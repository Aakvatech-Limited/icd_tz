import frappe
import requests
from frappe import _
from frappe.utils import cint

from tanesw_integration import outage
from tanesw_integration.credentials import (
	assert_write_operations_enabled,
	build_token_cache_key,
	get_current_user_account,
)


def _settings():
	return frappe.get_single("TANeSW Settings")


def _get_session():
	import requests

	s = requests.Session()
	settings = _settings()
	s.headers.update({"Accept": "application/json", "accept-language": "EN"})
	s.verify = bool(cint(settings.verify_tls))
	return s, settings


def _cache_token(key, token, ttl):
	frappe.cache.set_value(key, token, expires_in_sec=ttl)


def _cached_token(key):
	return frappe.cache.get_value(key)


def _invalidate_cached_token():
	account = get_current_user_account()
	key = build_token_cache_key(account.user, account.company_code, account.role_code)
	frappe.cache.delete_value(key)


def _unreachable(reason):
	return _(
		"TANeSW (tanesw.tra.go.tz) did not respond in time ({0}). TRA's system is slow or down; "
		"nothing was changed. Try again in a few minutes."
	).format(reason)


def _login_post(session, url, payload, timeout, account):
	"""A login call is safe to repeat, so a timeout or dropped connection gets one retry.
	After that the user sees a plain message instead of a traceback. The account's connection
	status is updated, but the 5-minute lock-out is NOT set: TRA being slow says nothing about the password."""
	outage.guard()
	for attempt in range(2):
		try:
			r = session.post(url, json=payload, timeout=timeout)
			outage.resume()  # TANeSW answered
			return r
		except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
			if attempt == 0:
				continue
			account.db_set("last_connection_status", "Failed")
			account.db_set("last_connection_error", f"login: {type(exc).__name__}")
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- keep the status even though the request ends in an error
			outage.pause(f"login: {type(exc).__name__}")
			frappe.throw(
				_unreachable(type(exc).__name__),
				exc=outage.TANeSWUnreachable,
				title=_("TANeSW not responding"),
			)


def authenticate(account=None):
	if account is None:
		account = get_current_user_account()

	cache_key = build_token_cache_key(account.user, account.company_code, account.role_code)
	cached = _cached_token(cache_key)
	if cached:
		return cached

	# A rejected login is remembered for a few minutes: every screen fires several calls at once, and
	# retrying a wrong ID/password on each of them can get the TRA account locked.
	fail_key = f"{cache_key}:login-failed"
	failed = frappe.cache.get_value(fail_key)
	if failed:
		frappe.throw(failed, title=_("TANeSW login rejected"))

	session, settings = _get_session()
	base = settings.base_url.rstrip("/")
	timeout = cint(settings.request_timeout) or 30
	password = account.get_password("tanesw_password", raise_exception=False)
	if not account.tanesw_id or not password:
		frappe.throw(
			_("TANeSW User Account {0} has no TANeSW ID or password").format(account.name),
			title=_("TANeSW login"),
		)

	r1 = _login_post(
		session,
		f"{base}/ptl/api/v1/ptl/comn/comn/login/valdn",
		{"id": account.tanesw_id, "pwd": password, "lgnTp": "EXT"},
		timeout,
		account,
	)
	if r1.status_code in (400, 401, 403):
		msg = _(
			"TANeSW rejected the login for TANeSW ID {0} (HTTP {1}). Check the TANeSW ID (your portal user name, "
			"e.g. JOHN.DOE, not the password) and the password in TANeSW User Account {2}. "
			"No further login attempts will be made for 5 minutes, to avoid locking the TRA account."
		).format(frappe.bold(account.tanesw_id), r1.status_code, frappe.bold(account.name))
		frappe.cache.set_value(fail_key, msg, expires_in_sec=300)
		account.db_set("last_connection_status", "Failed")
		account.db_set("last_connection_error", f"login/valdn HTTP {r1.status_code}")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- keep the status even though the request ends in an error
		frappe.throw(msg, title=_("TANeSW login rejected"))
	r1.raise_for_status()

	r2 = _login_post(
		session,
		f"{base}/ptl/api/v1/ptl/comn/comn/login",
		{
			"id": account.tanesw_id,
			"pwd": password,
			"coTin": account.company_tin,
			"coTpCd": account.company_type,
			"coCd": account.company_code,
		},
		timeout,
		account,
	)
	r2.raise_for_status()

	token = (r2.headers.get("Authorization") or r2.headers.get("authorization") or "").replace("Bearer ", "")
	if not token:
		frappe.throw(_("TANeSW login succeeded but no bearer token was returned"))

	ttl = cint(settings.token_cache_duration) or 1800
	_cache_token(cache_key, token, ttl)

	account.db_set("last_successful_connection", frappe.utils.now())
	account.db_set("last_connection_status", "Successful")
	account.db_set("last_connection_error", "")

	return token


