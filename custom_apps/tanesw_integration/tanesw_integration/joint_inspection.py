"""LPCO > Joint Inspection — server side for the `tanesw-joint-inspection` desk page.

Mirrors TANeSW screens:
  ESWE-0105-005Q  Inspection Target List          -> target_list
  ESWE-0105-006S  Inspection Target Details       -> target_detail
  ESWE-0105-001S  Joint Inspection Booking Reg.   -> register_booking
  ESWE-0105-002Q  Inspection Booking List         -> booking_list
  ESWE-0105-003S  Joint Inspection Booking Details-> booking_detail, approval_history, delete_booking
  ESWE-0105-004S  Booking Modify                  -> modify_booking
  (popup)         Booked Result Registration      -> result_registration_info, save_result_registration
  ESWE-0105-007Q  Inspection Result Search        -> inspection_results, inspection_attachments, submit_objection
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from tanesw_integration import api_client as tc
from tanesw_integration.credentials import get_current_user_account, require_tanesw_user
from tanesw_integration.hints import JSONish, Scalar

CODE_CACHE_TTL = 6 * 3600
USER_CACHE_TTL = 1800

# Fallbacks used only when the live lookup fails. RKM0019 was read from the
# portal's Status dropdown; the others are values TANeSW returns.
FALLBACK_CODES = {
	"RKM0019": {
		"A": "Received",
		"B": "Approved",
		"C": "Confirmed",
		"D": "Submitted",
		"E": "Rejected",
		"F": "Returned",
		"G": "Re-submit",
		"H": "Re-submitted",
		"I": "Inspected",
	},
	"ESW0076": {"I2": "OGA Inspection"},
	"ESW0009": {"VE": "Verification Officer"},
	# Cargo process status (read from the portal's ICD Transfer status checkboxes)
	"COM0023": {
		"A01": "REGISTERED",
		"A04": "SUBMITTED",
		"D01": "RECEIVED",
		"A05": "RECEIVED ERROR",
		"D06": "APPROVED",
		"D08": "REJECTED",
		"D09": "RETURNED",
		"G07": "CANCELED",
		"D15": "WAITING PAYMENT AFTER AUDIT",
	},
	"CGM0066": {"OWN": "Own Driving", "VEHC": "Vehicle"},
}

CARGO_TYPES = ["VEHICLE", "BULK", "LOOSE", "FCL", "LCL"]


# ----------------------------------------------------------------- helpers


def _parse(value):
	if isinstance(value, str):
		try:
			return frappe.parse_json(value)
		except Exception:
			return value
	return value


def _find_list(obj, marker, depth=0):
	"""Return the first list of dicts under obj whose rows contain `marker`.

	TANeSW wraps lists differently per endpoint ({xList: {content: [...]}},
	{content: [...]}, bare list) so lookups search instead of hard-coding."""
	if depth > 5:
		return None
	if isinstance(obj, list):
		if obj and isinstance(obj[0], dict) and marker in obj[0]:
			return obj
		for item in obj:
			found = _find_list(item, marker, depth + 1)
			if found:
				return found
	elif isinstance(obj, dict):
		for value in obj.values():
			found = _find_list(value, marker, depth + 1)
			if found:
				return found
	return None


def _find_key(obj, key, depth=0):
	if depth > 5:
		return None
	if isinstance(obj, dict):
		if key in obj and obj[key] not in (None, ""):
			return obj[key]
		for value in obj.values():
			found = _find_key(value, key, depth + 1)
			if found not in (None, ""):
				return found
	elif isinstance(obj, list):
		for item in obj:
			found = _find_key(item, key, depth + 1)
			if found not in (None, ""):
				return found
	return None


def _paged(res, list_key, page, size):
	"""Normalise a Spring page ({content, totalElements, totalPages, number} or
	{content, page:{...}}) into {content, page}."""
	container = res.get(list_key) if (isinstance(res, dict) and list_key) else None
	if container is None and isinstance(res, dict):
		# key not known for this endpoint: take the first {content: [...]} block
		container = next(
			(v for v in res.values() if isinstance(v, dict) and isinstance(v.get("content"), list)), res
		)
	if container is None:
		container = res
	if isinstance(container, list):
		rows, meta_src = container, {}
	else:
		rows = container.get("content") or []
		meta_src = container.get("page") if isinstance(container.get("page"), dict) else container
	total = cint(meta_src.get("totalElements")) if meta_src.get("totalElements") is not None else len(rows)
	pages = cint(meta_src.get("totalPages")) or max(1, -(-total // max(1, cint(size))))
	return {
		"content": rows,
		"page": {
			"number": cint(meta_src.get("number", page)),
			"size": cint(size),
			"totalElements": total,
			"totalPages": pages,
		},
	}


def _content(res, key):
	block = res.get(key) if isinstance(res, dict) else None
	if isinstance(block, dict) and "content" in block:
		return block["content"]
	return block


def _join_tansad(value):
	cstm, yy, srno = tc.split_tansad(value)
	return f"{cstm}{yy}{srno}"


# ----------------------------------------------------------------- context & lookups


def _user_info():
	account = get_current_user_account()
	key = f"tanesw:jnt:usrinfo:{account.name}"
	cached = frappe.cache.get_value(key)
	if cached:
		return cached
	info = {}
	try:
		raw = tc.get_user_info()
		for k in (
			"coNm",
			"coDclaTp",
			"coDclaCd",
			"tin",
			"cfaTin",
			"usrId",
			"usrNm",
			"telNo",
			"cstmCd",
			"authList",
		):
			info[k] = _find_key(raw, k)
	except Exception:
		frappe.log_error(title="TANeSW usrInfo lookup failed")
	info["coDclaTp"] = info.get("coDclaTp") or account.company_type
	info["coDclaCd"] = info.get("coDclaCd") or account.warehouse_code or account.company_code
	info["tin"] = info.get("tin") or account.company_tin
	frappe.cache.set_value(key, info, expires_in_sec=USER_CACHE_TTL)
	return info


@frappe.whitelist(methods=["POST"])
def context():
	"""Who is using the page: drives the same defaults the portal sets on load
	(CFA -> reffTin locked to own TIN; warehouse -> srchWrhsCd = own code)."""
	info = _user_info()
	auth = info.get("authList") or []
	if isinstance(auth, str):
		auth = [a.strip() for a in auth.split(",")]
	return {
		"is_cfa": info.get("coDclaTp") == "C",
		"company_type": info.get("coDclaTp"),
		"warehouse_code": info.get("coDclaCd"),
		"tin": info.get("tin"),
		"company_name": info.get("coNm"),
		"auth_list": auth,
		"write_enabled": cint(frappe.db.get_single_value("TANeSW Settings", "enable_write_operations"))
		or cint(frappe.db.get_single_value("TANeSW Settings", "test_mode")),
		"test_mode": cint(frappe.db.get_single_value("TANeSW Settings", "test_mode")),
		"cargo_types": CARGO_TYPES,
	}


@frappe.whitelist(methods=["POST"])
def codes(comn_cds: JSONish):
	"""{comnCd: {value: label}} for each requested common-code group."""
	require_tanesw_user()  # cached and fallback codes are returned without calling TANeSW
	comn_cds = _parse(comn_cds) or []
	if isinstance(comn_cds, str):
		comn_cds = [c.strip() for c in comn_cds.split(",") if c.strip()]
	out = {}
	for cd in comn_cds:
		key = f"tanesw:jnt:code:{cd}"
		mapping = frappe.cache.get_value(key)
		if not mapping:
			mapping = {}
			try:
				rows = _find_list(tc.get_common_codes(cd), "cdVldVal") or []
				mapping = {r["cdVldVal"]: r.get("cdVldValNm") or r["cdVldVal"] for r in rows}
			except Exception:
				frappe.log_error(title=f"TANeSW code lookup failed: {cd}")
			if mapping:
				frappe.cache.set_value(key, mapping, expires_in_sec=CODE_CACHE_TTL)
			else:
				mapping = FALLBACK_CODES.get(cd, {})
		out[cd] = mapping
	return out


@frappe.whitelist(methods=["POST"])
def parties():
	"""Warehouse (coDclaCd -> wrhsNm) and OGA (orgCd -> orgNm) names, used to
	render '[WAREHOUSE CODE] WAREHOUSE NAME' style labels."""
	require_tanesw_user()  # a cached answer is returned without calling TANeSW
	key = "tanesw:jnt:parties:v2"
	cached = frappe.cache.get_value(key)
	if cached:
		return cached
	result = {"warehouses": {}, "organisations": {}, "customs": {}}
	try:
		rows = _find_list(tc.get_warehouses(), "coDclaCd") or []
		result["warehouses"] = {r["coDclaCd"]: r.get("wrhsNm") for r in rows}
	except Exception:
		frappe.log_error(title="TANeSW warehouse lookup failed")
	try:
		rows = _find_list(tc.get_organisations("01"), "orgCd") or []
		result["organisations"] = {r["orgCd"]: r.get("orgNm") for r in rows}
	except Exception:
		frappe.log_error(title="TANeSW organisation lookup failed")
	try:  # customs offices, as the portal's code lookup (area cstmCd) builds it
		rows = (
			_find_list(
				tc._authed_get(
					"/ptl/api/v1/ptle/extptl/comnppup/cstm?cstmOfceCd=&cstmNm=&dclrYn=&cstmTpCd=&cstmOfceCdArr=&size=999999"
				),
				"cstmOfceCd",
			)
			or []
		)
		result["customs"] = {r["cstmOfceCd"]: r.get("cstmNm") for r in rows}
	except Exception:
		frappe.log_error(title="TANeSW customs office lookup failed")
	if result["warehouses"] and result["organisations"]:
		frappe.cache.set_value(key, result, expires_in_sec=CODE_CACHE_TTL)
	elif result["warehouses"] or result["organisations"]:
		frappe.cache.set_value(key, result, expires_in_sec=300)  # partial: retry the failed lookup soon
	return result


# ----------------------------------------------------------------- 005Q / 006S  target


@frappe.whitelist(methods=["POST"])
def target_list(
	srch_dt_strt: Scalar,
	srch_dt_end: Scalar,
	cplt_yn: Scalar = "N",
	cstm_ofce_cd: Scalar | None = None,
	tansad_yy: Scalar | None = None,
	tansad_srno: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	if not (srch_dt_strt and srch_dt_end):
		frappe.throw(_("TANSAD Date range is required"))
	res = tc.get_insc_target_list(
		{
			"srchDtStrt": srch_dt_strt,
			"srchDtEnd": srch_dt_end,
			"cpltYn": cplt_yn or "N",
			"cstmOfceCd": (cstm_ofce_cd or "").upper(),
			"tansadYy": tansad_yy,
			"tansadSrno": tansad_srno,
		},
		page,
		size,
	)
	return _paged(res, "jntInscTrgtList", page, size)


@frappe.whitelist(methods=["POST"])
def target_detail(tansad_no: Scalar):
	tansad_no = _join_tansad(tansad_no)
	out = {"criteria": [], "criteria_change": [], "items": [], "scanning": None, "guideline": None}
	sltv = tc.get_insc_target_selectivity(tansad_no)
	trgt = (_content(sltv, "trgtInfo") or {}) if isinstance(sltv, dict) else {}
	out["criteria"] = trgt.get("resultCriteria") or []
	out["criteria_change"] = trgt.get("resultCriteriaChange") or []
	for key, fn, block in (
		("items", tc.get_insc_target_items, "jntInscTrgtItmList"),
		("scanning", tc.get_insc_target_scanning, "scanning"),
		("guideline", tc.get_insc_target_guideline, "isprGdlnInfo"),
	):
		try:
			out[key] = _content(fn(tansad_no), block)
		except Exception:
			# ponytail: the portal also renders 006S when a side panel fails
			frappe.clear_messages()
	return out


# ----------------------------------------------------------------- 002Q / 003S  booking


@frappe.whitelist(methods=["POST"])
def booking_list(
	srch_dt_strt: Scalar | None = None,
	srch_dt_end: Scalar | None = None,
	srch_stat_cd: Scalar | None = None,
	srch_wrhs_cd: Scalar | None = None,
	cstm_ofce_cd: Scalar | None = None,
	tansad_yy: Scalar | None = None,
	tansad_srno: Scalar | None = None,
	reff_tin: Scalar | None = None,
	reff_yy: Scalar | None = None,
	reff_srno: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	ctx = _user_info()
	params = {
		"srchDtStrt": srch_dt_strt,
		"srchDtEnd": srch_dt_end,
		"srchStatCd": srch_stat_cd,
		"cstmOfceCd": (cstm_ofce_cd or "").upper(),
		"tansadYy": tansad_yy,
		"tansadSrno": tansad_srno,
		"reffTin": reff_tin,
		"reffYy": reff_yy,
		"reffSrno": reff_srno,
	}
	# Same scoping the portal applies on load: CFA sees its own references,
	# everyone else sees bookings at its own warehouse.
	if ctx.get("coDclaTp") == "C":
		params["reffTin"] = ctx.get("tin")
	else:
		params["srchWrhsCd"] = srch_wrhs_cd or ctx.get("coDclaCd")
	return _paged(tc.get_booking_list_raw(params, page, size), "jntInscBkngList", page, size)


@frappe.whitelist(methods=["POST"])
def booking_detail(tansad_no: Scalar):
	res = tc.get_booking_detail(_join_tansad(tansad_no))
	data = (res.get("result") or {}).get("content") if isinstance(res, dict) else None
	return data or {}


@frappe.whitelist(methods=["POST"])
def approval_history(tansad_no: Scalar):
	res = tc.get_approval_history(_join_tansad(tansad_no))
	return _content(res, "aprvHistList") or []


def _booking_dto(form, ctx, modify=False):
	tansad = _join_tansad(form.get("tansad_no"))
	if not tansad or len(tansad) < 13:
		frappe.throw(_("TANSAD No. is required"))
	dto = {
		"tansadNo": tansad,
		"coNm": ctx.get("coNm"),
		"mdfyGodsLoctWrhsCd": form.get("mdfy_gods_loct_wrhs_cd") or None,
		"bkngRqstDt": form.get("bkng_dt"),
		"cntrLstCn": form.get("cntr_lst_cn"),
		"blNo": form.get("bl_no"),
		"jntInscZoneAddr": form.get("jnt_insc_zone_addr"),
	}
	if modify:
		dto["bkngMdfyRqstDt"] = form.get("bkng_mdfy_rqst_dt")
	else:
		dto.update(
			{
				"godsLoctWrhsCd": form.get("gods_loct_wrhs_cd"),
				"dcltTin": ctx.get("cfaTin"),
				"csclPlnCd": form.get("cscl_pln_cd"),
				"regmCd": form.get("regm_cd"),
				"gpcCd": form.get("gpc_cd"),
				"epcCd": form.get("epc_cd"),
				"dstnCntyCd": form.get("dstn_cnty_cd"),
				"prcsStatCd": form.get("prcs_stat_cd"),
			}
		)
	return {"esweJntInscBkngGnrlMDto": dto}


@frappe.whitelist(methods=["POST"])
def register_booking(form: JSONish):
	"""Booking Registration popup (001S) — opened from the Target List 'Booking'
	button or from a [G] Re-submit row on the Booking List."""
	form = _parse(form) or {}
	for field, label in (
		("bl_no", "B/L No"),
		("bkng_dt", "Booking Date"),
		("gods_loct_wrhs_cd", "Cargo Deposit Station"),
		("cntr_lst_cn", "Cargo Type"),
	):
		if not form.get(field):
			frappe.throw(_("{0} is required").format(label))
	if form.get("is_resubmit") and not form.get("mdfy_gods_loct_wrhs_cd"):
		frappe.throw(_("Modified Cargo Deposit Station is required"))
	if getdate(form["bkng_dt"]) < getdate(today()):
		frappe.throw(_("Booking Date cannot be before today"))
	return tc.submit_booking(_booking_dto(form, _user_info()))


@frappe.whitelist(methods=["POST"])
def modify_booking(form: JSONish):
	"""Booking Modify popup (004S)."""
	form = _parse(form) or {}
	if not form.get("mdfy_gods_loct_wrhs_cd") or not form.get("bkng_mdfy_rqst_dt"):
		frappe.throw(_("Modified Cargo Deposit Station and Booking Modify Date are required"))
	if getdate(form["bkng_mdfy_rqst_dt"]) < getdate(today()):
		frappe.throw(_("Booking Modify Date must be today or later"))
	return tc.modify_booking(_booking_dto(form, _user_info(), modify=True))


@frappe.whitelist(methods=["POST"])
def delete_booking(tansad_no: Scalar):
	return tc.delete_booking(_join_tansad(tansad_no))


# ----------------------------------------------------------------- Booked Result Registration


@frappe.whitelist(methods=["POST"])
def result_registration_info(tansad_no: Scalar):
	tansad_no = _join_tansad(tansad_no)
	bkng = _content(tc.get_booking_app_info(tansad_no), "appBkngInfo") or {}
	aprv = {}
	try:
		aprv = _content(tc.get_booking_approval_info(tansad_no), "appAprvInfo") or {}
	except Exception:
		frappe.clear_messages()
	booking_date = bkng.get("bkngMdfyRqstDt") or bkng.get("bkngRqstDt")
	due = bool(booking_date) and getdate(booking_date) <= getdate(today())
	return {
		"booking": bkng,
		"approval": aprv,
		"can_save": due,  # portal hides Save until the booked date arrives
		"can_confirm": due and bool(aprv.get("prcssStatCd")),  # Confirm only after a Save
		"needs_modify_date": not due or bool(bkng.get("bkngMdfyRqstDt")),
	}


@frappe.whitelist(methods=["POST"])
def save_result_registration(
	tansad_no: Scalar,
	prcss_stat_cd: Scalar,
	prcss_rsn_cn: Scalar,
	rmrk: Scalar | None = None,
	bkng_mdfy_rqst_dt: Scalar | None = None,
	action: Scalar = "save",
):
	"""Save (app-aprv-save) or Confirm (app-aprv-sbmt) the verification result.

	Payload = the record app-aprv-info returned, overlaid with the officer's
	input, plus tansadNo and orgCd='N/A' — exactly what the portal sends."""
	if prcss_stat_cd != "AP":
		frappe.throw(_("Verification Result must be Approved (AP)"))
	if not (prcss_rsn_cn or "").strip():
		frappe.throw(_("Verification Reason is required"))
	tansad_no = _join_tansad(tansad_no)
	info = result_registration_info(tansad_no)
	if not info["can_save"] and not bkng_mdfy_rqst_dt:
		frappe.throw(_("The booking date has not arrived yet. Set a Booking Modify Date first."))

	if bkng_mdfy_rqst_dt:
		b = info["booking"]
		tc.modify_booking(
			{
				"esweJntInscBkngGnrlMDto": {
					"tansadNo": tansad_no,
					"coNm": _user_info().get("coNm"),
					"mdfyGodsLoctWrhsCd": b.get("mdfyGodsLoctWrhsCd"),
					"bkngRqstDt": b.get("bkngRqstDt"),
					"bkngMdfyRqstDt": bkng_mdfy_rqst_dt,
					"cntrLstCn": b.get("cntrLstCn"),
					"blNo": b.get("blNo"),
					"jntInscZoneAddr": b.get("jntInscZoneAddr"),
				}
			}
		)

	payload = {k: info["approval"].get(k) for k in ("asnmtUuid", "reffUuid", "exmpnTaxTpCd")}
	payload.update(
		{
			"prcssStatCd": prcss_stat_cd,
			"prcssRsnCn": prcss_rsn_cn,
			"rmrk": rmrk,
			"tansadNo": tansad_no,
			"orgCd": "N/A",
		}
	)
	if action == "sbmt":
		if not info["approval"].get("prcssStatCd"):
			frappe.throw(_("Save the result before confirming it"))
		return tc.submit_booking_approval(payload)
	return tc.save_booking_approval(payload)


# ----------------------------------------------------------------- 007Q  results


@frappe.whitelist(methods=["POST"])
def inspection_results(tansad_no: Scalar, page: Scalar = 0, size: Scalar = 10):
	cstm, yy, srno = tc.split_tansad(tansad_no)
	if not (cstm and yy and srno):
		frappe.throw(_("TANSAD No. is required"))
	return _paged(tc.get_inspection_results(tansad_no, page, size), "jntInscRsltList", page, size)


@frappe.whitelist(methods=["POST"])
def inspection_attachments(tansad_no: Scalar, page: Scalar = 0, size: Scalar = 10):
	return _paged(tc.get_inspection_attachments(_join_tansad(tansad_no), page, size), "atcmList", page, size)


@frappe.whitelist(methods=["POST"])
def submit_objection(
	tansad_no: Scalar,
	org_cd: Scalar,
	jnt_insc_rslt_accpt_cd: Scalar,
	apear_rsn: Scalar,
	bl_no: Scalar | None = None,
):
	"""Joint Inspection Objection Apply. Portal offers it only on OGAM0001 rows
	that do not already carry an objection number."""
	if not jnt_insc_rslt_accpt_cd or not (apear_rsn or "").strip():
		frappe.throw(_("Objection type and objection content are required"))
	if len(apear_rsn) > 2000:
		frappe.throw(_("Objection content is limited to 2000 characters"))
	ctx = _user_info()
	return tc.submit_objection(
		{
			"objtAplyAplcTin": ctx.get("tin"),
			"objtAplyYy": today()[2:4],
			"tansadNo": _join_tansad(tansad_no),
			"orgCd": org_cd,
			"blNo": bl_no,
			"jntInscRsltAccptCd": jnt_insc_rslt_accpt_cd,
			"apearRsn": apear_rsn,
		}
	)
