"""Cargo Mgmt — server side for the `tanesw-cargo` desk page.

Every path, parameter name and payload shape below is taken from the TANeSW
portal bundle (cgme main.js) and, for the list screens, confirmed against the
portal's own requests on 2026-10-28.

Manifest Management > Sea Import Manifest
  CGME-0101-025Q Manifest Information        -> manifest_info_list
  CGME-0101-026Q Sea Import MRN Details      -> mrn_detail, mrn_mbl_list
  CGME-0101-027Q Master BL Information       -> mbl_info
Transfer > ICD Transfer
  CGME-0301-001Q Expected ICD Transfer List  -> icd_expected_list
  CGME-0301-002Q ICD Transfer Declaration    -> icd_declaration_list, icd_declaration_delete_many
  CGME-0301-003Q (popup) Usable cargo        -> icd_usable_cargo
  CGME-0301-005S Declaration Registration    -> icd_declaration, icd_base_info, icd_declaration_save,
                                                icd_declaration_submit, icd_declaration_delete,
                                                icd_declaration_excel
  CGME-0301-006Q (popup) Container list      -> icd_target_containers, icd_add_containers
  CGME-0305-1xxQ (popups) driver / C45 / vehicle lookups -> trsf_driver_licence, trsf_transporters,
                                                trsf_vehicles
  CGME-0301-011Q Amendment List              -> icd_amendment_list
  CGME-0301-012S Amendment Registration      -> icd_amendment_targets, icd_amendment_init, icd_amendment,
                                                icd_amendment_save, icd_amendment_delete
  CGME-0301-021Q Cancellation List           -> icd_cancellation_list
  CGME-0301-022S Cancellation Registration   -> icd_cancellation, icd_cancellation_reference,
                                                icd_cancellation_save, icd_cancellation_delete
"""

import base64
import json
import re

import frappe
from frappe import _
from frappe.utils import cint, flt

from tanesw_integration import api_client as tc
from tanesw_integration.credentials import facility_code as legacy_facility_code
from tanesw_integration.credentials import require_tanesw_user
from tanesw_integration.hints import JSONish, Scalar
from tanesw_integration.joint_inspection import _content, _paged, _parse, _user_info
from tanesw_integration.outage import log_error as _outage_log_error

MNFS = "/cgm/api/v1/cgme/mnfs/imp/imp-mnfs"
ICD = "/cgm/api/v1/cgme/trsf/icd/dcla"
ICD_AMD = "/cgm/api/v1/cgme/trsf/icd/dcla/amd"
ICD_CNCL = "/cgm/api/v1/cgme/trsf/icd/dcla/cncl"
TRSF_COMN = "/cgm/api/v1/cgme/trsf/comn"
DCLR_AMD = "/cgm/api/v1/cgme/dclr/amd"

# Process status codes (portal Y0.PRCSS_STAT_CD / COM0023)
STATUS = {
	"A01": "REGISTERED",
	"A04": "SUBMITTED",
	"D01": "RECEIVED",
	"A05": "RECEIVED ERROR",
	"D06": "APPROVED",
	"D08": "REJECTED",
	"D09": "RETURNED",
	"G07": "CANCELED",
	"D15": "WAITING PAYMENT AFTER AUDIT",
}
DECLARATION_STATUSES = ["A01", "A04", "D01", "A05", "D06", "D08", "D09", "G07"]
AMD_CNCL_STATUSES = ["A01", "A04", "D01", "A05", "D06", "D08", "D09", "D15"]
EDITABLE_STATUSES = ("", "A01", "A05", "D09")


def _crn_search(value):
	"""Cargo reference typed the way screens show it (26XXX000000-1000, or the full 26XXX000000-1000-000)
	-> what TANeSW matches: no dashes/spaces. TANeSW does a partial match, so the 15-character form is used
	(the 18-character form with the trailing -000 returns nothing on the carry-out list)."""
	v = re.sub(r"[^0-9A-Za-z]", "", value or "").upper()
	return v[:15] if len(v) == 18 and v.endswith("000") else v


def _one(res, key):
	"""Detail payload: res[key].content, else the first {content: {...}} block."""
	val = _content(res, key)
	if val is None and isinstance(res, dict):
		val = next(
			(
				v["content"]
				for v in res.values()
				if isinstance(v, dict) and isinstance(v.get("content"), dict)
			),
			None,
		)
	return val


def _get(path, params=None):
	return tc._authed_get(path, params or {})


def _post(path, payload, write=True):
	return tc._authed_post(path, payload, is_write=write)


def _csv(value, default):
	value = _parse(value)
	if not value:
		return ",".join(default)
	if isinstance(value, list | tuple):
		return ",".join(value)
	return value


def _rows(value):
	value = _parse(value)
	return value if isinstance(value, list) else []


def _assert_editable(status, label):
	if (status or "") not in EDITABLE_STATUSES:
		frappe.throw(
			_("{0} in status {1} can no longer be changed").format(label, STATUS.get(status, status))
		)


def _write_result(res, key):
	"""Surface TANeSW pre-validation errors the way the portal's error popup does."""
	content = _content(res, key) if isinstance(res, dict) else None
	if isinstance(content, dict) and content.get("error") is True:
		errors = []
		for k in ("comnErrList", "indvErrList", "valdnMsgList"):
			errors += content.get(k) or []
		lines = []
		for e in errors:
			if isinstance(e, dict):
				lines.append(e.get("errMsg") or e.get("msg") or e.get("errCn") or frappe.as_json(e))
			else:
				lines.append(str(e))
		frappe.throw(
			"<br>".join(frappe.utils.escape_html(x) for x in lines) or _("TANeSW rejected the request"),
			title=_("TANeSW validation"),
		)
	return content if content is not None else res


# =================================================================== Manifest


def _all_pages(path, params, key, max_pages=10, size=1000):
	"""Every row of a TANeSW list, each once.

	TANeSW's ordering is not stable between page requests: read page by page, rows repeat and others are never
	returned, so vessels drop out of "Our Cargo" and others show twice. So read in one large page, drop repeats,
	and record it when TANeSW still returns fewer distinct rows than it says it has."""
	rows, seen, p, pages, total = [], set(), 0, 1, 0
	while p < pages and p < max_pages:
		res = _paged(_get(path, {"page": p, "size": size, **params}), key, p, size)
		for r in res.get("content") or []:
			uid = r.get("mrn") or json.dumps(r, sort_keys=True, default=str)
			if uid not in seen:
				seen.add(uid)
				rows.append(r)
		info = res.get("page") or {}
		pages, total = cint(info.get("totalPages")) or 1, cint(info.get("totalElements"))
		p += 1
	if total and len(rows) < total:
		frappe.log_error(
			title=f"TANeSW list incomplete: {path}",
			message=f"{len(rows)} distinct rows of {total} for {frappe.as_json(params)}",
		)
	return rows


def _page_out(rows, page, size, **extra):
	page, size = cint(page), cint(size) or 10
	return {
		"content": rows[page * size : (page + 1) * size],
		**extra,
		"page": {
			"number": page,
			"size": size,
			"totalElements": len(rows),
			"totalPages": (len(rows) + size - 1) // size if rows else 0,
		},
	}


@frappe.whitelist(methods=["POST"])
def manifest_info_list(
	srch_dt_from: Scalar,
	srch_dt_to: Scalar,
	srch_tp: Scalar = "mrn",
	srch_tp_cn: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
	our_only: Scalar = "ours",
):
	"""CGME-0101-025Q. srch_tp: mrn | vsslNm | tpaUid.

	The portal lists every sea manifest arriving in the window (all of Dar es Salaam). our_only narrows it:
	  ours (default) — manifests with any Master B/L whose place of delivery is our ICD (containers, bulk, loose).
	  0              — everything, as the portal shows.
	Allocation is read from each manifest's B/L list (dlvrPlcCd), which exists from the day the manifest
	is submitted — so vessels that have NOT arrived yet are included. TANeSW's Expected ICD Transfer list
	(/xptd) only covers arrived cargo (a range into the future returns no future vessels);
	its Target / Declared counts are added for manifests that appear there."""
	# Two views: "ours" = any B/L delivered to our ICD (containers, bulk, loose), or "0" = all.
	# Older values ("cntr", "bl", "1") all mean "ours".
	our_only = "0" if our_only in ("0", 0, None, "") else "ours"
	params = {
		"trptModeCd": "10",
		"srchDtFrom": srch_dt_from,
		"srchDtTo": srch_dt_to,
		"srchTp": srch_tp or "mrn",
		"srchTpCn": (srch_tp_cn or "").strip().upper(),
	}
	if our_only in ("0", 0):
		return _paged(
			_get(f"{MNFS}/info", {"page": cint(page), "size": cint(size), **params}), "impMnfsLst", page, size
		)

	from tanesw_integration import api as legacy  # shared, cached B/L walk

	code = legacy._our_facility_code()
	rows = _all_pages(f"{MNFS}/info", params, "impMnfsLst")
	summaries = legacy._our_bl_summaries([r.get("mrn") for r in rows], code)
	xptd = {}
	try:
		for r in _all_pages(
			f"{ICD}/xptd",
			{"srchArvlDtFrom": srch_dt_from, "srchArvlDtTo": srch_dt_to, "srchCagTp": "C"},
			"icdTrsfXptdLstData",
		):
			if r.get("mrn"):
				xptd[r["mrn"]] = r
	except Exception:
		_outage_log_error(title="TANeSW expected ICD list failed", message=frappe.get_traceback())
	# Three outcomes per manifest: verified ours, verified not ours, or UNVERIFIED (B/L list could not be read).
	# Unverified manifests are never put in the filtered list — a TANeSW outage must not fill it with other
	# ICDs' vessels — and never silently dropped either: they come back separately so the screen can say so.
	ours, unverified = [], []
	for r in rows:
		summ = summaries.get(r.get("mrn")) or {}
		if summ.get("scan_failed") or "our_bl_count" not in summ:
			unverified.append(
				{
					"mrn": r.get("mrn"),
					"vsslNm": r.get("vsslNm"),
					"arvlDt": r.get("actlArvlDt") or r.get("arvlXptdDt"),
				}
			)
			continue
		bls, cntrs = cint(summ.get("our_bl_count")), cint(summ.get("our_cntr_count"))
		if not bls:
			continue
		x = xptd.get(r.get("mrn")) or {}
		ours.append(
			{
				**r,
				"our_bl_count": bls,
				"our_cntr_count": cntrs,
				"our_trgt_count": cint(x["trgtCnt"]) if x.get("trgtCnt") not in (None, "") else None,
				"our_dclr_count": cint(x["dclrCnt"]) if x.get("dclrCnt") not in (None, "") else None,
			}
		)
	return _page_out(
		ours,
		page,
		size,
		basis=our_only,
		facility_code=code,
		scanned=len(rows),
		verified=len(rows) - len(unverified),
		unverified=unverified,
		complete=not unverified,
	)


@frappe.whitelist(methods=["POST"])
def mrn_detail(mrn: Scalar):
	"""CGME-0101-026Q summary block."""
	return _one(_get(f"{MNFS}/{mrn.strip().upper()}"), "impMnfsMrn") or {}


@frappe.whitelist(methods=["POST"])
def mrn_mbl_list(mrn: Scalar, page: Scalar = 0, size: Scalar = 10, our_only: Scalar = 0):
	"""CGME-0101-026Q Master B/L list. our_only=1 keeps B/Ls whose place of delivery is our warehouse."""
	mrn = mrn.strip().upper()
	if not cint(our_only):
		res = _get(f"{MNFS}/mrn", {"page": cint(page), "size": cint(size), "trptModeCd": "10", "mrn": mrn})
		return _paged(res, "impMnfsBlLst", page, size)
	from tanesw_integration import api as legacy

	code = legacy._our_facility_code()
	ours = legacy._our_bls(mrn, code)
	page, size = cint(page), cint(size) or 10
	return {
		"content": ours[page * size : (page + 1) * size],
		"facility_code": code,
		"page": {
			"number": page,
			"size": size,
			"totalElements": len(ours),
			"totalPages": (len(ours) + size - 1) // size if ours else 0,
		},
	}


@frappe.whitelist(methods=["POST"])
def mbl_info(mrn: Scalar, mbl_no: Scalar):
	"""CGME-0101-027Q. The portal keys a B/L as 'MRN^MBLNO'."""
	res = _get(f"{MNFS}/blInfo", {"key": f"{mrn.strip().upper()}^{mbl_no.strip()}"})
	return _one(res, "impMnfsBl") or {}


# Fields of the 026Q MRN form (form_seaImpMrnDtl); the portal posts all of them to excel-dwnl.
MRN_FORM_FIELDS = (
	"mrn",
	"carrCd",
	"carrNm",
	"prcssStatCd",
	"vygNo",
	"csgn",
	"imoNo",
	"vsslNm",
	"natCd",
	"cstmOfceCd",
	"dptrDt",
	"arvlXptdDt",
	"actlArvlDt",
	"trmnlCd",
	"trmnlOptrCd",
	"dptrPortCd",
	"dscgPortCd",
	"tpaUid",
	"inblYn",
	"sbmtDt",
	"trptModeCd",
	"blDstcCd",
)


@frappe.whitelist(methods=["POST"])
def manifest_excel(mrn: Scalar, header: JSONish | None = None):
	"""'Excel Download' on 026Q (Master B/L list): POST /imp-mnfs/excel-dwnl with the whole MRN form,
	exactly like the portal ({...impMrnDtl.getValues()}, trptModeCd 10 = sea). Returns the official workbook."""
	mrn = mrn.strip().upper()
	header = _parse(header) or {}
	if not header:
		header = mrn_detail(mrn) or {}
	body = {k: header.get(k) for k in MRN_FORM_FIELDS if header.get(k) not in (None, "")}
	# The portal blanks carrCd/shagCd before the list/excel calls (otherwise only that carrier's B/Ls come back).
	body.update({"mrn": mrn, "trptModeCd": header.get("trptModeCd") or "10", "carrCd": "", "shagCd": ""})
	data = _post_binary("/cgm/api/v1/cgme/mnfs/imp/imp-mnfs/excel-dwnl", body)
	stamp = frappe.utils.now_datetime().strftime("%Y%m%d%H%M%S")
	return {
		"filename": f"Sea Import MRN Detail_{mrn}[{stamp}].xlsx",
		"content": base64.b64encode(data).decode(),
	}


# =================================================================== ICD Transfer — lists