def _handle_tanesw_error(response, path):
	status = response.status_code
	try:
		body = response.json()
		msg = (
			body.get("message")
			or body.get("msg")
			or body.get("errorMessage")
			or body.get("error")
			or str(body)
		)
	except Exception:
		import re

		text = response.text or ""
		# Tomcat error pages: show "<h1>" text, not the raw HTML
		m = re.search(r"<h1>(.*?)</h1>", text, re.S) or re.search(r"<title>(.*?)</title>", text, re.S)
		msg = re.sub(r"<[^>]+>", " ", m.group(1)).strip() if m else (text[:200] or "No details")
	if status == 500:
		frappe.throw(_("TANeSW server error on {0}: {1}").format(path, msg), title=_("TANeSW Error"))
	elif status == 404:
		frappe.throw(_("TANeSW resource not found: {0}").format(path), title=_("Not Found"))
	else:
		frappe.throw(
			_("TANeSW returned HTTP {0} on {1}: {2}").format(status, path, msg), title=_("TANeSW Error")
		)


def plain_request_args():
	"""Base URL, headers (with a valid token), timeout and TLS setting, for plain HTTP reads made in worker threads.

	The threads get no frappe context and so no database connection of their own: the token is fetched here, in the
	request's own thread, and the threads only send HTTP requests."""
	outage.guard()
	token = authenticate()
	session, settings = _get_session()
	headers = dict(session.headers)
	headers["Authorization"] = f"Bearer {token}"
	return settings.base_url.rstrip("/"), headers, cint(settings.request_timeout) or 30, session.verify


BL_LIST_PATH = "/cgm/api/v1/cgme/mnfs/imp/imp-mnfs/mrn"


def _authed_get(path, params=None):
	for attempt in range(2):
		token = authenticate()
		session, settings = _get_session()
		session.headers["Authorization"] = f"Bearer {token}"
		base = settings.base_url.rstrip("/")
		timeout = cint(settings.request_timeout) or 30

		clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
		outage.guard()
		try:
			r = session.get(f"{base}{path}", params=clean, timeout=timeout)
			outage.resume()  # TANeSW answered
		except requests.exceptions.RequestException as exc:
			# ponytail: one retry covers the frequent TANeSW connect timeouts;
			# writes are deliberately NOT retried (double-submit risk).
			if attempt == 0:
				continue
			outage.pause(f"{path}: {type(exc).__name__}")
			frappe.throw(
				_unreachable(type(exc).__name__),
				exc=outage.TANeSWUnreachable,
				title=_("TANeSW not responding"),
			)
		if r.status_code == 401 and attempt == 0:
			_invalidate_cached_token()
			continue
		if r.status_code >= 400:
			_handle_tanesw_error(r, path)
		return r.json()


def _authed_delete(path):
	"""DELETE is always a write: gated, and never retried except on 401."""
	assert_write_operations_enabled()
	for attempt in range(2):
		token = authenticate()
		session, settings = _get_session()
		session.headers["Authorization"] = f"Bearer {token}"
		base = settings.base_url.rstrip("/")
		timeout = cint(settings.request_timeout) or 30
		r = session.delete(f"{base}{path}", timeout=timeout)
		if r.status_code == 401 and attempt == 0:
			_invalidate_cached_token()
			continue
		if r.status_code >= 400:
			_handle_tanesw_error(r, path)
		try:
			return r.json()
		except Exception:
			return {"status": "ok", "text": r.text}


def _authed_post(path, payload=None, *, is_write=False):
	if is_write:
		assert_write_operations_enabled()

	for attempt in range(2):
		token = authenticate()
		session, settings = _get_session()
		session.headers["Authorization"] = f"Bearer {token}"
		base = settings.base_url.rstrip("/")
		timeout = cint(settings.request_timeout) or 30

		outage.guard()
		try:
			r = session.post(f"{base}{path}", json=payload or {}, timeout=timeout)
			outage.resume()  # TANeSW answered
		except requests.exceptions.RequestException as exc:
			outage.pause(f"{path}: {type(exc).__name__}")
			# Never retried: TANeSW may have received a write before the line dropped.
			if is_write:
				frappe.throw(
					_(
						"TANeSW did not answer in time ({0}). It may or may not have recorded this "
						"submission: check it on TANeSW before submitting again."
					).format(type(exc).__name__),
					title=_("TANeSW not responding"),
				)
			frappe.throw(
				_unreachable(type(exc).__name__),
				exc=outage.TANeSWUnreachable,
				title=_("TANeSW not responding"),
			)
		if r.status_code == 401 and attempt == 0:
			_invalidate_cached_token()
			continue
		if r.status_code >= 400:
			_handle_tanesw_error(r, path)
		try:
			return r.json()
		except Exception:
			return {"status": "ok", "text": r.text}


# --- Read endpoints ---


def get_manifest_list(dt_from, dt_to, mrn=None, page=0, size=10):
	params = {
		"page": int(page),
		"size": int(size),
		"srchDtFrom": dt_from,
		"srchDtTo": dt_to,
		"trptModeCd": "10",
		"srchTp": "mrn",
	}
	if mrn and mrn.strip():
		params["srchTpCn"] = mrn.strip()
	return _authed_get("/cgm/api/v1/cgme/mnfs/imp/imp-mnfs/info", params)


def get_manifest(mrn):
	return _authed_get(f"/cgm/api/v1/cgme/mnfs/imp/imp-mnfs/{mrn}")


def get_manifest_excel(mrn):
	"""Download 5-sheet official manifest Excel from TANeSW as raw bytes."""
	for attempt in range(2):
		token = authenticate()
		session, settings = _get_session()
		session.headers["Authorization"] = f"Bearer {token}"
		base = settings.base_url.rstrip("/")
		timeout = cint(settings.request_timeout) or 30
		r = session.post(
			f"{base}/cgm/api/v1/cgme/mnfs/imp/imp-mnfs/excel-dwnl", json={"mrn": mrn}, timeout=timeout
		)
		if r.status_code == 401 and attempt == 0:
			_invalidate_cached_token()
			continue
		if r.status_code >= 400:
			_handle_tanesw_error(r, "/cgm/api/v1/cgme/mnfs/imp/imp-mnfs/excel-dwnl")
		return r.content


def get_bl_list(mrn, page=0, size=50):
	return _authed_get(BL_LIST_PATH, {"mrn": mrn, "trptModeCd": "10", "page": page, "size": size})


def get_bl_containers(mrn, page=0, size=50):
	return _authed_get("/cgm/api/v1/cgme/mnfs/imp/imp-mnfs/bl", {"key": mrn, "page": page, "size": size})


def search_transfers(
	mrn=None, dt_from=None, dt_to=None, page=0, size=100, dclr_no=None, cntr_no=None, dptr_wrhs_cd=None
):
	# Live-verified: TANeSW ignores mrn / srchDtStrt / srchDtEnd / srchDtTp and
	# only these parameter names filter the declaration list.
	params = {"page": page, "size": size}
	if mrn:
		params["srchMrn"] = mrn.strip()
	if dt_from:
		params["srchDtTpFrom"] = dt_from
	if dt_to:
		params["srchDtTpTo"] = dt_to
	if dclr_no:
		params["srchDclrNo"] = dclr_no.strip()
	if cntr_no:
		params["srchCntrNo"] = cntr_no.strip()
	if dptr_wrhs_cd:
		params["srchDptrWrhsCd"] = dptr_wrhs_cd
	return _authed_get("/cgm/api/v1/cgme/trsf/icd/dcla", params)