@frappe.whitelist(methods=["POST"])
def icd_expected_list(
	srch_arvl_dt_from: Scalar,
	srch_arvl_dt_to: Scalar,
	srch_cag_tp: Scalar = "C",
	srch_mrn: Scalar | None = None,
	srch_vssl_nm: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	"""CGME-0301-001Q."""
	res = _get(
		f"{ICD}/xptd",
		{
			"page": cint(page),
			"size": cint(size),
			"srchArvlDtFrom": srch_arvl_dt_from,
			"srchArvlDtTo": srch_arvl_dt_to,
			"srchCagTp": srch_cag_tp or "C",
			"srchMrn": (srch_mrn or "").strip().upper(),
			"srchVsslNm": srch_vssl_nm,
		},
	)
	return _paged(res, "icdTrsfXptdLstData", page, size)


@frappe.whitelist(methods=["POST"])
def icd_declaration_list(
	srch_dt_tp_from: Scalar,
	srch_dt_tp_to: Scalar,
	srch_dt_tp: Scalar = "rgsrDt",
	prcss_stat_cds: Scalar | None = None,
	srch_mrn: Scalar | None = None,
	srch_dptr_wrhs_cd: Scalar | None = None,
	srch_dclr_no: Scalar | None = None,
	srch_cntr_no: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	"""CGME-0301-002Q. Status filter is prcssStatCds (comma list) — it works."""
	res = _get(
		ICD,
		{
			"page": cint(page),
			"size": cint(size),
			"srchDtTpFrom": srch_dt_tp_from,
			"srchDtTpTo": srch_dt_tp_to,
			"prcssStatCds": _csv(prcss_stat_cds, DECLARATION_STATUSES),
			"srchDtTp": srch_dt_tp or "rgsrDt",
			"srchMrn": (srch_mrn or "").strip().upper(),
			"srchDptrWrhsCd": srch_dptr_wrhs_cd,
			"srchDclrNo": (srch_dclr_no or "").replace("-", "").strip().upper(),
			"srchCntrNo": (srch_cntr_no or "").strip().upper(),
		},
	)
	return _paged(res, "icdTrsfDclrLstData", page, size)


@frappe.whitelist(methods=["POST"])
def icd_usable_cargo(
	srch_arvl_dt_from: Scalar,
	srch_arvl_dt_to: Scalar,
	srch_cag_tp: Scalar = "C",
	srch_mrn: Scalar | None = None,
	srch_vssl_nm: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	"""CGME-0301-003Q popup behind 'New Declaration' (portal default: arrival today -1M ~ +1M, container).
	TANeSW returns only manifests with cargo still available to transfer to this ICD."""
	res = _get(
		f"{ICD}/trgt",
		{
			"page": cint(page),
			"size": cint(size),
			"srchArvlDtFrom": srch_arvl_dt_from,
			"srchArvlDtTo": srch_arvl_dt_to,
			"srchCagTp": srch_cag_tp or "C",
			"srchMrn": (srch_mrn or "").strip().upper(),
			"srchVsslNm": (srch_vssl_nm or "").strip().upper(),
		},
	)
	return _paged(res, "trsfIcdDclaTrgtList", page, size)


@frappe.whitelist(methods=["POST"])
def icd_declaration_delete_many(dclr_nos: Scalar):
	"""'Delete' on 002Q — only REGISTERED / RECEIVED ERROR rows never submitted."""
	tc.assert_write_operations_enabled()
	done = []
	for no in _rows(dclr_nos):
		tc._authed_delete(f"{ICD}/{no}")
		done.append(no)
	return {"deleted": done}


# =================================================================== ICD Transfer — 005S registration


@frappe.whitelist(methods=["POST"])
def icd_declaration(dclr_no: Scalar):
	return _one(_get(f"{ICD}/{dclr_no.replace('-', '').strip()}"), "trsfIcdDcla") or {}


@frappe.whitelist(methods=["POST"])
def icd_base_info(mrn: Scalar):
	"""Departure/destination warehouse and customs office for a new declaration."""
	return _one(_get(f"{ICD}/trgt/{mrn.strip().upper()}"), "trsfIcdDcla") or {}


def _declaration_payload(header, containers, vehicles):
	header = _parse(header) or {}
	payload = {k: v for k, v in header.items() if not k.startswith("_")}

	# screen-only keys (e.g. _excel_row from Excel Upload) never go to TANeSW
	def clean(rows):
		return [
			{k: v for k, v in r.items() if not str(k).startswith("_")}
			for r in _rows(rows)
			if isinstance(r, dict)
		]

	payload["trsfIcdCntrRList"] = clean(containers)
	payload["trsfIcdVhclRList"] = clean(vehicles)
	for field, label in (
		("mrn", "MRN"),
		("trsfStrtDt", "Transfer Period"),
		("trsfEndDt", "Transfer Period"),
		("dptrWrhsCd", "Place of Departure"),
	):
		if not payload.get(field):
			frappe.throw(_("{0} is required").format(label))
	return payload


def _validate_vehicles(vehicles, require=True):
	"""Same checks as the portal's gridVldtyChk."""
	if require and not vehicles:
		frappe.throw(_("Add at least one vehicle"))
	seen = set()
	for i, v in enumerate(vehicles, 1):
		key = (v.get("drvrLcneNo"), v.get("vhclNo"))
		if key in seen:
			frappe.throw(_("Licence No. {0} is duplicated").format(v.get("drvrLcneNo")))
		seen.add(key)
		for f, label in (("drvrNm", "Driver Name"), ("drvrLcneNo", "Licence No.")):
			if not v.get(f):
				frappe.throw(_("{0} is required on vehicle row {1}").format(label, i))
		if v.get("drivTpCd") not in (None, "", "OWN", "VEHC"):
			frappe.throw(
				_("Driving Type on vehicle row {0} must be OWN or VEHC (found {1})").format(
					i, frappe.utils.escape_html(v.get("drivTpCd"))
				)
			)
		if v.get("drivTpCd") != "OWN":
			for f, label in (("drivTpCd", "Driving Type"), ("vhclNo", "Vehicle No."), ("c45No", "C45 No.")):
				if not v.get(f):
					frappe.throw(_("{0} is required on vehicle row {1}").format(label, i))


@frappe.whitelist(methods=["POST"])
def icd_declaration_save(header: JSONish, containers: JSONish | None = None, vehicles: JSONish | None = None):
	payload = _declaration_payload(header, containers, vehicles)
	_assert_editable(payload.get("prcssStatCd"), _("This declaration"))
	if payload.get("dclrNo"):
		_validate_vehicles(payload["trsfIcdVhclRList"], require=False)
	res = _write_result(_post(ICD, payload), "cgmeTrsfIcdMDto")
	_persist_transfer_allocation(payload, res)
	return res


@frappe.whitelist(methods=["POST"])
def icd_declaration_submit(
	header: JSONish, containers: JSONish | None = None, vehicles: JSONish | None = None
):
	payload = _declaration_payload(header, containers, vehicles)
	_assert_editable(payload.get("prcssStatCd"), _("This declaration"))
	# portal gridVldtyChk order: vehicles first (msg.cgm.00592), then containers (msg.cgm.00279).
	# Submit works on a new declaration too: sbmt registers and submits in one call and returns the new dclrNo.
	_validate_vehicles(payload["trsfIcdVhclRList"])
	if not payload["trsfIcdCntrRList"]:
		frappe.throw(_("Add at least one container"))
	res = _write_result(_post(f"{ICD}/sbmt", payload), "cgmeTrsfIcdMDto")
	_persist_transfer_allocation(payload, res)
	return res


@frappe.whitelist(methods=["POST"])
def icd_declaration_delete(dclr_no: Scalar, prcss_stat_cd: Scalar | None = None):
	_assert_editable(prcss_stat_cd, _("This declaration"))
	return tc._authed_delete(f"{ICD}/dtl/{dclr_no.replace('-', '').strip()}")


def _post_binary(path, body):
	"""POST that returns a file (Excel/PDF). Retries once on 401; surfaces JSON error bodies."""
	for attempt in range(2):
		token = tc.authenticate()
		session, settings = tc._get_session()
		session.headers["Authorization"] = f"Bearer {token}"
		r = session.post(
			f"{settings.base_url.rstrip('/')}{path}",
			json=body,
			timeout=max(cint(settings.request_timeout) or 30, 90),
		)
		if r.status_code == 401 and attempt == 0:
			tc._invalidate_cached_token()
			continue
		if r.status_code >= 400:
			tc._handle_tanesw_error(r, path)
		ctype = (r.headers.get("Content-Type") or "").lower()
		if "json" in ctype or (r.content[:1] in (b"{", b"[")):
			try:
				j = r.json()
			except Exception:
				j = {}
			msg = j.get("errorMessage") or j.get("message") or _("TANeSW returned no document.")
			frappe.throw(frappe.utils.escape_html(str(msg)), title=_("TANeSW"))
		if not r.content:
			frappe.throw(_("TANeSW returned an empty document."), title=_("TANeSW"))
		return r.content


@frappe.whitelist(methods=["POST"])
def icd_declaration_excel(header: JSONish):
	"""'Download' on 005S — POST /excelDown with the header form."""
	header = _parse(header) or {}
	data = _post_binary(f"{ICD}/excelDown", header)
	name = f"{header.get('dstnWrhsCd') or ''}_{header.get('dclrNo') or 'declaration'}.xlsx"
	return {"filename": name, "content": base64.b64encode(data).decode()}


# =================================================================== Reports (portal "[CGMPDF]" viewer)
RPRT = "/cgm/api/v1/cgme/rprt/cgme-rprt"
# Report types this app prints, with the parameters the portal sends for each.
REPORTS = {
	# ICD Transfer 005S "Print MovementSheet" (NcsIcdMovementSheet).
	"RP-CGME-0301-005S01": ("icd_movement_sheet", ("dclrNo",)),
	# Sea import manifest by MRN (seaImportManifestMrn.jrxml) — the portal shows this on the
	# shipping agent's MRN screen, not on the warehouse 026Q; access for a warehouse login is unverified.
	"RP-CGME-0101-002S01": ("manifest", ("mrn",)),
}


def _print_report(params, filename):
	rtype = params.get("rprtTpCd")
	if rtype not in REPORTS:
		frappe.throw(_("Unsupported report type {0}").format(rtype))
	for f in REPORTS[rtype][1]:
		if not params.get(f):
			frappe.throw(_("{0} is required to print this report").format(f))
	data = _post_binary(RPRT, {k: v for k, v in params.items() if v not in (None, "")})
	return {"filename": filename, "content": base64.b64encode(data).decode(), "mime": "application/pdf"}


@frappe.whitelist(methods=["POST"])
def icd_movement_sheet(dclr_no: Scalar, crn: Scalar | None = None, is_bulk: Scalar | None = None):
	"""005S 'Print MovementSheet': {cagDclrTpCd CDD, rprtTpCd RP-CGME-0301-005S01, dclrNo,
	containerNo: isBulk, crn, mrn: crn} — exactly what the portal posts."""
	dclr_no = (dclr_no or "").strip()
	if not dclr_no:
		frappe.throw(_("Save the declaration before printing the movement sheet."))
	if not crn:  # printed from the list: take CRN / isBulk from the declaration, as 005S does
		d = icd_declaration(dclr_no)
		if d.get("prcssStatCd") and d["prcssStatCd"] != "D06":
			frappe.throw(_("The movement sheet is available once the declaration is APPROVED."))
		crn, is_bulk = d.get("crn"), d.get("isBulk")
	params = {
		"cagDclrTpCd": "CDD",
		"rprtTpCd": "RP-CGME-0301-005S01",
		"dclrNo": dclr_no,
		"containerNo": is_bulk,
		"crn": crn,
		"mrn": crn,
	}
	return _print_report(params, f"MovementSheet_{dclr_no}.pdf")


@frappe.whitelist(methods=["POST"])
def manifest_report(mrn: Scalar):
	"""Cargo Manifest Report Inward of Vessel (PDF) for an MRN — portal params {cagDclrTpCd ISM, rprtTpCd, mrn}."""
	mrn = (mrn or "").strip().upper()
	params = {"cagDclrTpCd": "ISM", "rprtTpCd": "RP-CGME-0101-002S01", "mrn": mrn}
	return _print_report(params, f"Manifest_{mrn}.pdf")


@frappe.whitelist(methods=["POST"])
def icd_target_containers(
	mrn: Scalar,
	crn: Scalar | None = None,
	dclr_no: Scalar | None = None,
	cag_dclr_tp_cd: Scalar = "CDD",
	is_bulk: Scalar = "N",
	cntr_no: Scalar | None = None,
	srch_bl_no: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 50,
):
	"""CGME-0301-006Q container popup."""
	res = _get(
		f"{ICD}/trgt/cntr",
		{
			"page": cint(page),
			"size": cint(size),
			"mrn": mrn,
			"crn": crn,
			"dclrNo": dclr_no,
			"cagDclrTpCd": cag_dclr_tp_cd or "CDD",
			"isBulk": is_bulk or "N",
			"cntrNo": (cntr_no or "").strip().upper(),
			"srchBlNo": (srch_bl_no or "").strip().upper(),
		},
	)
	return _paged(res, "cntrLstData", page, size)


@frappe.whitelist(methods=["POST"])
def icd_add_containers(
	mrn: Scalar,
	dclr_no: Scalar | None = None,
	rows: JSONish | None = None,
	crn: Scalar | None = None,
	cag_dclr_tp_cd: Scalar = "CDD",
	is_bulk: Scalar = "N",
):
	"""006Q popup 'Save': checkCntr first, then trgt/save — exactly the portal sequence, on new and saved
	declarations alike (the portal sends dclrNo "" on a new one).

	As the portal exchanges them:
	  checkCntr -> {"result":{"content":[]}}  (empty = containers OK; otherwise a list of messages)
	  trgt/save -> {"cgmeTrsfIcdMDto":{}}     (nothing comes back)
	The portal then only adds the ticked rows to the on-screen grid; they reach TANeSW in the
	trsfIcdCntrRList of the declaration's Save (POST /dcla) or Submit (POST /dcla/sbmt).
	So the caller must keep the rows on screen and send them with Save/Submit — never reload and expect
	trgt/save to have stored them."""
	rows = _rows(rows)
	if not rows:
		frappe.throw(_("Select at least one container"))
	body = {
		"mrn": mrn,
		"crn": crn,
		"dclrNo": dclr_no or "",
		"cagDclrTpCd": cag_dclr_tp_cd or "CDD",
		"isBulk": is_bulk or "N",
		"trsfIcdCntrRList": rows,
	}
	check = _post(f"{ICD}/checkCntr", body)
	msgs = ((check or {}).get("result") or {}).get("content") if isinstance(check, dict) else None
	if msgs:
		frappe.throw(
			"<br>".join(
				frappe.utils.escape_html(
					m
					if isinstance(m, str)
					else (m.get("msg") or m.get("errMsg") or m.get("message") or frappe.as_json(m))
				)
				for m in msgs
			),
			title=_("TANeSW container check"),
		)
	# trgt/save returns nothing we use (captured: {"cgmeTrsfIcdMDto":{}}) and the containers are filed by the
	# declaration's Save / Submit anyway. TANeSW sometimes answers it with an HTML 500 — checkCntr has already passed, so keep the picked rows and carry on instead of blocking.
	saved = True
	try:
		_post(f"{ICD}/trgt/save", body)
	except Exception:
		saved = False
		frappe.clear_messages()
		frappe.log_error(
			title="TANeSW trgt/save failed (containers kept on screen)", message=frappe.get_traceback()
		)
	return {"rows": rows, "trgt_saved": saved}


# 005S Vehicle Information tab — portal: HZ.downloadTemplate("1bc55e46-...") = ICDTransferDeclarationSample.xlsx
ICD_VHCL_TEMPLATE_UUID = "1bc55e46-3293-081f-e063-020011acda75"
# Portal importExcel({headers: 1, sheet: 0, bindings: {A..G}}) — row 1 is the header, data from row 2.
ICD_VHCL_EXCEL_COLS = ("drvrNm", "drvrLcneNo", "drivTpCd", "c45No", "vhclNo", "trlrNo", "semiTrlrNo")


@frappe.whitelist(methods=["POST"])
def icd_vehicle_template():
	"""'Template Download' on the 005S Vehicle Information tab."""
	return download_template(ICD_VHCL_TEMPLATE_UUID)


def _cell_text(v):
	"""Excel cell -> clean upper-case text. Licence numbers typed as numbers come back as 4000000000.0."""
	if v is None:
		return ""
	if isinstance(v, float) and v.is_integer():
		v = int(v)
	return str(v).strip().upper()


@frappe.whitelist(methods=["POST"])
def icd_vehicle_excel_parse(filename: Scalar, content: Scalar):
	"""'Excel Upload' on the 005S Vehicle Information tab.

	The portal reads the workbook in the browser and appends the rows to the vehicle grid — nothing is sent
	to TANeSW until Save/Submit. Same here: parse sheet 1 (row 1 = header, columns A-G as in the template)
	and return the rows plus row-level warnings (the portal's own checks run again at Save/Submit)."""
	from tanesw_integration.credentials import require_tanesw_user

	require_tanesw_user()
	import csv
	import io

	raw = base64.b64decode(content or "")
	if not raw:
		frappe.throw(_("The file is empty."))
	name = (filename or "").lower()
	table = []
	if name.endswith(".csv"):
		text = raw.decode("utf-8-sig", errors="replace")
		table = [list(r) for r in csv.reader(io.StringIO(text))]
	else:
		if name.endswith(".xls"):
			frappe.throw(
				_(
					"Save the file as .xlsx (Excel Workbook) and upload it again — the old .xls format is not supported."
				)
			)
		from openpyxl import load_workbook

		try:
			wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
		except Exception:
			frappe.throw(
				_("Could not read {0} as an Excel workbook (.xlsx).").format(
					frappe.utils.escape_html(filename or "")
				)
			)
		ws = wb.worksheets[0]
		table = [list(r) for r in ws.iter_rows(min_row=1, max_col=len(ICD_VHCL_EXCEL_COLS), values_only=True)]
		wb.close()

	rows, warnings = [], []
	for excel_row, values in enumerate(table[1:], start=2):  # skip header row
		values = (list(values) + [None] * len(ICD_VHCL_EXCEL_COLS))[: len(ICD_VHCL_EXCEL_COLS)]
		v = {k: _cell_text(values[i]) for i, k in enumerate(ICD_VHCL_EXCEL_COLS)}
		if not any(v.values()):
			continue
		if v["drivTpCd"] == "OWN":
			# portal drivTpCdChange: OWN -> vehicle "OWN", no C45 / trailer / semi-trailer
			v.update({"vhclNo": "OWN", "c45No": "", "trlrNo": "", "semiTrlrNo": ""})
		problems = []
		if not v["drvrNm"]:
			problems.append(_("Driver Name"))
		if not v["drvrLcneNo"]:
			problems.append(_("Licence No."))
		if v["drivTpCd"] not in ("OWN", "VEHC"):
			problems.append(_("Driving Type (OWN or VEHC)"))
		elif v["drivTpCd"] == "VEHC":
			if not v["vhclNo"]:
				problems.append(_("Vehicle No."))
			if not v["c45No"]:
				problems.append(_("C45 No."))
		if problems:
			warnings.append(_("Row {0}: missing {1}").format(excel_row, ", ".join(problems)))
		rows.append({**v, "delYn": "N", "vhclSrno": 0, "_excel_row": excel_row})
	if not rows:
		frappe.throw(
			_(
				"No vehicle rows found. Fill the template from row 2: Driver Name, Driver License No, "
				"Driving Type, C45_No, Vehicle No, Trailer No, Semi-Trailer No."
			)
		)
	return {"rows": rows, "warnings": warnings}


# --- vehicle popup lookups (CGME-0305-10xQ) ---


@frappe.whitelist(methods=["POST"])
def trsf_driver_licence(lcne_no: Scalar):
	return _one(_get(f"{TRSF_COMN}/drvr/lcne/{lcne_no.strip()}"), "drvrLcneInfo") or {}


@frappe.whitelist(methods=["POST"])
def trsf_transporters(
	c45_no: Scalar | None = None, co_nm: Scalar | None = None, page: Scalar = 0, size: Scalar = 10
):
	res = _get(f"{TRSF_COMN}/trpr", {"page": cint(page), "size": cint(size), "c45No": c45_no, "coNm": co_nm})
	return _paged(res, "trsfComnTrprList", page, size)


@frappe.whitelist(methods=["POST"])
def trsf_vehicles(
	kind: Scalar = "vhcl",
	c45_no: Scalar | None = None,
	vhcl_no: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	"""kind: vhcl | trlr | semi-trlr. normalTrsfYn=Y as the portal's ICD popup sends."""
	path, key = {
		"vhcl": ("trpr/vhcl", "trsfComnTrprVhclList"),
		"trlr": ("trpr/trlr", "trsfComnTrprTrlrList"),
		"semi-trlr": ("trpr/semi-trlr", "trsfComnTrprSemiTrlrList"),
	}.get(kind, ("trpr/vhcl", "trsfComnTrprVhclList"))
	res = _get(
		f"{TRSF_COMN}/{path}",
		{
			"page": cint(page),
			"size": cint(size),
			"c45No": c45_no,
			"vhclNo": (vhcl_no or "").strip().upper(),
			"normalTrsfYn": "Y",
		},
	)
	return _paged(res, key, page, size)


# =================================================================== ICD Transfer — amendment (011Q/012S)


@frappe.whitelist(methods=["POST"])
def icd_amendment_list(
	rgsr_dt_from: Scalar,
	rgsr_dt_to: Scalar,
	srch_dt_tp: Scalar = "rgsrDt",
	srch_no_tp: Scalar = "dclrNo",
	srch_no: Scalar | None = None,
	prcss_stat_cds: Scalar | None = None,
	mrn: Scalar | None = None,
	dptr_wrhs_cd: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	params = {
		"page": cint(page),
		"size": cint(size),
		"rgsrDtFrom": rgsr_dt_from,
		"rgsrDtTo": rgsr_dt_to,
		"prcssStatCds": _csv(prcss_stat_cds, AMD_CNCL_STATUSES),
		"srchDtTp": srch_dt_tp or "rgsrDt",
		"srchNoTp": srch_no_tp or "dclrNo",
		"mrn": (mrn or "").strip().upper(),
		"dptrWrhsCd": dptr_wrhs_cd,
	}
	if srch_no:
		params[srch_no_tp or "dclrNo"] = srch_no.replace("-", "").strip().upper()
	return _paged(_get(f"{ICD_AMD}/", params), "trsfIcdAmdDclaList", page, size)


@frappe.whitelist(methods=["POST"])
def icd_amendment_targets(
	rgsr_dt_from: Scalar,
	rgsr_dt_to: Scalar,
	dclr_tp_cd: Scalar = "CDA",
	dclr_no: Scalar | None = None,
	mrn: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	"""CGME-0301-013Q popup: approved declarations that can be amended (CDA) or cancelled (CDC)."""
	res = _get(
		f"{ICD_AMD}/trgt",
		{
			"page": cint(page),
			"size": cint(size),
			"rgsrDtFrom": rgsr_dt_from,
			"rgsrDtTo": rgsr_dt_to,
			"dclrTpCd": dclr_tp_cd,
			"dclrNo": (dclr_no or "").replace("-", "").strip().upper(),
			"mrn": (mrn or "").strip().upper(),
		},
	)
	return _paged(res, "trsfIcdAmdDclaTrgtList", page, size)


@frappe.whitelist(methods=["POST"])
def icd_amendment_init(dclr_no: Scalar):
	"""Original declaration loaded into a new amendment."""
	return _one(_get(f"{ICD_AMD}/amd/init/{dclr_no.replace('-', '').strip()}"), "trsfIcdAmdInit") or {}


@frappe.whitelist(methods=["POST"])
def icd_amendment(amd_dclr_no: Scalar):
	return _one(_get(f"{ICD_AMD}/{amd_dclr_no.replace('-', '').strip()}"), "trsfIcdAmdDcla") or {}


@frappe.whitelist(methods=["POST"])
def icd_amendment_save(
	header: JSONish,
	items: JSONish | None = None,
	containers: JSONish | None = None,
	vehicles: JSONish | None = None,
	bf_containers: Scalar | None = None,
	bf_vehicles: Scalar | None = None,
	action: Scalar = "save",
):
	"""Save (amd/save) or Submit (amd/sbmt). Rows carry dtlAmdTpCd O/A/C/D and the
	body has the same shape as the portal's getSaveData()."""
	header = _parse(header) or {}
	_assert_editable(header.get("prcssStatCd"), _("This amendment"))
	if not (header.get("amdRsn") or "").strip():
		frappe.throw(_("Amendment Reason is required"))
	if not header.get("reffDclrNo"):
		frappe.throw(_("Select the ICD declaration to amend"))
	cntr, vhcl = _rows(containers), _rows(vehicles)
	_validate_vehicles([v for v in vhcl if v.get("dtlAmdTpCd") != "D"], require=action == "sbmt")
	values = {k: v for k, v in header.items() if not k.startswith("_")}
	body = {
		**values,
		"cgmeDclrAmdMDto": {
			**values,
			"dclrAmdItmRList": _rows(items),
			"amdTpCd": "ZZ",
			"cagDclrTpCd": "CDA",
			"dclrAmdItmVhclRList": vhcl,
			"orgDclrAmdItmVhclRList": vhcl,
			"dclrAmdItmCntrRList": cntr,
			"orgDclrAmdItmCntrRList": cntr,
		},
		"bfVhclRList": _rows(bf_vehicles),
		"afVhclRList": vhcl,
		"bfCntrRList": _rows(bf_containers),
		"afCntrRList": cntr,
	}
	path = f"{ICD_AMD}/sbmt" if action == "sbmt" else f"{ICD_AMD}/save"
	return _write_result(_post(path, body), "trsfIcdAmdDcla")


@frappe.whitelist(methods=["POST"])
def icd_amendment_delete(header: JSONish):
	"""Portal: check status via amd/dclr/{no}, then PUT /dclr/amd/dclr-del."""
	header = _parse(header) or {}
	info = _one(_get(f"{ICD_AMD}/dclr/{header.get('amdDclrNo')}"), "trsfIcdAmdDclrInfo") or {}
	st = info.get("prcssStatCd")
	if st == "D06":
		frappe.throw(_("An approved amendment cannot be deleted"))
	if st in ("A04", "D01"):
		frappe.throw(_("A submitted amendment cannot be deleted"))
	tc.assert_write_operations_enabled()
	session_put = _put_json(f"{DCLR_AMD}/dclr-del", {"dclrAmdList": [header]})
	return session_put


def _put_json(path, body):
	tc.assert_write_operations_enabled()
	for attempt in range(2):
		token = tc.authenticate()
		session, settings = tc._get_session()
		session.headers["Authorization"] = f"Bearer {token}"
		r = session.put(
			f"{settings.base_url.rstrip('/')}{path}", json=body, timeout=cint(settings.request_timeout) or 30
		)
		if r.status_code == 401 and attempt == 0:
			tc._invalidate_cached_token()
			continue
		if r.status_code >= 400:
			tc._handle_tanesw_error(r, path)
		try:
			return r.json()
		except Exception:
			return {"status": "ok"}


# =================================================================== ICD Transfer — cancellation (021Q/022S)


@frappe.whitelist(methods=["POST"])
def icd_cancellation_list(
	rgsr_dt_from: Scalar,
	rgsr_dt_to: Scalar,
	srch_dt_tp: Scalar = "rgsrDt",
	srch_no_tp: Scalar = "dclrNo",
	srch_no: Scalar | None = None,
	prcss_stat_cds: Scalar | None = None,
	mrn: Scalar | None = None,
	dptr_wrhs_cd: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	params = {
		"page": cint(page),
		"size": cint(size),
		"rgsrDtFrom": rgsr_dt_from,
		"rgsrDtTo": rgsr_dt_to,
		"prcssStatCds": _csv(prcss_stat_cds, AMD_CNCL_STATUSES),
		"srchDtTp": srch_dt_tp or "rgsrDt",
		"srchNoTp": srch_no_tp or "dclrNo",
		"mrn": (mrn or "").strip().upper(),
		"dptrWrhsCd": dptr_wrhs_cd,
	}
	if srch_no:
		params[srch_no_tp or "dclrNo"] = srch_no.replace("-", "").strip().upper()
	return _paged(_get(ICD_CNCL, params), "trsfIcdCnclDclaList", page, size)


@frappe.whitelist(methods=["POST"])
def icd_cancellation(cncl_dclr_no: Scalar):
	return _one(_get(f"{ICD_CNCL}/{cncl_dclr_no.replace('-', '').strip()}"), "trsfIcdCnclDcla") or {}


@frappe.whitelist(methods=["POST"])
def icd_cancellation_reference(dclr_no: Scalar):
	"""Original ICD declaration (header, containers, vehicles) shown on 022S."""
	return _one(_get(f"{ICD_CNCL}/dclr/{dclr_no.replace('-', '').strip()}"), "trsfIcdCnclDcla") or {}


@frappe.whitelist(methods=["POST"])
def icd_cancellation_save(header: JSONish, action: Scalar = "save"):
	header = _parse(header) or {}
	_assert_editable(header.get("prcssStatCd"), _("This cancellation"))
	if not (header.get("cnclCn") or "").strip():
		frappe.throw(_("Cancellation Comment is required"))
	if not header.get("reffDclrNo"):
		frappe.throw(_("Select the ICD declaration to cancel"))
	values = {k: v for k, v in header.items() if not k.startswith("_")}
	if action == "sbmt":
		return _write_result(_post(f"{ICD_CNCL}/sbmt", {**values, "cgmeDclrCnclMDto": values}), "dclrCncl")
	ctx = _user_info()
	# Portal stamps the declarant from the logged-in user before saving
	values.update(
		{
			k: v
			for k, v in {
				"dcltId": ctx.get("usrId"),
				"dcltNm": ctx.get("usrNm"),
				"dcltTin": ctx.get("tin"),
				"prcssId": ctx.get("usrId"),
				"cstmOfceCd": values.get("cstmOfceCd") or ctx.get("cstmCd"),
			}.items()
			if v
		}
	)
	return _write_result(_post(ICD_CNCL, values), "dclrCncl")


@frappe.whitelist(methods=["POST"])
def icd_cancellation_delete(cncl_dclr_no: Scalar):
	cur = icd_cancellation(cncl_dclr_no)
	st = cur.get("prcssStatCd")
	if st == "D06":
		frappe.throw(_("An approved cancellation cannot be deleted"))
	if st in ("A04", "D01"):
		frappe.throw(_("A submitted cancellation cannot be deleted"))
	return tc._authed_delete(f"{ICD_CNCL}/{cncl_dclr_no}")


# =================================================================== common: processing status history
# The status cell on every Cargo list opens the portal's dclrDtlPpup:
# processing history, return reason / errors, and (once approved) the
# confirmation notice document.
DCLR_STTS = "/ptl/api/v1/comn/comn/dclr"


@frappe.whitelist(methods=["POST"])
def declaration_status(doc_sbmt_no: Scalar, dcla_doc_cd: Scalar):
	"""Processing status history for one declaration/report."""
	hist = _get(
		f"{DCLR_STTS}/elec-dclr-prcss-stts-hist", {"docSbmtNo": doc_sbmt_no, "dclaDocCd": dcla_doc_cd}
	)
	rows = _content(hist, "elecDclrPrcssSttsHistList") or []
	out = {"history": rows, "detail": None, "errors": [], "notice_url": None}
	if not rows:
		return out
	top = rows[0]
	if top.get("ntcStat") == "E" and top.get("msgId"):
		err = _get(f"{DCLR_STTS}/elec-dclr-prcss-stts-err", {"page": 0, "size": 50, "msgId": top["msgId"]})
		out["errors"] = _content(err, "elecDclrPrcssErrList") or []
	elif top.get("dclrNtcUrlAddr") and top.get("docMakeUrlAddr"):
		# approval / confirmation notice rendered by TANeSW itself
		out["notice_url"] = (
			"https://tanesw.tra.go.tz" + str(top.get("docMakeUrlAddr")) + str(top.get("dclrReffId") or "")
		)
	elif top.get("dclrPrcssSttsUuid"):
		dtl = _get(f"{DCLR_STTS}/elec-dclr-prcss-stts-dtl/{top['dclrPrcssSttsUuid']}/{top.get('prcssSrno')}")
		out["detail"] = _content(dtl, "elecDclrPrcssSttsInfo")
	return out


@frappe.whitelist(methods=["POST"])
def declaration_status_detail(uuid: Scalar, srno: Scalar):
	return (
		_content(_get(f"{DCLR_STTS}/elec-dclr-prcss-stts-dtl/{uuid}/{srno}"), "elecDclrPrcssSttsInfo") or {}
	)


@frappe.whitelist(methods=["POST"])
def procedure_codes(comn_cd: Scalar):
	"""Procedure status codes (area=cgmePrcdCd), e.g. SRR stripping report statuses."""
	require_tanesw_user()  # a cached answer is returned without calling TANeSW, so check the role here
	key = f"tanesw:cgm:prcd:{comn_cd}"
	cached = frappe.cache.get_value(key)
	if cached:
		return cached
	from tanesw_integration.joint_inspection import _find_list

	res = _get("/cgm/api/v1/cgme/comn/cd", {"area": "cgmePrcdCd", "comnCd": comn_cd, "size": 999999})
	# Portal reads these rows as {comnCdVal, comnCdLbl} (HZ.getCodeValue/Label, area cgmePrcdCd).
	rows = _find_list(res, "comnCdVal") or _find_list(res, "cdVldVal") or _find_list(res, "cd") or []
	mapping = {}
	for r in rows:
		k = r.get("comnCdVal") or r.get("cdVldVal") or r.get("cd")
		if k:
			mapping[k] = r.get("comnCdLbl") or r.get("cdVldValNm") or r.get("cdNm") or k
	if mapping:
		frappe.cache.set_value(key, mapping, expires_in_sec=6 * 3600)
	return mapping


def _stamp_declarant(values):
	"""Portal Z0.setFormDcltInfo: declarant fields come from the logged-in user."""
	ctx = _user_info()
	for k, v in (
		("dcltId", ctx.get("usrId")),
		("dcltNm", ctx.get("usrNm")),
		("dcltTin", ctx.get("tin")),
		("dcltTelno", ctx.get("telNo")),
		("prcssId", ctx.get("usrId")),
	):
		if v and not values.get(k):
			values[k] = v
	return values


# =================================================================== Simple Transfer (CGME-0302-0xx)
SIMPL = "/cgm/api/v1/cgme/trsf/simpl/gnrl/dcla"
SIMPL_ERR = {
	"crnChk": "CRN {crn} is already declared on another simple transfer",
	"cntrNoChk": "Container {cntrNo} is already declared on another simple transfer",
	"dstnWrhsChk": "Destination warehouse {dstnWrhsCd} is not allowed",
	"dstnWrhsCoTpChk": "Destination warehouse {dstnWrhsCd} is not allowed for this company type",
	"crnStckChk": "CRN {crn} has no stock at {dptrWrhsCd}",
	"cntrNoStckChk": "Container {cntrNo} has no stock at {dptrWrhsCd}",
	"vhclCntChk": "Vehicle information is required",
	"cntrCntChk": "Container information is required for CRN {crn}",
}


def _simpl_result(res):
	c = _content(res, "cgmeTrsfSimplMDto") or {}
	if c.get("errYn") == "Y":
		msg = SIMPL_ERR.get(c.get("errTp"), "TANeSW rejected the declaration ({errTp})")
		frappe.throw(
			_(msg).format(
				**{k: c.get(k) or "" for k in ("crn", "cntrNo", "dstnWrhsCd", "dptrWrhsCd", "errTp")}
			)
		)
	return _write_result(res, "cgmeTrsfSimplMDto")


# Portal status defaults (Status checkboxes) for the Simple Transfer lists.
SIMPL_STATUSES = ["A01", "A04", "A05", "D01", "D06", "D08", "D09", "G07"]
SIMPL_AMD_CNCL_STATUSES = ["A01", "A04", "A05", "D01", "D06", "D08", "D09", "D15"]


@frappe.whitelist(methods=["POST"])
def simpl_list(
	from_rgsr_dt: Scalar,
	to_rgsr_dt: Scalar,
	srch_no_tp: Scalar = "dclrNo",
	srch_no: Scalar | None = None,
	srch_trsf_tp_cd: Scalar | None = None,
	prcss_stat_cds: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	params = {
		"page": cint(page),
		"size": cint(size),
		"fromRgsrDt": from_rgsr_dt,
		"toRgsrDt": to_rgsr_dt,
		"srchNoTp": srch_no_tp or "dclrNo",
		"srchTrsfTpCd": srch_trsf_tp_cd,
		"prcssStatCds": _csv(prcss_stat_cds, SIMPL_STATUSES),
	}
	if srch_no:
		params["srchNo"] = srch_no.replace("-", "").strip().upper()
		params[
			{"dclrNo": "srchDclrNo", "crn": "srchCrn", "cntrNo": "srchCntrNo"}.get(srch_no_tp, "srchDclrNo")
		] = params["srchNo"]
	return _paged(_get(SIMPL, params), "trsfSimplList", page, size)


@frappe.whitelist(methods=["POST"])
def simpl_cargo_refs(
	srch_cag_tp: Scalar = "import",
	srch_bl_no: Scalar | None = None,
	srch_crn_reff_no: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	"""Cargo reference popup behind 'New' (import B/L/CRN or export TANSAD)."""
	res = _get(
		f"{SIMPL}/cagref",
		{
			"page": cint(page),
			"size": cint(size),
			"srchCagTp": srch_cag_tp,
			"srchBlNo": (srch_bl_no or "").strip().upper(),
			"srchCrnReffNo": _crn_search(srch_crn_reff_no),
		},
	)
	return _paged(res, "trsfSimplCagrefTrgtList", page, size)


@frappe.whitelist(methods=["POST"])
def simpl_init(
	init_cag_tp: Scalar, init_no: Scalar, reff_dclr_no: Scalar | None = None, mrn: Scalar | None = None
):
	return (
		_one(
			_get(
				f"{SIMPL}/init",
				{"initCagTp": init_cag_tp, "initNo": init_no, "reffDclrNo": reff_dclr_no, "mrn": mrn},
			),
			"trsfSimplInit",
		)
		or {}
	)


@frappe.whitelist(methods=["POST"])
def simpl_declaration(dclr_no: Scalar):
	return _one(_get(f"{SIMPL}/{dclr_no.replace('-', '').strip()}"), "trsfSimpl") or {}


@frappe.whitelist(methods=["POST"])
def simpl_containers(crn: Scalar, dptr_wrhs_cd: Scalar | None = None, page: Scalar = 0, size: Scalar = 50):
	res = _get(
		f"{SIMPL}/cntr", {"page": cint(page), "size": cint(size), "crn": crn, "dptrWrhsCd": dptr_wrhs_cd}
	)
	return _paged(res, "trsfSimplCntrTrgtList", page, size)


@frappe.whitelist(methods=["POST"])
def simpl_save(
	header: JSONish,
	containers: JSONish | None = None,
	vehicles: JSONish | None = None,
	action: Scalar = "save",
):
	header = _parse(header) or {}
	_assert_editable(header.get("prcssStatCd"), _("This declaration"))
	for f, label in (
		("trsfStrtDt", "Transfer Period"),
		("dptrWrhsCd", "Place of Departure"),
		("dstnWrhsCd", "Place of Destination"),
		("trsfTpCd", "Transfer Type"),
		("cstmOfceCd", "Customs Office"),
	):
		if not header.get(f):
			frappe.throw(_("{0} is required").format(label))
	vhcl = _rows(vehicles)
	_validate_vehicles(vhcl, require=action == "sbmt")
	values = {k: v for k, v in header.items() if not k.startswith("_")}
	if action == "sbmt":
		_stamp_declarant(values)
	body = {**values, "trsfSimplVhclRList": vhcl, "trsfSimplCntrRList": _rows(containers)}
	return _simpl_result(_post(f"{SIMPL}/sbmt" if action == "sbmt" else SIMPL, body))


@frappe.whitelist(methods=["POST"])
def simpl_delete(dclr_no: Scalar, prcss_stat_cd: Scalar | None = None):
	_assert_editable(prcss_stat_cd, _("This declaration"))
	return tc._authed_delete(f"{SIMPL}/{dclr_no}")


@frappe.whitelist(methods=["POST"])
def simpl_handover_check(dclr_no: Scalar):
	"""Which HandOver report belongs to an approved simple transfer."""
	res = _get(f"{SIMPL}/hndv-chk/{dclr_no}")
	return ((res or {}).get("result") or {}).get("content") or {}


@frappe.whitelist(methods=["POST"])
def simpl_amd_list(
	from_rgsr_dt: Scalar,
	to_rgsr_dt: Scalar,
	srch_no_tp: Scalar = "dclrNo",
	srch_no: Scalar | None = None,
	prcss_stat_cds: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	params = {
		"page": cint(page),
		"size": cint(size),
		"fromRgsrDt": from_rgsr_dt,
		"toRgsrDt": to_rgsr_dt,
		"srchNoTp": srch_no_tp,
		"prcssStatCds": _csv(prcss_stat_cds, SIMPL_AMD_CNCL_STATUSES),
	}
	if srch_no:
		params["srchNo"] = srch_no.replace("-", "").strip().upper()
	return _paged(_get(f"{SIMPL}/amd", params), "trsfSimplAmdList", page, size)


@frappe.whitelist(methods=["POST"])
def simpl_amd_cncl_targets(
	srch_rgsr_dt_from: Scalar,
	srch_rgsr_dt_to: Scalar,
	cag_dclr_tp_cd: Scalar = "STA",
	srch_no_tp: Scalar = "dclrNo",
	srch_no: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	params = {
		"page": cint(page),
		"size": cint(size),
		"srchRgsrDtFrom": srch_rgsr_dt_from,
		"srchRgsrDtTo": srch_rgsr_dt_to,
		"cagDclrTpCd": cag_dclr_tp_cd,
		"srchNoTp": srch_no_tp,
	}
	if srch_no:
		params["srchNo"] = srch_no.replace("-", "").strip().upper()
	return _paged(_get(f"{SIMPL}/amd-cncl/trgt", params), "trsfSimplAmdCnclTrgtList", page, size)


@frappe.whitelist(methods=["POST"])
def simpl_amd_new(dclr_no: Scalar):
	return _one(_get(f"{SIMPL}/amd/new/{dclr_no}"), "trsfSimplAmd") or {}


@frappe.whitelist(methods=["POST"])
def simpl_amd(amd_dclr_no: Scalar):
	return _one(_get(f"{SIMPL}/amd/{amd_dclr_no}"), "trsfSimplAmd") or {}


@frappe.whitelist(methods=["POST"])
def simpl_amd_save(
	header: JSONish,
	info: JSONish | None = None,
	items: JSONish | None = None,
	bf_vehicles: Scalar | None = None,
	af_vehicles: Scalar | None = None,
	containers: JSONish | None = None,
	action: Scalar = "save",
):
	"""Body = portal getSaveData() for 0302012S."""
	header, info = _parse(header) or {}, _parse(info) or {}
	_assert_editable(header.get("prcssStatCd"), _("This amendment"))
	if not (header.get("amdRsn") or "").strip():
		frappe.throw(_("Amendment Reason is required"))
	af = _rows(af_vehicles)
	_validate_vehicles([v for v in af if v.get("dtlAmdTpCd") != "D"], require=False)
	values = {k: v for k, v in header.items() if not k.startswith("_")}
	body = {
		**values,
		"crn": info.get("crn"),
		"dptrWrhsCd": info.get("dptrWrhsCd"),
		"cgmeDclrAmdMDto": {**values, "dclrAmdItmRList": _rows(items)},
		"bfVhclAmdList": _rows(bf_vehicles),
		"afVhclAmdList": af,
		"trsfSimplCntrRList": _rows(containers),
	}
	return _write_result(
		_post(f"{SIMPL}/amd/sbmt" if action == "sbmt" else f"{SIMPL}/amd/save", body), "trsfSimpleAmd"
	)


@frappe.whitelist(methods=["POST"])
def simpl_amd_delete(header: JSONish):
	header = _parse(header) or {}
	_assert_editable(header.get("prcssStatCd"), _("This amendment"))
	return _put_json(f"{DCLR_AMD}/dclr-del", {"dclrAmdList": [header]})


@frappe.whitelist(methods=["POST"])
def simpl_cncl_list(
	from_rgsr_dt: Scalar,
	to_rgsr_dt: Scalar,
	srch_no_tp: Scalar = "dclrNo",
	srch_no: Scalar | None = None,
	prcss_stat_cds: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	params = {
		"page": cint(page),
		"size": cint(size),
		"fromRgsrDt": from_rgsr_dt,
		"toRgsrDt": to_rgsr_dt,
		"srchNoTp": srch_no_tp,
		"prcssStatCds": _csv(prcss_stat_cds, SIMPL_AMD_CNCL_STATUSES),
	}
	if srch_no:
		params["srchNo"] = srch_no.replace("-", "").strip().upper()
	return _paged(_get(f"{SIMPL}/cncl", params), "trsfSimplCnclList", page, size)


@frappe.whitelist(methods=["POST"])
def simpl_cncl_init(dclr_no: Scalar):
	return _one(_get(f"{SIMPL}/cncl/init/{dclr_no}"), "trsfSimplCncl") or {}


@frappe.whitelist(methods=["POST"])
def simpl_cncl(cncl_dclr_no: Scalar):
	return _one(_get(f"{SIMPL}/cncl/{cncl_dclr_no}"), "trsfSimplCncl") or {}


@frappe.whitelist(methods=["POST"])
def simpl_cncl_save(header: JSONish, containers: JSONish | None = None, action: Scalar = "save"):
	header = _parse(header) or {}
	_assert_editable(header.get("prcssStatCd"), _("This cancellation"))
	if not (header.get("cnclCn") or "").strip():
		frappe.throw(_("Cancellation Reason is required"))
	values = _stamp_declarant({k: v for k, v in header.items() if not k.startswith("_")})
	cntr = _rows(containers)
	if action == "sbmt":
		return _write_result(
			_post(f"{SIMPL}/cncl/sbmt", {**values, "cgmeDclrCnclMDto": values, "trsfSimplCntrRList": cntr}),
			"trsfSimplCncl",
		)
	return _write_result(_post(f"{SIMPL}/cncl", {**values, "cntrList": cntr}), "dclrCncl")


@frappe.whitelist(methods=["POST"])
def simpl_cncl_delete(cncl_dclr_no: Scalar):
	return tc._authed_delete(f"{SIMPL}/cncl/{cncl_dclr_no}")


# =================================================================== Carry-In (CGME-0401-001Q / 002S)
CRI = "/cgm/api/v1/cgme/wrhs/cri"
EDITABLE_ROW = (None, "", "A01", "A05", "D09")


@frappe.whitelist(methods=["POST"])
def cri_list(
	srch_aprv_dt_from: Scalar,
	srch_aprv_dt_to: Scalar,
	srch_rpt_stat: Scalar | None = None,
	srch_crn: Scalar | None = None,
	srch_reff_no: Scalar | None = None,
	srch_cntr_no: Scalar | None = None,
	srch_bcode_no: Scalar | None = None,
	srch_cri_tp_cd: Scalar | None = None,
	srch_crio_prcss_ut_cd: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	res = _get(
		CRI,
		{
			"page": cint(page),
			"size": cint(size),
			"srchAprvDtFrom": srch_aprv_dt_from,
			"srchAprvDtTo": srch_aprv_dt_to,
			"srchRptStat": _csv(srch_rpt_stat, ["N", "P", "Y"]),
			"srchCrn": _crn_search(srch_crn),
			"srchReffNo": (srch_reff_no or "").strip(),
			"srchCntrNo": (srch_cntr_no or "").strip().upper(),
			"srchBcodeNo": srch_bcode_no,
			"srchCriTpCd": srch_cri_tp_cd,
			"srchCrioPrcssUtCd": srch_crio_prcss_ut_cd,
		},
	)
	return _paged(res, "wrhsCriList", page, size)


@frappe.whitelist(methods=["POST"])
def cri_report_comments(form: Scalar, rows: JSONish):
	"""'Submit' on 001Q: sends the comments typed against expected carry-ins."""
	body = {**(_parse(form) or {}), "list": _rows(rows)}
	return _write_result(_post(f"{CRI}/sbmt", body), "cgmeXptdCriBlMDto")


@frappe.whitelist(methods=["POST"])
def cri_detail(crn: Scalar, wrhs_cd: Scalar, cri_base_no: Scalar):
	return _one(_get(f"{CRI}/imp/{crn}", {"wrhsCd": wrhs_cd, "criBaseNo": cri_base_no}), "wrhsCriImp") or {}


@frappe.whitelist(methods=["POST"])
def cri_search(
	crn: Scalar,
	wrhs_cd: Scalar,
	cri_base_no: Scalar,
	srch_bcode_no: Scalar | None = None,
	srch_drvr_lcne_no: Scalar | None = None,
):
	"""002S header 'Barcode (Scan Doc)' search — portal posts {srchBcodeNo, srchDrvrLcneNo, wrhsCd, criBaseNo, crn}."""
	if not (srch_bcode_no or "").strip():
		frappe.throw(_("Enter or scan the barcode first."))
	body = {
		"srchBcodeNo": srch_bcode_no.strip(),
		"srchDrvrLcneNo": (srch_drvr_lcne_no or "").strip() or None,
		"wrhsCd": wrhs_cd,
		"criBaseNo": cri_base_no,
		"crn": crn,
	}
	d = _one(_post(f"{CRI}/imp/srch", body, write=False), "wrhsCriImp") or {}
	if not d.get("crn"):
		frappe.throw(_("No data found for this barcode."))
	return d


@frappe.whitelist(methods=["POST"])
def cri_vehicle_search(header: JSONish, srch_cntr_no: Scalar | None = None):
	"""002S 'Container No. [Search]' above the vehicle grid: POST /imp/srch with the whole report form,
	srchCntrNo and wrhsCriVhclList=null — the portal's getWrhsCriImpVhclLst. Empty container = all vehicles."""
	header = {k: v for k, v in (_parse(header) or {}).items() if not isinstance(v, list)}
	body = {**header, "srchCntrNo": (srch_cntr_no or "").strip().upper(), "wrhsCriVhclList": None}
	return _one(_post(f"{CRI}/imp/srch", body, write=False), "wrhsCriImp") or {}


@frappe.whitelist(methods=["POST"])
def cri_driver_lookup(drvr_lcne_no: Scalar, page: Scalar = 0, size: Scalar = 10):
	"""Driver licence popup on 002S (GET /drvr-ppup): rows cntrNo, drvrNm, vhclNo, bcodeNo."""
	if not (drvr_lcne_no or "").strip():
		frappe.throw(_("Enter the driver licence number."))
	res = _get(
		f"{CRI}/drvr-ppup", {"page": cint(page), "size": cint(size), "drvrLcneNo": drvr_lcne_no.strip()}
	)
	return _paged(res, "wrhsCriDrvrList", page, size)


@frappe.whitelist(methods=["POST"])
def cri_container_detail(row: JSONish):
	return _one(_post(f"{CRI}/imp/cntr/dtl", _parse(row) or {}, write=False), "wrhsCriImpCntrDtl") or {}


CRI_LIST_KEY = {"B": "criBlMList", "V": "criVhclRList", "C": "criCntrRList", "I": "criItmRList"}
CRO_LIST_KEY = {"B": "croBlMList", "V": "croVhclRList", "C": "croCntrRList", "I": "croItmRList"}


def _unit_rows(header, rows, keys, label):
	header = _parse(header) or {}
	unit = header.get("crioPrcssUtCd") or "B"
	rows = _rows(rows)
	if not rows:
		frappe.throw(_("Select at least one row"))
	return header, unit, rows, keys[unit]


@frappe.whitelist(methods=["POST"])
def cri_save(header: JSONish, rows: JSONish):
	header, unit, rows, key = _unit_rows(header, rows, CRI_LIST_KEY, "Carry-In")
	if unit == "B":
		for r in rows:
			if r.get("criPckgNo") in (None, "") and header.get("bulkYn") != "Y":
				frappe.throw(_("Carry-in packages are required"))
			if r.get("criWght") in (None, ""):
				frappe.throw(_("Carry-in weight is required"))
	res = _post(f"{CRI}/imp", {**header, key: rows})
	c = _content(res, "wrhsCriImp") or {}
	if c.get("msgList"):
		frappe.throw(
			"<br>".join(
				frappe.utils.escape_html(str(m.get("msg") if isinstance(m, dict) else m))
				for m in c["msgList"]
			)
		)
	_persist_carry_in(header, rows, c)
	return c


# Portal 002S form_criDclaRgsr: Submit posts ONLY these header fields ({...criDclaRgsr.getValues()}),
# with the two date fields as YYYY-MM-DD (date controls) — no MRN, no vehicle/container lists.
CRI_SBMT_FIELDS = (
	"srchCntrNo",
	"criBaseNo",
	"aprvDt",
	"criTpCd",
	"trsfEndDt",
	"crn",
	"crioPrcssUtCd",
	"criXptdPckgNo",
	"pckgUtCd",
	"criXptdWght",
	"wghtUtCd",
	"godsDesc",
	"wrhsCd",
	"wrhsNm",
	"bulkYn",
	"newableYn",
	"criRprtYn",
)


def _ymd(v):
	d = re.sub(r"[^0-9]", "", str(v or ""))
	return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) >= 8 else v


@frappe.whitelist(methods=["POST"])
def cri_submit(header: JSONish, reception: JSONish | None = None):
	require_tanesw_user()  # in Test Mode nothing is sent to TANeSW, so the TANeSW login's role check never runs
	h = _parse(header) or {}
	body = {k: h.get(k) for k in CRI_SBMT_FIELDS}
	body["srchCntrNo"] = body.get("srchCntrNo") or ""
	body["aprvDt"], body["trsfEndDt"] = _ymd(body.get("aprvDt")), _ymd(body.get("trsfEndDt"))
	from tanesw_integration import test_mode

	simulated = test_mode.on()  # TEST MODE: nothing goes to TANeSW, the ERP side below still runs
	res = None if simulated else _post(f"{CRI}/imp/sbmt", body)
	out = test_mode.simulated_carry_in_submit(body) if simulated else _write_result(res, "cgmeCriBlMDto")
	pb = body.get("criBaseNo") or body.get("crn")
	if pb and not simulated and frappe.db.exists("TANeSW Carry In", pb):
		try:
			doc = frappe.get_doc("TANeSW Carry In", pb)
			doc.status = "REPORTED"
			doc.process_status_code = "A01"
			if res:
				doc.submission_response = frappe.as_json(res)
			doc.flags.ignore_links = True
			doc.save()
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- TANeSW has already accepted it: our copy must survive a later ERP error
		except Exception as e:
			frappe.log_error(f"Error updating Carry In on submit: {e}")
	if reception and isinstance(out, dict):
		# the gate clerk gave yard location + clerk: receive into the ERP now (Container Reception submitted)
		try:
			from tanesw_integration.icd_link import receive_carry_in

			out["icd_reception"] = receive_carry_in(body.get("crn"), body.get("criBaseNo"), _parse(reception))
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title="TANeSW carry-in: receiving into the ERP failed", message=frappe.get_traceback()
			)
			frappe.clear_messages()
			out["icd_reception_error"] = _(
				"TANeSW accepted the carry-in, but receiving into the ERP failed; the "
				"5-minute check will draft the reception. See Error Log."
			)
	try:
		from tanesw_integration.icd_link import on_carry_in_submitted

		on_carry_in_submitted(body)  # draft the icd_tz reception now, not at the next 5-minute check
	except Exception:
		frappe.log_error(
			title="TANeSW carry-in: could not queue the ICD link", message=frappe.get_traceback()
		)
	return out


@frappe.whitelist(methods=["POST"])
def cri_delete(header: JSONish, rows: JSONish):
	header, _unit, rows, key = _unit_rows(header, rows, CRI_LIST_KEY, "Carry-In")
	for r in rows:
		if r.get("dclrNo") and r.get("prcssStatCd") not in ("A01", "A05"):
			frappe.throw(_("Report {0} can no longer be deleted").format(r.get("dclrNo")))
	return _content(_post(f"{CRI}/imp/del-cri", {**header, key: rows}), "cgmeCriBlMDto") or {}


# =================================================================== Carry-Out (CGME-0401-008Q / 009S)
CRO = "/cgm/api/v1/cgme/wrhs/cro"


@frappe.whitelist(methods=["POST"])
def cro_list(
	srch_aprv_dt_from: Scalar,
	srch_aprv_dt_to: Scalar,
	srch_rpt_stat: Scalar | None = None,
	srch_crn: Scalar | None = None,
	srch_reff_no: Scalar | None = None,
	srch_cro_tp_cd: Scalar | None = None,
	srch_crio_prcss_ut_cd: Scalar | None = None,
	srch_exit_cfrm_yn: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	res = _get(
		CRO,
		{
			"page": cint(page),
			"size": cint(size),
			"srchAprvDtFrom": srch_aprv_dt_from,
			"srchAprvDtTo": srch_aprv_dt_to,
			"srchRptStat": _csv(srch_rpt_stat, ["N", "P", "Y"]),
			"srchCrn": _crn_search(srch_crn),
			"srchReffNo": (srch_reff_no or "").strip(),
			"srchCroTpCd": srch_cro_tp_cd,
			"srchCrioPrcssUtCd": srch_crio_prcss_ut_cd,
			# Exit status radio: "" All, N Not Exit, Y Exit Confirm. The portal always sends the key, even empty.
			"srchExitCfrmYn": srch_exit_cfrm_yn if srch_exit_cfrm_yn in ("N", "Y") else "",
		},
	)
	return _paged(res, "wrhsCroList", page, size)


@frappe.whitelist(methods=["POST"])
def cro_gate_check(row: JSONish):
	"""Portal checks gate confirmation before opening a carry-out."""
	res = _post(f"{CRO}/chk-gate-cfrm", _parse(row) or {}, write=False)
	c = _content(res, "cgmeCroBlMDto") or {}
	if c.get("confirmYn") == "N":
		frappe.throw(
			str(c.get("message") or "").replace("Gate confirmation", "Carry-out").replace("\\n", "<br>")
		)
	return c.get("gateCfrmCheck") or _parse(row)


@frappe.whitelist(methods=["POST"])
def cro_detail(cro_base_no: Scalar, crn: Scalar, wrhs_cd: Scalar, mrn: Scalar | None = None):
	return _one(_get(f"{CRO}/{cro_base_no}", {"crn": crn, "wrhsCd": wrhs_cd, "mrn": mrn}), "wrhsCro") or {}


@frappe.whitelist(methods=["POST"])
def cro_driver_suggestions(**kw):
	res = _get(f"{CRO}/auto-drvrInfo", {k: v for k, v in kw.items() if k not in ("cmd",)})
	return _content(res, "drvrInfoList") or []


def _cro_header(header):
	"""009S header as the portal posts it (POST /wrhs/cro and /wrhs/cro/sbmt):
	the detail GET gives aprvDt "2026-11-02 00:00:00", the portal sends "2026-11-02"; detail-only lists are not sent."""
	h = {k: v for k, v in (header or {}).items() if not str(k).startswith("_") or k == "_escrow"}
	if isinstance(h.get("aprvDt"), str) and len(h["aprvDt"]) > 10:
		h["aprvDt"] = h["aprvDt"][:10]
	for k in (
		"wrhsCroVhclLst",
		"wrhsCroCntrLst",
		"wrhsCroItmLst",
		"wrhsCroBlLst",
		"xptdCroCntrRList",
		"xptdCroItmRList",
		"xptdCroVhclRList",
		"list",
	):
		h.pop(k, None)
	return h


@frappe.whitelist(methods=["POST"])
def cro_save(header: JSONish, rows: JSONish):
	header, unit, rows, key = _unit_rows(header, rows, CRO_LIST_KEY, "Carry-Out")
	if unit == "B":
		for r in rows:
			for f, label in (
				("drvrNm", "Driver Name"),
				("drvrLcneNo", "Licence No."),
				("vhclNo", "Vehicle No."),
			):
				if not r.get(f):
					frappe.throw(_("{0} is required").format(label))
	body = {**_cro_header(header), key: rows}
	if header.get("_escrow") == "Y":
		body["im4EscrowOilYn"] = "Y"
	body.pop("_escrow", None)
	res = _post(CRO, body)
	c = _write_result(res, "cgmeCroBlMDto") or {}
	if c.get("msgList"):
		frappe.throw(
			"<br>".join(
				frappe.utils.escape_html(str(m.get("msg") if isinstance(m, dict) else m))
				for m in c["msgList"]
			)
		)
	_persist_carry_out(header, rows, c)
	return c


@frappe.whitelist(methods=["POST"])
def cro_submit(header: JSONish):
	res = _write_result(
		_post(f"{CRO}/sbmt", {k: v for k, v in _cro_header(_parse(header) or {}).items() if k != "_escrow"}),
		"cgmeCroBlMDto",
	)
	_persist_carry_out(_parse(header) or {}, [], res)
	return res


@frappe.whitelist(methods=["POST"])
def cro_delete(header: JSONish, rows: JSONish):
	header, _unit, rows, key = _unit_rows(header, rows, CRO_LIST_KEY, "Carry-Out")
	for r in rows:
		if r.get("dclrNo") and r.get("prcssStatCd") not in ("A01", "A05"):
			frappe.throw(_("Report {0} can no longer be deleted").format(r.get("dclrNo")))
	return _content(_post(f"{CRO}/del-cro", {**header, key: rows}), "cgmeCroBlMDto") or {}


@frappe.whitelist(methods=["POST"])
def cro_change_unit(header: JSONish):
	"""'Change processing unit' button (savePrcssUtCdChg)."""
	return _post(f"{CRO}/chg", _parse(header) or {})


# =================================================================== Stripping (CGME-0406-0xx)
STRP = "/cgm/api/v1/cgme/bw/strpng"


@frappe.whitelist(methods=["POST"])
def strp_schedule(
	rgsr_dt_from: Scalar | None = None,
	rgsr_dt_to: Scalar | None = None,
	mrn: Scalar | None = None,
	crn: Scalar | None = None,
	prcss_stat_cd: Scalar = "All",
	page: Scalar = 0,
	size: Scalar = 10,
):
	res = _get(
		f"{STRP}/schd",
		{
			"page": cint(page),
			"size": cint(size),
			"rgsrDtFrom": rgsr_dt_from,
			"rgsrDtTo": rgsr_dt_to,
			"mrn": (mrn or "").strip().upper(),
			"crn": (crn or "").strip().upper(),
			"prcssStatCd": prcss_stat_cd or "All",
		},
	)
	return _paged(res, "bwStrpngSchdList", page, size)


def _strp_list(
	path, key, rgsr_dt_from, rgsr_dt_to, gen_item, srch_opt, srch_stat_cd, page, size, target=False
):
	"""Stripping lists, as the portal sends them:
	the search box fills mrn / cntrNo / rprtNo depending on the selector, and wrhsCd is ALWAYS the
	logged-in warehouse — without it TANeSW returns every warehouse's reports (189 vs 7 on one week).
	Amendment/cancellation target pick-lists add srchStatCd=J07 (CONFIRMED) and amdYn=Y."""
	opt = (srch_opt or "").strip().upper()
	if gen_item == "rprtNo":
		opt = opt.replace("-", "")
	params = {
		"page": cint(page),
		"size": cint(size),
		"rgsrDtFrom": rgsr_dt_from,
		"rgsrDtTo": rgsr_dt_to,
		"genItem": gen_item or "rprtNo",
		"mrn": "",
		"cntrNo": "",
		"rprtNo": "",
		"wrhsCd": _user_info().get("coDclaCd"),
	}
	if gen_item in ("mrn", "cntrNo", "rprtNo") and opt:
		params[gen_item] = opt
	if target:
		params.update({"srchStatCd": "J07", "amdYn": "Y"})
	else:
		params["srchStatCd"] = _csv(srch_stat_cd, []) or None
	return _paged(_get(path, params), key, page, size)


@frappe.whitelist(methods=["POST"])
def strp_report_list(
	rgsr_dt_from: Scalar | None = None,
	rgsr_dt_to: Scalar | None = None,
	gen_item: Scalar = "rprtNo",
	srch_opt: Scalar | None = None,
	srch_stat_cd: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	return _strp_list(
		f"{STRP}/rpt",
		"bwStrpngRptList",
		rgsr_dt_from,
		rgsr_dt_to,
		gen_item,
		srch_opt,
		srch_stat_cd,
		page,
		size,
	)


@frappe.whitelist(methods=["POST"])
def strp_report(rprt_no: Scalar):
	return _one(_get(f"{STRP}/rpt/{rprt_no}"), "bwStrpngRpt") or {}


@frappe.whitelist(methods=["POST"])
def strp_report_save(header: JSONish, action: Scalar = "save"):
	header = _parse(header) or {}
	_assert_editable(header.get("prcssStatCd"), _("This report"))
	for f, label in (("mrn", "MRN"), ("strpngDt", "Stripping Date"), ("strpngRsltTpCd", "Stripping Type")):
		if not header.get(f):
			frappe.throw(_("{0} is required").format(label))
	values = {k: v for k, v in header.items() if not k.startswith("_")}
	res = _write_result(
		_post(f"{STRP}/rpt/sbmt" if action == "sbmt" else f"{STRP}/rpt", values), "cgmeStrpngRsltMDto"
	)
	_persist_stripping_report(values, res)
	return res


@frappe.whitelist(methods=["POST"])
def strp_report_delete(rprt_no: Scalar):
	return tc._authed_delete(f"{STRP}/rpt/{rprt_no}")


@frappe.whitelist(methods=["POST"])
def strp_lcl_candidates(
	mrn: Scalar,
	rprt_no: Scalar | None = None,
	crn: Scalar | None = None,
	prcss_stat_cd: Scalar = "All",
	page: Scalar = 0,
	size: Scalar = 50,
):
	res = _get(
		f"{STRP}/lcl-ppup",
		{
			"page": cint(page),
			"size": cint(size),
			"mrn": mrn,
			"rprtNo": rprt_no,
			"crn": (crn or "").strip().upper(),
			"prcssStatCd": prcss_stat_cd,
		},
	)
	return _paged(res, "bwStrpngLclPpupList", page, size)


@frappe.whitelist(methods=["POST"])
def strp_normal_bls(
	rprt_no: Scalar | None = None, mrn: Scalar | None = None, amd_dclr_no: Scalar | None = None
):
	res = _get(f"{STRP}/nrml-bl-ppup", {"rprtNo": rprt_no, "mrn": mrn, "amdDclrNo": amd_dclr_no})
	return _content(res, "bwStrpngNrmlBlPpupList") or []


@frappe.whitelist(methods=["POST"])
def strp_add_normal_bls(rprt_no: Scalar, mrn: Scalar, rows: JSONish):
	rows = _rows(rows)
	if not rows:
		frappe.throw(_("Select at least one B/L"))
	for r in rows:
		r["rprtNo"] = rprt_no
	return _post(
		f"{STRP}/nrml-bl-ppup",
		{"mrn": mrn, "rprtNo": rprt_no, "prcssStatCd": "All", "strpngRsltBlRList": rows},
	)


@frappe.whitelist(methods=["POST"])
def strp_delete_rows(kind: Scalar, keys: Scalar):
	"""kind: nrml | mbl | hbl. keys like 'rprtNo!mblNo!hblNo!crn' (portal format)."""
	path = {"nrml": "nrml-bl-ppup", "mbl": "mbl-abnr-ppup", "hbl": "hbl-abnr-ppup"}[kind]
	return tc._authed_delete(f"{STRP}/{path}/{','.join(_rows(keys))}")


@frappe.whitelist(methods=["POST"])
def strp_abnormal(
	kind: Scalar, rprt_no: Scalar | None = None, amd_dclr_no: Scalar | None = None, mrn: Scalar | None = None
):
	path, key = {
		"mbl": ("mbl-abnr-ppup", "bwStrpngMblAbnrPpupList"),
		"hbl": ("hbl-abnr-ppup", "bwStrpngHblAbnrPpupList"),
	}[kind]
	return (
		_content(_get(f"{STRP}/{path}", {"rprtNo": rprt_no, "amdDclrNo": amd_dclr_no, "mrn": mrn}), key) or []
	)


@frappe.whitelist(methods=["POST"])
def strp_save_abnormal(kind: Scalar, row: JSONish):
	"""Short/over-landed MBL or HBL row (I insert / U update / D delete)."""
	path = {"mbl": "mbl-abnr-ppup", "hbl": "hbl-abnr-ppup"}[kind]
	return _post(f"{STRP}/{path}", _parse(row) or {})


@frappe.whitelist(methods=["POST"])
def strp_bl_containers(row: JSONish):
	return _content(_get(f"{STRP}/cntr-rgsr-ppup", _parse(row) or {}), "bwStrpngCntrRgsrPpupList") or []


@frappe.whitelist(methods=["POST"])
def strp_save_bl_containers(row: JSONish, containers: JSONish):
	return _post(f"{STRP}/cntr-rgsr-ppup", {**(_parse(row) or {}), "strpngRsltCntrList": _rows(containers)})


@frappe.whitelist(methods=["POST"])
def strp_delete_bl_containers(keys: Scalar):
	return tc._authed_delete(f"{STRP}/cntr-rgsr-ppup/{','.join(_rows(keys))}")


@frappe.whitelist(methods=["POST"])
def strp_amd_list(
	rgsr_dt_from: Scalar | None = None,
	rgsr_dt_to: Scalar | None = None,
	gen_item: Scalar = "rprtNo",
	srch_opt: Scalar | None = None,
	srch_stat_cd: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	return _strp_list(
		f"{STRP}/amd",
		"bwStrpngAmdList",
		rgsr_dt_from,
		rgsr_dt_to,
		gen_item,
		srch_opt,
		srch_stat_cd,
		page,
		size,
	)


@frappe.whitelist(methods=["POST"])
def strp_targets(
	kind: Scalar,
	rgsr_dt_from: Scalar | None = None,
	rgsr_dt_to: Scalar | None = None,
	gen_item: Scalar = "rprtNo",
	srch_opt: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	path, key = {"amd": ("amd/trgt", "bwStrpngAmdTrgtList"), "cncl": ("cncl/trgt", "bwStrpngCnclTrgtList")}[
		kind
	]
	return _strp_list(
		f"{STRP}/{path}", key, rgsr_dt_from, rgsr_dt_to, gen_item, srch_opt, None, page, size, target=True
	)


@frappe.whitelist(methods=["POST"])
def strp_amd(no: Scalar):
	return _one(_get(f"{STRP}/amd/{no}"), "bwStrpngAmd") or {}


@frappe.whitelist(methods=["POST"])
def strp_amd_save(header: JSONish, action: Scalar = "save"):
	header = _parse(header) or {}
	if not (header.get("amdRsn") or "").strip():
		frappe.throw(_("Amendment Comment is required"))
	values = {k: v for k, v in header.items() if not k.startswith("_")}
	return _write_result(
		_post(f"{STRP}/amd/sbmt" if action == "sbmt" else f"{STRP}/amd", values), "cgmeDclrAmdMDto"
	)


@frappe.whitelist(methods=["POST"])
def strp_amd_delete(amd_dclr_no: Scalar):
	return tc._authed_delete(f"{STRP}/amd/{amd_dclr_no}")


@frappe.whitelist(methods=["POST"])
def strp_cncl_list(
	rgsr_dt_from: Scalar | None = None,
	rgsr_dt_to: Scalar | None = None,
	gen_item: Scalar = "rprtNo",
	srch_opt: Scalar | None = None,
	srch_stat_cd: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	return _strp_list(
		f"{STRP}/cncl",
		"bwStrpngCnclList",
		rgsr_dt_from,
		rgsr_dt_to,
		gen_item,
		srch_opt,
		srch_stat_cd,
		page,
		size,
	)


@frappe.whitelist(methods=["POST"])
def strp_cncl(no: Scalar):
	return _one(_get(f"{STRP}/cncl/{no}"), "bwStrpngCncl") or {}


@frappe.whitelist(methods=["POST"])
def strp_cncl_save(header: JSONish, action: Scalar = "save"):
	header = _parse(header) or {}
	if not (header.get("cnclCn") or "").strip():
		frappe.throw(_("Cancellation Comment is required"))
	values = _stamp_declarant({k: v for k, v in header.items() if not k.startswith("_")})
	return _write_result(
		_post(f"{STRP}/cncl/sbmt" if action == "sbmt" else f"{STRP}/cncl", values), "dclrCncl"
	)


@frappe.whitelist(methods=["POST"])
def strp_cncl_delete(cncl_dclr_no: Scalar):
	return tc._authed_delete(f"{STRP}/cncl/{cncl_dclr_no}")


# =================================================================== Cargo Tracking (CGME-0910-001Q)
TRK = "/cgm/api/v1/cgme/trkng"


@frappe.whitelist(methods=["POST"])
def tracking_search(
	srch_crn: Scalar | None = None, srch_bl_no: Scalar | None = None, srch_cntr_no: Scalar | None = None
):
	"""CGME-0910-001Q. One hit -> {count:1, detail}; several -> {count:n, crns:[...]}."""
	params = {
		"srchCrn": _crn_search(srch_crn),
		"srchBlNo": (srch_bl_no or "").strip().upper(),
		"srchCntrNo": (srch_cntr_no or "").strip().upper(),
	}
	if not any(params.values()):
		frappe.throw(_("Input Search Condition"))
	res = _get(f"{TRK}/srch", params)
	count = cint(_content(res, "totalCnt"))
	data = _content(res, "trkngDtl")
	if count == 1:
		return {"count": 1, "detail": data if isinstance(data, dict) else (data or [{}])[0]}
	return {"count": count, "crns": data if isinstance(data, list) else []}


@frappe.whitelist(methods=["POST"])
def tracking_detail(crn: Scalar):
	return _one(_get(f"{TRK}/{crn.strip().upper()}"), "trkngDtl") or {}


@frappe.whitelist(methods=["POST"])
def tracking_container(crn: Scalar, cntr_no: Scalar):
	return _one(_get(f"{TRK}/cntr-dtl", {"srchCrn": crn, "srchCntrNo": cntr_no}), "trkngCntrDtl") or {}


@frappe.whitelist(methods=["POST"])
def tracking_export_containers(srch_mbl_no: Scalar, page: Scalar = 0, size: Scalar = 10):
	res = _get(
		f"{TRK}/exp-cntr", {"page": cint(page), "size": cint(size), "srchMblNo": srch_mbl_no.strip().upper()}
	)
	return _paged(res, "trkngExpCntrLst", page, size)


# =================================================================== Carry-In/Out shared result helpers
def _raise_lists(content):
	"""Portal pattern for submit: any comnErrList/indvErrList entry -> error popup."""
	if not isinstance(content, dict):
		return content
	errs = (content.get("comnErrList") or []) + (content.get("indvErrList") or [])
	if errs:
		lines = [
			(e.get("errMsg") or e.get("msg") or e.get("errCn") or frappe.as_json(e))
			if isinstance(e, dict)
			else str(e)
			for e in errs
		]
		frappe.throw("<br>".join(frappe.utils.escape_html(x) for x in lines), title=_("TANeSW validation"))
	return content


def _raise_msgs(content):
	"""Portal pattern for save: content.msgList -> message popup (nothing saved)."""
	if isinstance(content, dict) and content.get("msgList"):
		frappe.throw(
			"<br>".join(
				frappe.utils.escape_html(str(m.get("msg") if isinstance(m, dict) else m))
				for m in content["msgList"]
			)
		)
	return content


def _strip_lists(header, keys):
	return {k: v for k, v in (header or {}).items() if k not in keys and not isinstance(v, list)}


def _deletable(rows):
	for r in rows:
		if r.get("addRow") == "I":
			continue
		if not r.get("dclrNo") and not r.get("prcssStatCd"):
			frappe.throw(_("Deletion is not possible."))
		if r.get("dclrNo") and r.get("prcssStatCd") not in ("A01", "A05"):
			frappe.throw(_("Deletion is not possible. [{0}]").format(r.get("dclrNo")))
	return [r for r in rows if r.get("addRow") != "I"]


# =================================================================== Bulk Carry-In (CGME-0401-005Q / 006S)
# Reached from the Carry-In list ("Bulk Carry-In" button), as in the portal.


@frappe.whitelist(methods=["POST"])
def cri_bulk_list(
	srch_aprv_dt_from: Scalar,
	srch_aprv_dt_to: Scalar,
	srch_mrn: Scalar | None = None,
	srch_bl_no: Scalar | None = None,
	srch_rpt_stat: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
):
	res = _get(
		f"{CRI}/bulk",
		{
			"page": cint(page),
			"size": cint(size),
			"srchAprvDtFrom": srch_aprv_dt_from,
			"srchAprvDtTo": srch_aprv_dt_to,
			"srchMrn": (srch_mrn or "").strip().upper(),
			"srchBlNo": (srch_bl_no or "").strip().upper(),
			"srchRptStat": _csv(srch_rpt_stat, ["N", "P", "Y"]),
		},
	)
	return _paged(res, "wrhsCriBulkList", page, size)


@frappe.whitelist(methods=["POST"])
def cri_bulk_detail(mrn: Scalar, cri_base_no: Scalar, report_yn: Scalar = "N"):
	"""GET /bulk/{mrn}?criBaseNo&criRprtYn. report_yn N = not reported (editable), P/Y = view."""
	return (
		_one(
			_get(
				f"{CRI}/bulk/{mrn.strip().upper()}", {"criBaseNo": cri_base_no, "criRprtYn": report_yn or "N"}
			),
			"wrhsCriBulk",
		)
		or {}
	)


@frappe.whitelist(methods=["POST"])
def cri_bulk_save(header: JSONish, rows: JSONish):
	"""Save: {...MRN form (criDt = expected carry-in date), criBlMList: ticked master B/L rows}."""
	header = _strip_lists(_parse(header), ("wrhsCriBulkList",))
	rows = _rows(rows)
	if not rows:
		frappe.throw(_("Select at least one row"))
	if not header.get("criDt"):
		frappe.throw(_("Carry-in date is required"))
	for r in rows:
		if r.get("prcssStatCd"):
			frappe.throw(_("{0} has already been processed").format(r.get("awb") or r.get("crn")))
	return _content(_post(f"{CRI}/bulk", {**header, "criBlMList": rows}), "cgmeCriBlMDto") or {}


@frappe.whitelist(methods=["POST"])
def cri_bulk_submit(header: JSONish, cri_base_no: Scalar, cri_tp_cd: Scalar):
	header = _strip_lists(_parse(header), ("wrhsCriBulkList",))
	c = (
		_content(
			_post(f"{CRI}/bulk/sbmt", {**header, "criBaseNo": cri_base_no, "criTpCd": cri_tp_cd}),
			"cgmeCriBlMDto",
		)
		or {}
	)
	if c.get("success") == "ZEROCARRYINCOUNT":
		frappe.throw(_("Nothing to submit — save the carry-in first."))
	return _raise_lists(c)


# =================================================================== B/L based Carry-In (CGME-0401-003S, /cri/exp)
CRI_BL_KEY = {"B": "criBlMList", "C": "criCntrRList"}
CRI_BL_LISTS = ("wrhsCriBlList", "wrhsCriCntrList")


@frappe.whitelist(methods=["POST"])
def cri_bl_detail(hbl_no: Scalar, mbl_no: Scalar, wrhs_cd: Scalar, cri_base_no: Scalar):
	"""GET /cri/exp/{hblNo}?mblNo&wrhsCd&expCriBaseNo — opened from Carry-In rows that carry an M B/L."""
	return (
		_one(
			_get(f"{CRI}/exp/{hbl_no}", {"mblNo": mbl_no, "wrhsCd": wrhs_cd, "expCriBaseNo": cri_base_no}),
			"wrhsCriExp",
		)
		or {}
	)


@frappe.whitelist(methods=["POST"])
def cri_bl_search(srch_bcode_no: Scalar):
	if not (srch_bcode_no or "").strip():
		frappe.throw(_("Enter or scan the barcode first."))
	d = (
		_one(_post(f"{CRI}/exp/srch", {"srchBcodeNo": srch_bcode_no.strip()}, write=False), "wrhsCriExp")
		or {}
	)
	if not d:
		frappe.throw(_("No data found for this barcode."))
	return d


@frappe.whitelist(methods=["POST"])
def cri_bl_container_detail(row: JSONish):
	return _one(_post(f"{CRI}/exp/cntr/dtl", _parse(row) or {}, write=False), "wrhsCriExpCntrDtl") or {}


@frappe.whitelist(methods=["POST"])
def cri_bl_save(header: JSONish, rows: JSONish):
	header = _strip_lists(_parse(header), CRI_BL_LISTS)
	unit = header.get("crioPrcssUtCd") or "B"
	if unit not in CRI_BL_KEY:
		frappe.throw(_("Processing unit {0} is not used on B/L based carry-in").format(unit))
	rows = _rows(rows)
	if not rows:
		frappe.throw(_("Select at least one row"))
	if unit == "B":
		for r in rows:
			for f, label in (
				("criDt", "Carry-in date"),
				("criPckgNo", "Carry-in packages"),
				("criWght", "Carry-in weight"),
			):
				if r.get(f) in (None, ""):
					frappe.throw(_("{0} is required").format(label))
	c = _raise_msgs(
		_content(_post(f"{CRI}/exp", {**header, CRI_BL_KEY[unit]: rows}), "cgmeExpCriBlMDto") or {}
	)
	_persist_carry_in(header, rows, c)
	return c


@frappe.whitelist(methods=["POST"])
def cri_bl_submit(header: JSONish):
	header = _strip_lists(_parse(header), CRI_BL_LISTS)
	return _raise_lists(_content(_post(f"{CRI}/exp/sbmt", header), "cgmeExpCriBlMDto") or {})


@frappe.whitelist(methods=["POST"])
def cri_bl_delete(header: JSONish, rows: JSONish):
	header = _strip_lists(_parse(header), CRI_BL_LISTS)
	unit = header.get("crioPrcssUtCd") or "B"
	rows = _deletable(_rows(rows))
	if not rows:
		return {"delCnt": 0}
	return (
		_content(
			_post(f"{CRI}/exp/del-cri", {**header, CRI_BL_KEY.get(unit, "criBlMList"): rows}), "cgmeCriBlMDto"
		)
		or {}
	)


# =================================================================== B/L based Carry-Out (CGME-0401-017S, /cro/exp)
CRO_BL_KEY = {"B": "croBlMList", "C": "croCntrRList"}
CRO_BL_LISTS = ("wrhsCroBlLst", "wrhsCroCntrLst", "wrhsCroVhclLst", "wrhsCroItmLst")


@frappe.whitelist(methods=["POST"])
def cro_bl_detail(cro_base_no: Scalar, mbl_no: Scalar, hbl_no: Scalar, wrhs_cd: Scalar, cro_tp_cd: Scalar):
	"""GET /cro/exp/{croBaseNo}?mblNo&hblNo&wrhsCd&croTpCd — Carry-Out rows that carry an M B/L."""
	return (
		_one(
			_get(
				f"{CRO}/exp/{cro_base_no}",
				{"mblNo": mbl_no, "hblNo": hbl_no, "wrhsCd": wrhs_cd, "croTpCd": cro_tp_cd},
			),
			"wrhsCro",
		)
		or {}
	)


@frappe.whitelist(methods=["POST"])
def cro_bl_driver_suggestions(mbl_no: Scalar, hbl_no: Scalar):
	return (
		_content(_get(f"{CRO}/auto-drvrInfo-exp", {"mblNo": mbl_no, "hblNo": hbl_no}), "drvrInfoList") or []
	)


@frappe.whitelist(methods=["POST"])
def cro_bl_save(header: JSONish, rows: JSONish):
	header = _strip_lists(_parse(header), CRO_BL_LISTS)
	unit = header.get("crioPrcssUtCd") or "B"
	if unit not in CRO_BL_KEY:
		frappe.throw(_("Processing unit {0} is not used on B/L based carry-out").format(unit))
	rows = _rows(rows)
	if not rows:
		frappe.throw(_("Select at least one row"))
	if unit == "B":
		for r in rows:
			for f, label in (
				("drvrNm", "Driver Name"),
				("drvrLcneNo", "Licence No."),
				("croDt", "Carry-out date"),
				("vhclNo", "Vehicle No."),
				("croPckgNo", "Carry-out packages"),
				("croWght", "Carry-out weight"),
			):
				if r.get(f) in (None, "") and not (f == "croPckgNo" and header.get("bulkYn") == "Y"):
					frappe.throw(_("{0} is required").format(label))
	return _raise_msgs(
		_content(_post(f"{CRO}/exp/save", {**header, CRO_BL_KEY[unit]: rows}), "cgmeCroBlMDto") or {}
	)


@frappe.whitelist(methods=["POST"])
def cro_bl_submit(header: JSONish):
	header = _strip_lists(_parse(header), CRO_BL_LISTS)
	return _raise_lists(_content(_post(f"{CRO}/exp/sbmt", header), "cgmeCroBlMDto") or {})


@frappe.whitelist(methods=["POST"])
def cro_bl_delete(header: JSONish, rows: JSONish):
	header = _strip_lists(_parse(header), CRO_BL_LISTS)
	unit = header.get("crioPrcssUtCd") or "B"
	rows = _deletable(_rows(rows))
	if not rows:
		return {"delCnt": 0}
	return (
		_content(
			_post(f"{CRO}/exp/del-cro", {**header, CRO_BL_KEY.get(unit, "croBlMList"): rows}), "cgmeCroBlMDto"
		)
		or {}
	)


# =================================================================== Grid export
@frappe.whitelist(methods=["POST"])
def export_xlsx(title: Scalar, headers: JSONish, rows: JSONish):
	"""'Excel Download' on list screens. The portal exports the grid on screen as .xlsx; same here."""
	from tanesw_integration.credentials import require_tanesw_user

	require_tanesw_user()
	from io import BytesIO

	from openpyxl import Workbook
	from openpyxl.styles import Font, PatternFill

	headers, rows = _parse(headers) or [], _parse(rows) or []
	wb = Workbook()
	ws = wb.active
	ws.title = (str(title) or "Sheet1")[:31].replace("/", "-")
	ws.append([str(h) for h in headers])
	for c in ws[1]:
		c.font = Font(bold=True)
		c.fill = PatternFill("solid", fgColor="DDE7F3")
	for r in rows:
		ws.append([("" if v is None else v) for v in r])
	for i, h in enumerate(headers, 1):
		width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows if i - 1 < len(r)])
		ws.column_dimensions[ws.cell(1, i).column_letter].width = min(60, max(10, width + 2))
	ws.freeze_panes = "A2"
	buf = BytesIO()
	wb.save(buf)
	stamp = frappe.utils.now_datetime().strftime("%Y%m%d%H%M%S")
	return {"filename": f"{title}[{stamp}].xlsx", "content": base64.b64encode(buf.getvalue()).decode()}


# =================================================================== Templates / Excel upload (Simple Transfer list)
SIMPL_TEMPLATE_UUID = "1d3f8699-1074-e755-e063-020011ac94db"  # portal HZ.downloadTemplate(...) on 0302-001Q


def _session():
	token = tc.authenticate()
	session, settings = tc._get_session()
	session.headers["Authorization"] = f"Bearer {token}"
	return session, settings.base_url.rstrip("/"), max(cint(settings.request_timeout) or 30, 90)


@frappe.whitelist(methods=["POST"])
def download_template(file_grp_uuid: Scalar = SIMPL_TEMPLATE_UUID):
	"""'Template Download': GET /ptl/api/v1/ptle/comn/files/{uuid} then POST .../download {fileGrpUuid, fileUuid}."""
	info = _get(f"/ptl/api/v1/ptle/comn/files/{file_grp_uuid}")
	rows = _content(info, "fileDtlInfoList") or []
	if not rows:
		frappe.throw(_("TANeSW has no template file for this screen."))
	f = rows[0]
	data = _post_binary(
		"/ptl/api/v1/ptle/comn/files/download",
		{"fileGrpUuid": f.get("fileGrpUuid"), "fileUuid": f.get("fileUuid")},
	)
	name, ext = f.get("fileNm") or "template", f.get("fileExt") or "xlsx"
	return {
		"filename": name if name.endswith("." + ext) else f"{name}.{ext}",
		"content": base64.b64encode(data).decode(),
	}


@frappe.whitelist(methods=["POST"])
def simpl_excel_upload(filename: Scalar, content: Scalar):
	"""'Excel Upload' on 0302-001Q: multipart POST {SIMPL}/excel/upload (file, fileNm, fileSize, url).
	TANeSW answers with a truncated JSON stream; the portal appends ']}' before parsing — so do we.
	Returns the validation messages (empty list = all declarations registered)."""
	import json

	tc.assert_write_operations_enabled()
	raw = base64.b64decode(content)
	session, base, timeout = _session()
	r = session.post(
		f"{base}{SIMPL}/excel/upload",
		files={"file": (filename, raw)},
		data={"fileNm": filename, "fileSize": str(len(raw)), "url": ""},
		timeout=timeout,
	)
	if r.status_code >= 400:
		tc._handle_tanesw_error(r, f"{SIMPL}/excel/upload")
	text = r.text or ""
	try:
		parsed = json.loads(text + "]}")
	except Exception:
		try:
			parsed = json.loads(text)
		except Exception:
			return {"messages": [], "raw": text[:500]}
	st = parsed.get("simpleTrsf") or []
	msgs = ((st[0].get("result") or {}).get("content") if st else None) or []
	return {"messages": msgs}


@frappe.whitelist(methods=["POST"])
def simpl_delete_many(dclr_nos: Scalar):
	"""'Delete' on 0302-001Q: DELETE {SIMPL}/{no1,no2,...} — registered rows only."""
	nos = [str(n).replace("-", "").strip() for n in _rows(dclr_nos) if n]
	if not nos:
		frappe.throw(_("Select declarations to delete"))
	return tc._authed_delete(f"{SIMPL}/{','.join(nos)}")


def _persist_transfer_allocation(payload, res):
	try:
		alloc_no = (res.get("dclrNo") if isinstance(res, dict) else None) or payload.get("dclrNo")
		if not alloc_no:
			return
		fields = {
			"declaration_no": payload.get("dclrNo") or alloc_no,
			"mrn": payload.get("mrn"),
			"crn": payload.get("crn"),
			"status": (res.get("prcssStatCd") if isinstance(res, dict) else None)
			or payload.get("prcssStatCd")
			or "SUBMITTED",
			"process_status_code": (res.get("prcssStatCd") if isinstance(res, dict) else None)
			or payload.get("prcssStatCd"),
			"place_of_departure": payload.get("dptrWrhsCd"),
			"place_of_destination": payload.get("arvlWrhsCd"),
			"transfer_start_date": payload.get("trsfStrtDt"),
			"transfer_end_date": payload.get("trsfEndDt"),
			"submission_response": frappe.as_json(res) if res else None,
		}
		if not frappe.db.exists("TANeSW Transfer Allocation", alloc_no):
			doc = frappe.get_doc(
				{"doctype": "TANeSW Transfer Allocation", "allocation_no": alloc_no, **fields}
			)
			for cntr in payload.get("trsfIcdCntrRList") or []:
				doc.append(
					"containers",
					{
						"container_no": cntr.get("cntrNo"),
						"container_size": cntr.get("cntrSizeCd"),
						"container_type": cntr.get("cntrTpCd"),
						"seal_no": cntr.get("sealNo"),
						"cargo_type": cntr.get("cargTpCd"),
						"status": cntr.get("prcssStatCd"),
					},
				)
			doc.insert()
		else:
			doc = frappe.get_doc("TANeSW Transfer Allocation", alloc_no)
			for k, v in fields.items():
				if v is not None:
					setattr(doc, k, v)
			doc.save()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- TANeSW has already accepted it: our copy must survive a later ERP error
	except Exception as e:
		frappe.clear_messages()  # TANeSW already accepted; only the ERPNext copy failed
		frappe.log_error(f"Error persisting Transfer Allocation: {e}")


def _persist_stripping_report(header, res):
	try:
		report_no = (res.get("rprtNo") if isinstance(res, dict) else None) or header.get("rprtNo")
		if not report_no:
			return
		fields = {
			"mrn": header.get("mrn"),
			"stripping_date": header.get("strpngDt"),
			"stripping_type": header.get("strpngRsltTpCd"),
			"warehouse_code": header.get("wrhsCd"),
			"status": (res.get("prcssStatCd") if isinstance(res, dict) else None)
			or header.get("prcssStatCd")
			or "SAVED",
			"process_status_code": (res.get("prcssStatCd") if isinstance(res, dict) else None)
			or header.get("prcssStatCd"),
			"supervisor_name": header.get("spvsrNm"),
			"officer_name": header.get("cstmsOffcrNm"),
			"remarks": header.get("rmrk"),
			"submission_response": frappe.as_json(res) if res else None,
		}
		if not frappe.db.exists("TANeSW Stripping Report", report_no):
			doc = frappe.get_doc({"doctype": "TANeSW Stripping Report", "report_no": report_no, **fields})
			doc.insert()
		else:
			doc = frappe.get_doc("TANeSW Stripping Report", report_no)
			for k, v in fields.items():
				if v is not None:
					setattr(doc, k, v)
			doc.save()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- TANeSW has already accepted it: our copy must survive a later ERP error
	except Exception as e:
		frappe.clear_messages()  # TANeSW already accepted; only the ERPNext copy failed
		frappe.log_error(f"Error persisting Stripping Report: {e}")


def _persist_carry_out(header, rows, res):
	try:
		cro_base_no = (
			(res.get("croBaseNo") if isinstance(res, dict) else None)
			or header.get("croBaseNo")
			or header.get("blNo")
		)
		if not cro_base_no:
			return
		row = rows[0] if (rows and isinstance(rows, list)) else {}
		fields = {
			"mrn": header.get("mrn") or row.get("mrn"),
			"crn": header.get("crn") or row.get("crn"),
			"warehouse_code": header.get("wrhsCd"),
			"status": (res.get("prcssStatCd") if isinstance(res, dict) else None)
			or header.get("prcssStatCd")
			or "SAVED",
			"process_status_code": (res.get("prcssStatCd") if isinstance(res, dict) else None)
			or header.get("prcssStatCd"),
			"vehicle_no": row.get("vhclNo") or header.get("vhclNo"),
			"trailer_no": row.get("trlrNo") or header.get("trlrNo"),
			"driver_name": row.get("drvrNm") or header.get("drvrNm"),
			"driver_license": row.get("drvrLcneNo") or header.get("drvrLcneNo"),
			"transporter_name": row.get("trspNm") or header.get("trspNm"),
			"transporter_tin": row.get("trspTin") or header.get("trspTin"),
			"container_no": row.get("cntrNo") or header.get("cntrNo"),
			"container_size": row.get("cntrSizeCd") or header.get("cntrSizeCd"),
			"seal_no": row.get("sealNo") or header.get("sealNo"),
			"package_count": row.get("croPckgNo") or header.get("croPckgNo"),
			"package_type": row.get("pckgUtCd") or header.get("pckgUtCd"),
			"weight": row.get("croWght") or header.get("croWght"),
			"cargo_description": row.get("godsDesc") or header.get("godsDesc"),
			"remarks": header.get("rmrk"),
			"submission_response": frappe.as_json(res) if res else None,
		}
		if not frappe.db.exists("TANeSW Carry Out", cro_base_no):
			doc = frappe.get_doc({"doctype": "TANeSW Carry Out", "cro_base_no": cro_base_no, **fields})
			doc.insert()
		else:
			doc = frappe.get_doc("TANeSW Carry Out", cro_base_no)
			for k, v in fields.items():
				if v is not None:
					setattr(doc, k, v)
			doc.save()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- TANeSW has already accepted it: our copy must survive a later ERP error
	except Exception as e:
		frappe.clear_messages()  # TANeSW already accepted; only the ERPNext copy failed
		frappe.log_error(f"Error persisting Carry Out: {e}")


def _cri_local_status(code):
	"""TANeSW Carry In.status only allows NOT REPORT / REPORTED / APPROVED (writing "SUBMITTED" or a raw
	code like A04 failed validation and popped a red "Status cannot be ..." message after a successful TANeSW submit)."""
	if code == "D06":
		return "APPROVED"
	return "REPORTED" if code else "NOT REPORT"


def _persist_carry_in(header, rows, res):
	try:
		rows = rows if isinstance(rows, list) else ([rows] if rows else [])
		row = rows[0] if rows else {}
		pb = (
			(res.get("criBaseNo") if isinstance(res, dict) else None)
			or header.get("criBaseNo")
			or row.get("dclrNo")
			or row.get("criBaseNo")
			or header.get("mrn")
		)
		if not pb:
			return
		tansad_no = header.get("tansadNo") or row.get("tansadNo")
		cntr_nos = [r.get("cntrNo") for r in rows if isinstance(r, dict) and r.get("cntrNo")]
		container_no = (
			", ".join(dict.fromkeys(cntr_nos)) if cntr_nos else (row.get("cntrNo") or header.get("cntrNo"))
		)
		tot_pckg = sum(cint(r.get("criPckgNo") or r.get("pckgNo") or 0) for r in rows if isinstance(r, dict))
		package_count = (
			tot_pckg if (len(rows) > 1 and tot_pckg > 0) else (row.get("criPckgNo") or row.get("pckgNo"))
		)
		tot_wght = sum(flt(r.get("criWght") or r.get("cntrWght") or 0) for r in rows if isinstance(r, dict))
		weight = tot_wght if (len(rows) > 1 and tot_wght > 0) else (row.get("criWght") or row.get("cntrWght"))
		fields = {
			"tansad_no": tansad_no,
			"mrn": header.get("mrn") or row.get("mrn"),
			"crn": header.get("crn") or row.get("crn"),
			"warehouse_code": header.get("wrhsCd") or legacy_facility_code(),
			"status": _cri_local_status(
				(res.get("prcssStatCd") if isinstance(res, dict) else None) or row.get("prcssStatCd")
			),
			"process_status_code": (res.get("prcssStatCd") if isinstance(res, dict) else None)
			or row.get("prcssStatCd"),
			"vehicle_no": row.get("vhclNo") or header.get("vhclNo"),
			"trailer_no": row.get("trlrNo") or header.get("trlrNo"),
			"driver_name": row.get("drvrNm") or header.get("drvrNm"),
			"driver_license": row.get("drvrLicNo") or row.get("drvrLcneNo"),
			"agent_tin": row.get("trspTin") or header.get("trspTin"),
			"agent_name": row.get("trspNm") or header.get("trspNm"),
			"container_no": container_no,
			"container_size": row.get("cntrSizeCd") or row.get("cntrSzCd"),
			"seal_no": row.get("sealNo1") or row.get("sealNo"),
			"seal_no_2": row.get("sealNo2"),
			"package_count": package_count,
			"package_type": row.get("pckgUtCd") or row.get("pckgTpCd"),
			"weight": weight,
			"cargo_description": row.get("godsDesc"),
			"discrepancy_remarks": row.get("rmrk") or header.get("rmrk"),
			"submission_response": frappe.as_json(res) if res else None,
		}
		if not frappe.db.exists("TANeSW Carry In", pb):
			doc = frappe.get_doc(
				{
					"doctype": "TANeSW Carry In",
					"cri_base_no": pb,
					**{k: v for k, v in fields.items() if v is not None},
				}
			)
			doc.flags.ignore_links = True
			doc.insert()
		else:
			doc = frappe.get_doc("TANeSW Carry In", pb)
			for k, v in fields.items():
				if v is not None:
					setattr(doc, k, v)
			doc.flags.ignore_links = True
			doc.save()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- TANeSW has already accepted it: our copy must survive a later ERP error
	except Exception as e:
		frappe.clear_messages()  # TANeSW already accepted; only the ERPNext copy failed
		frappe.log_error(f"Error persisting Carry In: {e}")