def get_transfer_detail(dclr_no):
	return _authed_get(f"/cgm/api/v1/cgme/trsf/icd/dcla/{dclr_no}")


def search_usable_cargo(dt_from=None, dt_to=None, cargo_type="C", mrn=None, page=0, size=25):
	"""Usable Cargo to ICD List (screen cgme0301003q) — manifests carrying cargo
	still available to declare. Live-verified: only srchArvlDtFrom / srchArvlDtTo /
	srchCagTp / srchMrn filter this list; unprefixed names return zero rows."""
	params = {"page": page, "size": size}
	if dt_from:
		params["srchArvlDtFrom"] = dt_from
	if dt_to:
		params["srchArvlDtTo"] = dt_to
	if cargo_type:
		params["srchCagTp"] = cargo_type
	if mrn:
		params["srchMrn"] = mrn.strip()
	return _authed_get("/cgm/api/v1/cgme/trsf/icd/dcla/trgt", params)


def get_declaration_template(mrn):
	""":returns: origin skeleton for a NEW ICD transfer declaration — the warehouse
	pair (port -> our ICD) is pre-filled, container/vehicle lists are empty."""
	return _authed_get(f"/cgm/api/v1/cgme/trsf/icd/dcla/trgt/{(mrn or '').strip()}")


def get_available_containers(mrn, dclr_no="", crn="", cargo_type="CDD", is_bulk="N", page=0, size=50):
	"""Containers TANeSW has resolved for this MRN and still considers declarable.

	Live-verified: works without a draft dclrNo, and its row count equals
	"Target - Declared" on the usable-cargo grid. cagDclrTpCd=CDD is the ICD
	transfer declaration document class."""
	params = {
		"page": page,
		"size": size,
		"mrn": mrn,
		"cagDclrTpCd": cargo_type or "CDD",
		"isBulk": is_bulk or "N",
	}
	if dclr_no:
		params["dclrNo"] = dclr_no
	if crn:
		params["crn"] = crn
	return _authed_get("/cgm/api/v1/cgme/trsf/icd/dcla/trgt/cntr", params)


def search_crn(search_type=None, search_no=None, srch_cntr_no=None, srch_bl_no=None):
	params = {}
	if srch_cntr_no:
		params["srchCntrNo"] = srch_cntr_no
	elif srch_bl_no:
		params["srchBlNo"] = srch_bl_no
	elif str(search_type).lower() in ("cntr", "container") or (search_no and not search_type):
		params["srchCntrNo"] = search_no
	elif str(search_type).lower() in ("bl", "mbl"):
		params["srchBlNo"] = search_no
	else:
		params["srchCntrNo"] = search_no
	return _authed_get("/cgm/api/v1/cgme/trkng/srch", params)


def get_crn_history(crn):
	return _authed_get(f"/cgm/api/v1/cgme/trkng/{crn}")


def get_carry_in_list(
	dt_from=None, dt_to=None, page=0, size=50, report_status="N,P,Y", container_no=None, crn=None
):
	params = {
		"srchAprvDtFrom": dt_from,
		"srchAprvDtTo": dt_to,
		"srchRptStat": report_status,
		"page": page,
		"size": size,
	}
	if container_no:
		params["srchCntrNo"] = container_no
	if crn:
		params["srchCrn"] = crn
	return _authed_get("/cgm/api/v1/cgme/wrhs/cri", params)


def get_carry_in_detail(crn, wrhs_cd, cri_base_no):
	return _authed_get(
		f"/cgm/api/v1/cgme/wrhs/cri/imp/{crn}",
		{"wrhsCd": wrhs_cd, "criBaseNo": cri_base_no},
	)


def get_carry_out_list(dt_from=None, dt_to=None, page=0, size=50):
	return _authed_get(
		"/cgm/api/v1/cgme/wrhs/cro",
		{"srchAprvDtFrom": dt_from, "srchAprvDtTo": dt_to, "page": page, "size": size},
	)


def get_carry_out_detail(cro_base_no):
	return _authed_get("/cgm/api/v1/cgme/wrhs/cro/dtl", {"croBaseNo": cro_base_no})


def get_carry_out_containers(cro_base_no):
	return _authed_get("/cgm/api/v1/cgme/wrhs/cro/cntr", {"croBaseNo": cro_base_no})


# --- Joint Inspection (LPCO > Joint Inspection, screens ESWE-0105-001S..007Q) ---
# Paths and parameter names as the portal bundle (eswe main.js) sends them.
JNT = "/esw/api/v1/eswe/jnt/insc"


def split_tansad(value):
	"""'TZDL-26-1747957' / 'TZDL261747957' -> ('TZDL', '26', '1747957')."""
	raw = "".join(ch for ch in (value or "") if ch.isalnum()).upper()
	return raw[:4], raw[4:6], raw[6:13]


def split_reference(value):
	"""'100000001-26-1234567' -> ('100000001', '26', '1234567')."""
	raw = "".join(ch for ch in (value or "") if ch.isalnum())
	return raw[:9], raw[9:11], raw[11:18]


def get_insc_target_list(params, page=0, size=10):
	"""Inspection Target List (005Q). params: srchDtStrt, srchDtEnd (required),
	cpltYn (Y/N), cstmOfceCd, tansadYy, tansadSrno."""
	return _authed_get(f"{JNT}/trgt", {"page": int(page), "size": int(size), **(params or {})})


def get_insc_target_selectivity(tansad_no):
	return _authed_get(f"{JNT}/trgt/sltv/{tansad_no}")


def get_insc_target_items(tansad_no):
	return _authed_get(f"{JNT}/trgt/sltv/itm/{tansad_no}")


def get_insc_target_scanning(tansad_no):
	return _authed_get(f"{JNT}/trgt/scnn/{tansad_no}")


def get_insc_target_guideline(tansad_no):
	return _authed_get(f"{JNT}/trgt/gdln/{tansad_no}")


def get_booking_list_raw(params, page=0, size=10):
	"""Inspection Booking List (002Q). params: srchDtStrt, srchDtEnd, srchStatCd,
	srchWrhsCd, cstmOfceCd, tansadYy, tansadSrno, reffTin, reffYy, reffSrno."""
	return _authed_get(f"{JNT}/bkng", {"page": int(page), "size": int(size), **(params or {})})


def get_booking_list(
	dt_from=None, dt_to=None, wrhs_cd=None, page=0, size=50, tansad_no=None, reference_no=None, status=None
):
	"""Backwards-compatible wrapper around get_booking_list_raw."""
	params = {"srchDtStrt": dt_from, "srchDtEnd": dt_to, "srchWrhsCd": wrhs_cd, "srchStatCd": status}
	if tansad_no:
		params.update(
			dict(zip(("cstmOfceCd", "tansadYy", "tansadSrno"), split_tansad(tansad_no), strict=True))
		)
	if reference_no:
		params.update(
			dict(zip(("reffTin", "reffYy", "reffSrno"), split_reference(reference_no), strict=True))
		)
	return get_booking_list_raw(params, page, size)


def get_booking_detail(tansad_no):
	"""Booking Details (003S): result.content.{jntInscBkngInfo, tansadInfo, blInfo,
	cntrInfo, jntInscCntrInfo}."""
	return _authed_get(f"{JNT}/bkng/{tansad_no}")


def get_approval_history(tansad_no):
	"""Approval History tab of 003S: aprvHistList.content[]."""
	return _authed_get(f"{JNT}/aprv-hist/{tansad_no}")


def get_booking_app_info(tansad_no):
	return _authed_get(f"{JNT}/app-bkng-info", {"tansadNo": tansad_no})


def get_booking_approval_info(tansad_no):
	return _authed_get(f"{JNT}/app-aprv-info", {"tansadNo": tansad_no})


def get_inspection_results(tansad_no, page=0, size=10):
	"""Inspection Result Search (007Q). TANSAD is mandatory on the portal."""
	cstm, yy, srno = split_tansad(tansad_no)
	return _authed_get(
		f"{JNT}/app-rslt-list",
		{
			"page": int(page),
			"size": int(size),
			"cstmOfceCd": cstm,
			"tansadYy": yy,
			"tansadSrno": srno,
			"tansadNo": f"{cstm}{yy}{srno}",
		},
	)


def get_inspection_attachments(tansad_no, page=0, size=10):
	return _authed_get(f"{JNT}/insc-atcm-list", {"page": int(page), "size": int(size), "tansadNo": tansad_no})


def get_tin_no_list(tin_no=""):
	payload = {}
	if tin_no:
		payload["tinNo"] = tin_no
	return _authed_post("/ptl/api/v1/ptle/extptl/comnppup/tin-no-list", payload, is_write=False)


# --- Portal lookups (the code/name popups every screen loads) ---


def get_common_codes(comn_cd):
	"""Common code list, e.g. RKM0019 booking status, ESW0076 inspection type."""
	return _authed_get("/ptl/api/v1/ptle/extptl/comnppup/comn-cd", {"comnCd": comn_cd, "size": 999999})


def get_warehouses():
	# Exactly as the portal's code lookup builds it (HZ.getCode area "wrhsCd"): the empty filters are part
	# of the request. Without them TANeSW answers "An error occurred".
	return _authed_get(
		"/ptl/api/v1/ptle/extptl/comnppup/wrhs?coDclaCd=&wrhsNm=&wrhsOprtTpCd=&cstmOfceCd=&size=999999"
	)


def get_organisations(org_tp_cd="01"):
	return _authed_get("/ptl/api/v1/ptle/extptl/comnppup/org", {"orgTpCd": org_tp_cd, "size": 999999})


def get_user_info():
	"""Logged-in TANeSW user context (coNm, coDclaTp, coDclaCd, tin, cfaTin, authList)."""
	return _authed_get("/ptl/api/v1/ptl/comn/comn/login/usrInfo")


def get_do_bl_info(crn):
	return _authed_get(f"/esw/api/v1/eswe/cag/do/bl-info/{crn}")


def get_do_list(crn=None, page=0, size=50):
	params = {"page": page, "size": size}
	if crn:
		params["crn"] = crn
	return _authed_get("/esw/api/v1/eswe/cag/do/list", params)


# --- Write endpoints ---


def register_carry_in(payload):
	return _authed_post("/cgm/api/v1/cgme/wrhs/cri/imp", payload, is_write=True)


def submit_carry_in(payload):
	return _authed_post("/cgm/api/v1/cgme/wrhs/cri/imp/sbmt", payload, is_write=True)


save_carry_in_imp = register_carry_in
submit_carry_in_imp = submit_carry_in


def submit_carry_out(payload):
	return _authed_post("/cgm/api/v1/cgme/wrhs/cro/rgst", payload, is_write=True)


def submit_booking(payload):
	"""Booking Registration (001S). Portal path is /bkng/sbmt, not /bkng."""
	return _authed_post(f"{JNT}/bkng/sbmt", payload, is_write=True)


def modify_booking(payload):
	return _authed_post(f"{JNT}/bkng/mdfy", payload, is_write=True)


def delete_booking(tansad_no):
	return _authed_delete(f"{JNT}/bkng/{tansad_no}")


def submit_objection(payload):
	return _authed_post(f"{JNT}/objt-sbmt", payload, is_write=True)


def submit_transfer(payload):
	return _authed_post("/cgm/api/v1/cgme/trsf/icd/dcla", payload, is_write=True)


def validate_carry_in_container(wrhs_cd, cntr_no, crn=""):
	return _authed_post(
		"/cgm/api/v1/cgme/wrhs/cri/imp/cntr/dtl",
		{"wrhsCd": wrhs_cd, "cntrNo": cntr_no, "crn": crn},
		is_write=False,
	)


def save_booking_approval(payload):
	return _authed_post(f"{JNT}/app-aprv-save", payload, is_write=True)


def submit_booking_approval(payload):
	return _authed_post(f"{JNT}/app-aprv-sbmt", payload, is_write=True)
