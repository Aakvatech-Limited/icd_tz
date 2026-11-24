import base64
import concurrent.futures
import io

import frappe

from tanesw_integration.api_client import (
	BL_LIST_PATH,
	authenticate,
	get_approval_history,
	get_bl_containers,
	get_bl_list,
	get_booking_app_info,
	get_booking_approval_info,
	get_booking_detail,
	get_booking_list,
	get_carry_in_detail,
	get_carry_in_list,
	get_carry_out_containers,
	get_carry_out_detail,
	get_carry_out_list,
	get_crn_history,
	get_do_bl_info,
	get_do_list,
	get_inspection_results,
	get_manifest,
	get_manifest_excel,
	get_manifest_list,
	get_tin_no_list,
	modify_booking,
	plain_request_args,
	search_crn,
	search_transfers,
	submit_booking,
	submit_carry_out,
)
from tanesw_integration.api_client import (
	register_carry_in as client_register_carry_in,
)
from tanesw_integration.api_client import (
	save_booking_approval as client_save_booking_approval,
)
from tanesw_integration.api_client import (
	submit_booking_approval as client_submit_booking_approval,
)
from tanesw_integration.api_client import (
	submit_carry_in as client_submit_carry_in,
)
from tanesw_integration.credentials import assert_write_operations_enabled, require_tanesw_user
from tanesw_integration.hints import JSONish, Scalar
from tanesw_integration.outage import log_error as _outage_log_error


@frappe.whitelist(methods=["POST"])
def test_connection():
	"""Test TANeSW connection for current user. Returns token length (not the token)."""
	token = authenticate()
	return {"status": "ok", "token_length": len(token)}


# --- Facility (place of delivery) filtering ---
# ponytail: the TANeSW B/L endpoint has no server-side delivery-place filter
# (dlvrPlcCd / srchTp / blDlvrPlcCd are all ignored), so "our cargo" filtering pages the B/Ls and filters here.
FACILITY_SCAN_LIMIT = 25  # manifests scanned per filtered search window (cached)
MAX_BL_PAGES = 10  # 10,000 B/Ls per manifest ceiling
FACILITY_CACHE_TTL = 900


def _our_facility_code():
	from tanesw_integration.credentials import facility_code

	return facility_code()


def _bl_node(res):
	res = res if isinstance(res, dict) else {}
	return res.get("impMnfsBlLst") or res.get("impMnfsBlLstData") or {}


def _iter_bls(mrn):
	"""Yield every Master B/L of an MRN (1000 per call, capped at MAX_BL_PAGES)."""
	page = 0
	while page < MAX_BL_PAGES:
		node = _bl_node(get_bl_list(mrn, page, 1000))
		yield from node.get("content") or []
		if page + 1 >= ((node.get("page") or {}).get("totalPages") or 1):
			return
		page += 1


def _our_bls(mrn, code):
	return _ours(_iter_bls(mrn), code)


def _our_bl_summaries(mrns, code, workers=5):
	"""Our B/L summary per MRN: from the cache, else read from TANeSW.

	Several uncached MRNs are read in parallel by worker threads that ONLY send HTTP requests: no frappe context, so
	no database connection of their own (PR #714 review, item 27). Everything that touches the database or the cache --
	the login, filtering, caching, error logging, and the normal read path with its retries -- stays in this thread.
	An MRN a worker could not read is read again here the normal way."""
	mrns = [m for m in dict.fromkeys(mrns) if m]
	out, todo = {}, []
	for mrn in mrns:
		cached = _cached_summary(mrn, code)
		if cached:
			out[mrn] = cached
		else:
			todo.append(mrn)
	fetched = {}
	if len(todo) > 1:
		try:
			args = plain_request_args()
			with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(todo))) as pool:
				for mrn, rows in zip(todo, pool.map(_fetch_bl_rows, [args] * len(todo), todo), strict=False):
					fetched[mrn] = rows
		except Exception:
			frappe.clear_messages()  # the per-MRN reads below report the problem, once per MRN
	for mrn in todo:
		try:
			rows = fetched.get(mrn)
			bls = _ours(rows, code) if rows is not None else _our_bls(mrn, code)
			out[mrn] = _store_summary(mrn, code, bls)
		except Exception:
			_outage_log_error(title=f"TANeSW B/L scan failed: {mrn}", message=frappe.get_traceback())
			frappe.clear_messages()
			out[mrn] = {"scan_failed": 1}
	return out


def _fetch_bl_rows(args, mrn):
	"""Runs in a worker thread: HTTP only. Every B/L row of an MRN, or None on any problem (then it is read again the
	normal way in the request's thread)."""
	import requests

	base, headers, timeout, verify = args
	rows = []
	try:
		with requests.Session() as session:
			session.headers.update(headers)
			session.verify = verify
			for page in range(MAX_BL_PAGES):
				r = session.get(
					f"{base}{BL_LIST_PATH}",
					params={"mrn": mrn, "trptModeCd": "10", "page": page, "size": 1000},
					timeout=timeout,
				)
				if r.status_code != 200:
					return None
				node = _bl_node(r.json())
				rows.extend(node.get("content") or [])
				if page + 1 >= ((node.get("page") or {}).get("totalPages") or 1):
					break
	except Exception:
		return None
	return rows


def _ours(rows, code):
	return [row for row in rows if str(row.get("dlvrPlcCd") or "").strip().upper() == code]


def _cached_summary(mrn, code):
	try:
		return frappe.cache().get_value(f"tanesw:ourbl:{code}:{mrn}")
	except Exception:
		frappe.logger("tanesw_integration").exception("TANeSW cache unavailable")
		return None


def _store_summary(mrn, code, bls):
	summary = {
		"our_bl_count": len(bls),
		"our_cntr_count": sum(int(row.get("cntrCnt") or 0) for row in bls),
	}
	try:
		frappe.cache().set_value(f"tanesw:ourbl:{code}:{mrn}", summary, expires_in_sec=FACILITY_CACHE_TTL)
	except Exception:
		frappe.logger("tanesw_integration").exception("TANeSW cache unavailable")
	return summary


def _our_bl_summary(mrn, code):
	"""Counts of our B/Ls on one manifest, cached so list paging stays fast."""
	return _cached_summary(mrn, code) or _store_summary(mrn, code, _our_bls(mrn, code))


DECLARED_CACHE_TTL = 900
MAX_DECL_PAGES = 20  # 10,000 declarations per window
DECLARED_SCAN_LIMIT = 100  # manifests per upstream page when filtering by arrival
DECLARED_MAX_PAGES = 10  # 1,000 manifests per arrival window ceiling
DECLARED_WINDOW_PAD_DAYS = 60  # declarations are filed around the arrival date, not on it


def _arrival_of(row):
	"""Best available arrival date for a manifest row, as YYYY-MM-DD."""
	return str(row.get("actlArvlDt") or row.get("arvlXptdDt") or "")[:10]


def _declared_mrns(dt_from, dt_to):
	"""MRNs our ICD transfer declarations prove are ours, with per-MRN totals."""
	bucket = f"tanesw:declmrn:{dt_from}:{dt_to}"
	try:
		cached = frappe.cache().get_value(bucket)
		if cached:
			return cached
	except Exception:
		pass
	agg, page = {}, 0
	while page < MAX_DECL_PAGES:
		node = (search_transfers(None, dt_from, dt_to, page, 500) or {}).get("icdTrsfDclrLstData") or {}
		rows = node.get("content") or []
		for row in rows:
			mrn = row.get("mrn")
			if not mrn:
				continue
			entry = agg.setdefault(
				mrn, {"decl_count": 0, "containers": 0, "last_status": None, "last_prcss_dtm": ""}
			)
			entry["decl_count"] += 1
			entry["containers"] += int(str(row.get("cntrCnt") or "0").split("(")[0].strip() or 0)
			dtm = row.get("prcssDtm") or ""
			if dtm > entry["last_prcss_dtm"]:
				entry["last_prcss_dtm"] = dtm
				entry["last_status"] = row.get("prcssStatCd")
		if page + 1 >= ((node.get("page") or {}).get("totalPages") or 1):
			break
		page += 1
	try:
		frappe.cache().set_value(bucket, agg, expires_in_sec=DECLARED_CACHE_TTL)
	except Exception:
		frappe.logger("tanesw_integration").exception("TANeSW cache unavailable")
	return agg


def _manifest_header(mrn):
	bucket = f"tanesw:mnfhdr:{mrn}"
	try:
		cached = frappe.cache().get_value(bucket)
		if cached:
			return cached
	except Exception:
		cached = None
	try:
		res = get_manifest(mrn) or {}
		header = (res.get("impMnfsMrn") or {}).get("content") or res
	except Exception:
		header = {}
	header = header if isinstance(header, dict) else {}
	try:
		frappe.cache().set_value(bucket, header, expires_in_sec=3600)
	except Exception:
		frappe.logger("tanesw_integration").exception("TANeSW cache unavailable")
	return header


@frappe.whitelist(methods=["POST"])
def manifest_list(
	dt_from: Scalar | None = None,
	dt_to: Scalar | None = None,
	mrn: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
	only_our_facility: Scalar = 0,
	scan_page: Scalar = 0,
	source: Scalar = "scan",
):
	if not dt_from:
		dt_from = frappe.utils.today()
	if not dt_to:
		dt_to = frappe.utils.add_days(dt_from, 7)
	page, size = int(page), int(size)

	if not int(only_our_facility or 0):
		data = get_manifest_list(dt_from, dt_to, mrn, page, size).get("impMnfsLst", {})
		return {
			"content": data.get("content") or [],
			"page": data.get("page") or {"number": page, "size": size, "totalElements": 0, "totalPages": 0},
			"facility_code": None,
			"scanned": 0,
			"scan_offset": 0,
			"total_manifests": 0,
			"has_more": False,
		}

	code = _our_facility_code()

	if source == "all":
		# Allocation ground truth: walk the B/Ls of every manifest arriving in the
		# window and keep ours (dlvrPlcCd == facility). Declaration evidence is
		# attached as a second, independent signal — the two can disagree, and that
		# disagreement is the useful part.
		declared = _declared_mrns(
			frappe.utils.add_days(dt_from, -DECLARED_WINDOW_PAD_DAYS),
			frappe.utils.add_days(dt_to, DECLARED_WINDOW_PAD_DAYS),
		)
		if mrn and mrn.strip():
			declared = {k: v for k, v in declared.items() if k == mrn.strip()}

		rows, scan_page, total_pages = [], 0, 1
		while scan_page < DECLARED_MAX_PAGES:
			node = (get_manifest_list(dt_from, dt_to, mrn, scan_page, DECLARED_SCAN_LIMIT) or {}).get(
				"impMnfsLst"
			) or {}
			rows.extend(node.get("content") or [])
			total_pages = int((node.get("page") or {}).get("totalPages") or 1)
			scan_page += 1
			if scan_page >= total_pages:
				break

		summaries = _our_bl_summaries([r.get("mrn") for r in rows], code)

		out = []
		for row in rows:
			summ = summaries.get(row.get("mrn")) or {}
			agg = declared.get(row.get("mrn")) or {}
			bl_count = int(summ.get("our_bl_count") or 0)
			decl_count = int(agg.get("decl_count") or 0)
			if not bl_count and not decl_count:
				continue
			item = dict(row)
			item["actlArvlDt"] = _arrival_of(row)
			item["our_bl_count"] = bl_count
			item["our_cntr_count"] = int(summ.get("our_cntr_count") or 0)
			item["decl_count"] = decl_count
			item["declared_containers"] = int(agg.get("containers") or 0)
			item["last_status"] = agg.get("last_status")
			item["last_prcss_dtm"] = agg.get("last_prcss_dtm")
			item["allocated"] = 1 if bl_count else 0
			item["declared"] = 1 if decl_count else 0
			out.append(item)

		out.sort(key=lambda r: (r.get("actlArvlDt") or "", r.get("mrn") or ""), reverse=True)
		total = len(out)
		return {
			"content": out[page * size : (page + 1) * size],
			"page": {
				"number": page,
				"size": size,
				"totalElements": total,
				"totalPages": (total + size - 1) // size if total else 0,
			},
			"facility_code": code,
			"scanned": len(rows),
			"scan_offset": 0,
			"total_manifests": total,
			"has_more": False,
			"source": "all",
			"dt_from": dt_from,
			"dt_to": dt_to,
		}

	if source == "declared":
		# The window is a VESSEL ARRIVAL window: TANeSW filters the manifest list by
		# arrival date, and we intersect it with MRNs our declarations prove are ours.
		# Declarations themselves are scanned over a padded window because they are
		# filed around the arrival date, not on it.
		declared = _declared_mrns(
			frappe.utils.add_days(dt_from, -DECLARED_WINDOW_PAD_DAYS),
			frappe.utils.add_days(dt_to, DECLARED_WINDOW_PAD_DAYS),
		)
		if mrn and mrn.strip():
			wanted = {mrn.strip()}
			declared = {k: v for k, v in declared.items() if k in wanted}

		out, scan_page, total_pages = [], 0, 1
		while scan_page < DECLARED_MAX_PAGES:
			node = (get_manifest_list(dt_from, dt_to, mrn, scan_page, DECLARED_SCAN_LIMIT) or {}).get(
				"impMnfsLst"
			) or {}
			batch = node.get("content") or []
			meta = node.get("page") or {}
			total_pages = int(meta.get("totalPages") or 1)
			for row in batch:
				agg = declared.get(row.get("mrn"))
				if not agg:
					continue
				item = dict(row)
				item["actlArvlDt"] = _arrival_of(row)
				item["decl_count"] = agg.get("decl_count")
				item["our_cntr_count"] = agg.get("containers")
				item["last_status"] = agg.get("last_status")
				item["last_prcss_dtm"] = agg.get("last_prcss_dtm")
				out.append(item)
			scan_page += 1
			if scan_page >= total_pages:
				break

		out.sort(key=lambda r: (r.get("actlArvlDt") or "", r.get("mrn") or ""), reverse=True)
		total = len(out)
		return {
			"content": out[page * size : (page + 1) * size],
			"page": {
				"number": page,
				"size": size,
				"totalElements": total,
				"totalPages": (total + size - 1) // size if total else 0,
			},
			"facility_code": code,
			"scanned": total,
			"scan_offset": 0,
			"total_manifests": total,
			"has_more": False,
			"source": "declared",
			"dt_from": dt_from,
			"dt_to": dt_to,
		}

	scan_page = max(0, int(scan_page or 0))
	res = get_manifest_list(dt_from, dt_to, mrn, scan_page, FACILITY_SCAN_LIMIT)
	node = res.get("impMnfsLst") or {}
	rows = node.get("content") or []
	meta = node.get("page") or {}

	scanned = []
	for row in rows:
		row = dict(row)
		row.update(_our_bl_summary(row.get("mrn"), code))
		scanned.append(row)

	total_manifests = int(meta.get("totalElements") or len(rows))
	total_scan_pages = int(meta.get("totalPages") or 1)
	return {
		"content": [row for row in scanned if row.get("our_bl_count")],
		"page": {
			"number": scan_page,
			"size": FACILITY_SCAN_LIMIT,
			"totalElements": total_manifests,
			"totalPages": total_scan_pages,
		},
		"facility_code": code,
		"scanned": len(scanned),
		"scan_offset": scan_page * FACILITY_SCAN_LIMIT,
		"total_manifests": total_manifests,
		"has_more": scan_page + 1 < total_scan_pages,
		"source": "scan",
	}


@frappe.whitelist(methods=["POST"])
def manifest(mrn: Scalar):
	res = get_manifest(mrn)
	header = res.get("impMnfsMrn", {}).get("content") or res
	if isinstance(header, dict):
		header.setdefault("vsslNm", header.get("vsslNm") or header.get("vslNm") or "")
		header.setdefault("vyg", header.get("vygNo") or header.get("vyg") or "")
		header.setdefault("clsgn", header.get("csgn") or header.get("clsgn") or "")
		header.setdefault("arvlDt", header.get("actlArvlDt") or header.get("arvlXptdDt") or "")
		header.setdefault("stsCd", header.get("prcssStatCd") or header.get("stsCd") or "")
		header.setdefault("carrNm", header.get("carrNm") or "")
		header.setdefault("totMblCnt", header.get("totMblCnt") or 0)
		header.setdefault("totCntrCnt", header.get("totCntrCnt") or 0)
	return header


@frappe.whitelist(methods=["POST"])
def manifest_detail(mrn: Scalar, page: Scalar = 0, size: Scalar = 10, only_our_facility: Scalar = 0):
	page, size = int(page), int(size)
	header_res = get_manifest(mrn)
	header = header_res.get("impMnfsMrn", {}).get("content") or header_res
	code = _our_facility_code()

	if int(only_our_facility or 0):
		bls = _our_bls(mrn, code)
		total = len(bls)
		return {
			"manifest": header if isinstance(header, dict) else {},
			"content": bls[page * size : (page + 1) * size],
			"page": {
				"number": page,
				"size": size,
				"totalElements": total,
				"totalPages": (total + size - 1) // size if total else 0,
			},
			"facility_code": code,
			"our_bl_count": total,
			"our_cntr_count": sum(int(row.get("cntrCnt") or 0) for row in bls),
		}

	bl_data = _bl_node(get_bl_list(mrn, page, size))
	return {
		"manifest": header if isinstance(header, dict) else {},
		"content": bl_data.get("content") or [],
		"page": bl_data.get("page") or {"number": page, "size": size, "totalElements": 0, "totalPages": 0},
		"facility_code": code,
		"our_bl_count": None,
		"our_cntr_count": None,
	}


@frappe.whitelist(methods=["POST"])
def bl_list(mrn: Scalar, page: Scalar = 0, size: Scalar = 50):
	try:
		res = get_bl_list(mrn, int(page), int(size))
		items = (
			res.get("impMnfsBlLst", {}).get("content")
			or res.get("content")
			or (res if isinstance(res, list) else [])
		)
		if items:
			return items
	except Exception:
		items = []

	# Fallback: parse official manifest Excel workbook
	try:
		import openpyxl

		raw = get_manifest_excel(mrn)
		wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True)
		if "Master BL List (4)" in wb.sheetnames:
			sheet = wb["Master BL List (4)"]
			excel_items = []
			for i, row in enumerate(sheet.iter_rows(values_only=True)):
				if i < 3:
					continue
				if not row or not row[0]:
					continue
				excel_items.append(
					{
						"mblNo": str(row[0]),
						"csgneNm": str(row[30] or "")[:50],
						"pkgCnt": str(row[9] or ""),
						"wgt": str(row[11] or ""),
						"cntrCnt": str(row[7] or ""),
					}
				)
			p = int(page)
			s = int(size)
			return excel_items[p * s : (p + 1) * s] if s > 0 else excel_items
	except Exception:
		pass

	return items


@frappe.whitelist(methods=["POST"])
def bl_containers(mrn: Scalar, page: Scalar = 0, size: Scalar = 50):
	res = get_bl_containers(mrn, int(page), int(size))
	return (
		res.get("impMnfsBl", {}).get("content")
		or res.get("content")
		or (res if isinstance(res, list) else [])
	)


@frappe.whitelist(methods=["POST"])
def download_manifest_excel(mrn: Scalar):
	"""Download 5-sheet official manifest workbook as base64 for client download."""
	raw = get_manifest_excel(mrn)
	return {
		"filename": f"Manifest_{mrn}.xlsx",
		"content_base64": base64.b64encode(raw).decode("utf-8"),
		"size": len(raw),
	}


@frappe.whitelist(methods=["POST"])
def manifest_lookup(mrn: str) -> dict:
	"""Fetch complete 5-tab manifest particulars matching TANeSW screen UI-CGM-0101-002S."""
	if not mrn:
		return {"found": False, "error": "MRN is required"}

	header = {}
	try:
		header = manifest(mrn)
	except Exception:
		_outage_log_error(title=f"TANeSW: manifest {mrn} header not read")

	import io

	import openpyxl

	result = {
		"found": True,
		"mrn": mrn,
		"manifest": header,
		"general": {},
		"bls": [],
		"containers": [],
		"split_consignments": [],
		"hbls": [],
	}

	try:
		raw = get_manifest_excel(mrn)
		if raw:
			wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)

			for sname in wb.sheetnames:
				s_lower = sname.strip().lower()
				all_rows = list(wb[sname].iter_rows(values_only=True))
				if not all_rows:
					continue

				hdr_idx = -1
				for idx, r in enumerate(all_rows[:5]):
					non_empty = [c for c in r if c is not None and str(c).strip()]
					if len(non_empty) >= 2:
						hdr_idx = idx
						break

				if hdr_idx == -1 or hdr_idx >= len(all_rows) - 1:
					continue

				hdrs = [str(h or "").strip().lower() for h in all_rows[hdr_idx]]
				data_rows = all_rows[hdr_idx + 1 :]

				# 1. MRN Detail / General
				if "mrn detail" in s_lower or "general" in s_lower:
					if data_rows:
						result["general"] = dict(zip(hdrs, data_rows[0], strict=False))

				# 2. Master BL List
				elif "master bl" in s_lower or "bill of lading" in s_lower:
					for r in data_rows:
						if any(r):
							rd = dict(zip(hdrs, r, strict=False))
							bl_no = (
								rd.get("m b/l no") or rd.get("b/l no.") or rd.get("b/l no") or rd.get("bl no")
							)
							if bl_no and str(bl_no).strip():
								result["bls"].append(
									{
										"no": len(result["bls"]) + 1,
										"blNo": str(bl_no).strip(),
										"polCd": rd.get("port of loading") or rd.get("pol") or "",
										"podCd": rd.get("place of destination") or rd.get("pod") or "TZDAR",
										"pckgQty": int(
											float(rd.get("package") or rd.get("number of container") or 0)
										),
										"grossMass": float(
											rd.get("gross weight") or rd.get("gross mass") or 0
										),
										"cnsgNm": rd.get("consignee name")
										or rd.get("place of delivery")
										or "",
										"goodsDesc": rd.get("description of goods")
										or rd.get("goods description")
										or "",
										"cargoType": rd.get("type") or rd.get("cargo type") or "",
										"freightIndicator": rd.get("b/l type")
										or rd.get("freight indicator")
										or "FCL",
										"stsCd": "Approved",
									}
								)

				# 3. Container
				elif "container" in s_lower and "hbl" not in s_lower:
					for r in data_rows:
						if any(r):
							rd = dict(zip(hdrs, r, strict=False))
							cntr_no = (
								rd.get("container no / chassis no")
								or rd.get("container no.")
								or rd.get("container no")
								or rd.get("container/trailer/vehicle/wagon reg no")
							)
							if cntr_no and str(cntr_no).strip():
								result["containers"].append(
									{
										"no": len(result["containers"]) + 1,
										"cntrNo": str(cntr_no).strip(),
										"cntrSzTpCd": rd.get("container size")
										or rd.get("size/type")
										or rd.get("size and type")
										or "",
										"sealNo1": str(
											rd.get("seal no#1")
											or rd.get("seal no. 1")
											or rd.get("seal no 1")
											or ""
										).strip(),
										"sealNo2": str(
											rd.get("seal no#2")
											or rd.get("seal no. 2")
											or rd.get("seal no 2")
											or ""
										).strip(),
										"blNo": str(
											rd.get("m b/l no") or rd.get("b/l no.") or rd.get("b/l no") or ""
										).strip(),
										"grossMass": float(
											rd.get("gross weight") or rd.get("gross mass") or 0
										),
										"pckgQty": int(float(rd.get("package") or rd.get("packages") or 1)),
									}
								)

				# 4. House BL List
				elif "house bl" in s_lower or "house b/l" in s_lower:
					for r in data_rows:
						if any(r):
							rd = dict(zip(hdrs, r, strict=False))
							hbl_no = (
								rd.get("h b/l no")
								or rd.get("house b/l no.")
								or rd.get("house b/l no")
								or rd.get("hbl no")
							)
							if hbl_no and str(hbl_no).strip():
								result["hbls"].append(
									{
										"no": len(result["hbls"]) + 1,
										"mblNo": str(
											rd.get("m b/l no") or rd.get("master b/l") or ""
										).strip(),
										"hblNo": str(hbl_no).strip(),
										"polCd": rd.get("pol") or "",
										"podCd": rd.get("place of destination") or rd.get("pod") or "TZDAR",
										"pckgQty": int(
											float(rd.get("number of container") or rd.get("package") or 0)
										),
										"grossMass": float(
											rd.get("net weight")
											or rd.get("gross weight")
											or rd.get("gross mass")
											or 0
										),
										"goodsDesc": rd.get("description of goods")
										or rd.get("goods description")
										or "",
										"cnsgNm": rd.get("consignee name") or "",
									}
								)
	except Exception as e:
		frappe.log_error(f"Error parsing manifest excel: {e}")

	return result


@frappe.whitelist(methods=["POST"])
def tracking_search(
	search_type: Scalar | None = None,
	search_no: Scalar | None = None,
	srch_cntr_no: Scalar | None = None,
	srch_bl_no: Scalar | None = None,
):
	res = search_crn(
		search_type=search_type, search_no=search_no, srch_cntr_no=srch_cntr_no, srch_bl_no=srch_bl_no
	)
	cnt = res.get("trkngDtl", {}).get("content") or res
	if isinstance(cnt, dict):
		s_no = srch_cntr_no or search_no or ""
		cnt.setdefault("cntrNo", s_no)
		cnt.setdefault("blNo", cnt.get("mblNo") or cnt.get("blNo") or "")
		cnt.setdefault("lctnNm", cnt.get("lastGodsLoctCdNm") or cnt.get("dlvrPlcCdNm") or "")
		cnt.setdefault("stsCd", cnt.get("cagTrkngPrcssCdNm") or cnt.get("cagTrkngPrcssCd") or "")
		return [cnt]
	return res if isinstance(res, list) else [res]


@frappe.whitelist(methods=["POST"])
def tracking_history(crn: Scalar):
	res = get_crn_history(crn)
	cnt = res.get("trkngDtl", {}).get("content") or res
	events = []
	if isinstance(cnt, dict):
		raw_events = cnt.get("blPrcssLst") or []
		for ev in raw_events:
			events.append(
				{
					"evntNm": ev.get("cagTrkngPrcssCdNm") or ev.get("cagTrkngPrcssCd"),
					"prcssNm": ev.get("cagTrkngPrcssCdNm") or ev.get("cagTrkngPrcssCd"),
					"evntDt": ev.get("prcssDt") or ev.get("crioDt"),
					"prcssDt": ev.get("prcssDt") or ev.get("crioDt"),
					"lctnNm": ev.get("wrhsCdNm") or ev.get("wrhsCd") or ev.get("dstnWrhsCdNm") or "",
					"rmrk": ev.get("dclrNo") or ev.get("reffNo") or "",
					"crioTpCdNm": ev.get("crioTpCdNm") or "",
					"opTpNm": ev.get("crioTpCdNm") or "",
				}
			)
	return {"trkngList": events, "raw": cnt}


@frappe.whitelist(methods=["POST"])
def carry_in_list(
	dt_from: Scalar | None = None,
	dt_to: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 50,
	report_status: Scalar = "N,P,Y",
	container_no: Scalar | None = None,
	crn: Scalar | None = None,
):
	if not dt_from:
		dt_from = frappe.utils.add_days(frappe.utils.today(), -30)
	if not dt_to:
		dt_to = frappe.utils.today()
	res = get_carry_in_list(dt_from, dt_to, int(page), int(size), report_status, container_no, crn)
	items = (
		res.get("wrhsCriList", {}).get("content")
		or res.get("content")
		or (res if isinstance(res, list) else [])
	)
	for it in items:
		if isinstance(it, dict):
			it.setdefault("criDt", it.get("aprvDt", ""))
			it.setdefault("stsCd", it.get("rptStatNm", ""))
			it.setdefault("wrhsNm", it.get("wrhsCd", ""))
	if isinstance(res, dict) and "wrhsCriList" in res and "page" in res["wrhsCriList"]:
		return {"content": items, "page": res["wrhsCriList"]["page"]}
	return items


@frappe.whitelist(methods=["POST"])
def carry_in_detail(crn: Scalar, wrhs_cd: Scalar, cri_base_no: Scalar):
	res = get_carry_in_detail(crn, wrhs_cd, cri_base_no)
	return res.get("wrhsCriImp", {}).get("content") or res


@frappe.whitelist(methods=["POST"])
def carry_out_list(
	dt_from: Scalar | None = None, dt_to: Scalar | None = None, page: Scalar = 0, size: Scalar = 50
):
	if not dt_from:
		dt_from = frappe.utils.add_days(frappe.utils.today(), -30)
	if not dt_to:
		dt_to = frappe.utils.today()
	res = get_carry_out_list(dt_from, dt_to, int(page), int(size))
	items = (
		res.get("wrhsCroList", {}).get("content")
		or res.get("content")
		or (res if isinstance(res, list) else [])
	)
	for it in items:
		if isinstance(it, dict):
			it.setdefault("croDt", it.get("aprvDt", ""))
			it.setdefault("stsCd", it.get("rptStatNm", ""))
			it.setdefault("wrhsNm", it.get("wrhsCd", ""))
	return items


@frappe.whitelist(methods=["POST"])
def carry_out_detail(cro_base_no: Scalar):
	res = get_carry_out_detail(cro_base_no)
	return res.get("wrhsCro") or res


@frappe.whitelist(methods=["POST"])
def carry_out_containers(cro_base_no: Scalar):
	res = get_carry_out_containers(cro_base_no)
	return res.get("wrhsCroCntrs") or res.get("content") or res


@frappe.whitelist(methods=["POST"])
def booking_list(
	dt_from: Scalar | None = None,
	dt_to: Scalar | None = None,
	wrhs_cd: Scalar | None = None,
	page: Scalar = 0,
	size: Scalar = 10,
	tansad_no: Scalar | None = None,
	reference_no: Scalar | None = None,
	status: Scalar | None = None,
):
	if not dt_from:
		dt_from = frappe.utils.add_days(frappe.utils.today(), -30)
	if not dt_to:
		dt_to = frappe.utils.today()
	res = get_booking_list(
		dt_from,
		dt_to,
		wrhs_cd,
		int(page),
		int(size),
		tansad_no=tansad_no,
		reference_no=reference_no,
		status=status,
	)
	container = res.get("jntInscBkngList", {}) if isinstance(res, dict) else {}
	items = container.get("content") or res.get("content") or (res if isinstance(res, list) else [])
	for it in items:
		if isinstance(it, dict):
			it["referenceNo"] = "-".join(
				x for x in [it.get("reffTin"), it.get("reffYy"), it.get("reffSrno")] if x
			)
	return {
		"content": items,
		"page": container.get("page")
		or {"size": int(size), "number": int(page), "totalElements": len(items), "totalPages": 1},
	}


@frappe.whitelist(methods=["POST"])
def booking_detail(tansad_no: Scalar):
	res = get_booking_detail(tansad_no)
	data = res.get("result", {}).get("content") or res
	if not isinstance(data, dict):
		data = {"raw": data}
	try:
		app_bkng = get_booking_app_info(tansad_no)
		if isinstance(app_bkng, dict) and "appBkngInfo" in app_bkng:
			data["appBkngInfo"] = app_bkng["appBkngInfo"].get("content", {})
	except Exception:
		_outage_log_error(title=f"TANeSW: booking {tansad_no} extra info not read")
	try:
		app_aprv = get_booking_approval_info(tansad_no)
		if isinstance(app_aprv, dict) and "appAprvInfo" in app_aprv:
			data["appAprvInfo"] = app_aprv["appAprvInfo"].get("content", {})
	except Exception:
		_outage_log_error(title=f"TANeSW: booking {tansad_no} extra info not read")
	return data


@frappe.whitelist(methods=["POST"])
def inspection_results(tansad_no: Scalar, page: Scalar = 0, size: Scalar = 10):
	"""Kept for old callers; TANeSW only searches results by TANSAD."""
	res = get_inspection_results(tansad_no, int(page), int(size))
	return (
		res.get("jntInscRsltList", {}).get("content")
		or res.get("content")
		or (res if isinstance(res, list) else [])
	)


@frappe.whitelist(methods=["POST"])
def do_bl_info(crn: Scalar):
	try:
		return get_do_bl_info(crn)
	except Exception as e:
		return {"error": str(e), "content": None}


@frappe.whitelist(methods=["POST"])
def do_list(crn: Scalar | None = None, page: Scalar = 0, size: Scalar = 50):
	try:
		return get_do_list(crn=crn, page=page, size=size)
	except Exception as e:
		return {"error": str(e), "content": []}


# --- Guarded write endpoints ---


@frappe.whitelist(methods=["POST"])
def register_carry_in(payload: JSONish):
	assert_write_operations_enabled()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	res = client_register_carry_in(payload)
	try:
		cri_base_no = payload.get("criBaseNo")
		if cri_base_no:
			import_carry_in_record(cri_base_no, data=payload)
	except Exception:
		# TANeSW has the carry-in; only the ERP copy failed. Leave a trace so it can be re-imported.
		_outage_log_error(title=f"TANeSW: carry-in {payload.get('criBaseNo')} sent, ERP record not saved")
	return res


@frappe.whitelist(methods=["POST"])
def submit_carry_in(payload: JSONish):
	assert_write_operations_enabled()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	res = client_submit_carry_in(payload)
	try:
		cri_base_no = payload.get("criBaseNo")
		if cri_base_no:
			import_carry_in_record(cri_base_no, data=payload)
	except Exception:
		# TANeSW has the carry-in; only the ERP copy failed. Leave a trace so it can be re-imported.
		_outage_log_error(title=f"TANeSW: carry-in {payload.get('criBaseNo')} sent, ERP record not saved")
	return res


submit_carry_in_report = submit_carry_in


@frappe.whitelist(methods=["POST"])
def submit_carry_out_report(payload: JSONish):
	assert_write_operations_enabled()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	return submit_carry_out(payload)


@frappe.whitelist(methods=["POST"])
def submit_inspection_booking(payload: JSONish):
	assert_write_operations_enabled()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	return submit_booking(payload)


@frappe.whitelist(methods=["POST"])
def modify_inspection_booking(payload: JSONish):
	assert_write_operations_enabled()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	return modify_booking(payload)


@frappe.whitelist(methods=["POST"])
def save_booking_approval_result(payload: JSONish):
	assert_write_operations_enabled()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	return client_save_booking_approval(payload)


@frappe.whitelist(methods=["POST"])
def submit_booking_approval_result(payload: JSONish):
	assert_write_operations_enabled()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	return client_submit_booking_approval(payload)


@frappe.whitelist(methods=["POST"])
def tin_no_list(tin_no: Scalar = ""):
	try:
		res = get_tin_no_list(tin_no)
		return res.get("tinNoList", {}).get("content", []) or res
	except Exception:
		return []


@frappe.whitelist(methods=["POST"])
def validate_carry_in_container(wrhs_cd: Scalar, cntr_no: Scalar, crn: Scalar = ""):
	try:
		from tanesw_integration.api_client import validate_carry_in_container as _val

		return _val(wrhs_cd, cntr_no, crn)
	except Exception as e:
		return {"error": str(e)}


@frappe.whitelist(methods=["POST"])
def sync_declaration(tansad_no: Scalar):
	require_tanesw_user()
	doc = frappe.get_doc("TANeSW Declaration", tansad_no)
	return doc.sync_from_tanesw()


@frappe.whitelist(methods=["POST"])
def import_declaration_from_tansad(tansad_no: Scalar):
	"""Import or update a TANeSW Declaration record from TANSAD number."""
	require_tanesw_user()
	if not frappe.db.exists("TANeSW Declaration", tansad_no):
		doc = frappe.get_doc(
			{
				"doctype": "TANeSW Declaration",
				"tansad_no": tansad_no,
			}
		)
		doc.insert()
	else:
		doc = frappe.get_doc("TANeSW Declaration", tansad_no)
	return doc.sync_from_tanesw()


@frappe.whitelist(methods=["POST"])
def import_carry_in_record(cri_base_no: Scalar, **kwargs):
	"""Import or update a Carry-In record with full particulars from TANeSW data."""
	require_tanesw_user()
	data = kwargs.get("data")
	if isinstance(data, str):
		try:
			data = frappe.parse_json(data)
		except Exception:
			data = {}
	elif not isinstance(data, dict):
		data = {}

	tansad_no = kwargs.get("tansad_no") or data.get("tansadNo") or data.get("dclrNo")
	fields = {
		"tansad_no": tansad_no,
		"crn": kwargs.get("crn") or data.get("crn"),
		"mrn": kwargs.get("mrn") or data.get("mrn"),
		"warehouse_code": kwargs.get("wrhs_cd")
		or data.get("wrhsCd")
		or data.get("wrhsNm")
		or _our_facility_code(),
		"status": kwargs.get("status") or data.get("stsCd") or "NOT REPORT",
		"vehicle_no": kwargs.get("vehicle_no") or data.get("vhclNo"),
		"trailer_no": kwargs.get("trailer_no") or data.get("trlrNo"),
		"arrival_date": kwargs.get("arrival_date")
		or data.get("criDt")
		or data.get("arvlDt")
		or frappe.utils.now(),
		"driver_name": kwargs.get("driver_name") or data.get("drvrNm"),
		"driver_license": kwargs.get("driver_license") or data.get("drvrLicNo"),
		"agent_tin": kwargs.get("agent_tin") or data.get("trspTin") or data.get("agentTin"),
		"agent_name": kwargs.get("agent_name") or data.get("trspNm") or data.get("agentNm"),
		"container_no": kwargs.get("cntr_no") or data.get("cntrNo"),
		"container_size": kwargs.get("container_size") or data.get("cntrSizeCd") or data.get("cntrSzCd"),
		"seal_no": kwargs.get("seal_no") or data.get("sealNo1") or data.get("sealNo"),
		"seal_no_2": kwargs.get("seal_no_2") or data.get("sealNo2"),
		"package_count": kwargs.get("package_count") or data.get("criXptdPckgNo") or data.get("pckgNo"),
		"package_type": kwargs.get("package_type") or data.get("pckgUtCd") or data.get("pckgTpCd"),
		"weight": kwargs.get("weight") or data.get("criXptdWght") or data.get("cntrWght"),
		"cargo_description": kwargs.get("cargo_description") or data.get("godsDesc"),
		"discrepancy_remarks": kwargs.get("discrepancy_remarks") or data.get("rmrk"),
		"submission_response": frappe.as_json(data) if data else None,
	}

	# If tansad is provided, link and sync declaration
	if tansad_no:
		try:
			import_declaration_from_tansad(tansad_no)
		except Exception:
			_outage_log_error(title=f"TANeSW: declaration {tansad_no} not imported")

	if not frappe.db.exists("TANeSW Carry In", cri_base_no):
		doc = frappe.get_doc(
			{
				"doctype": "TANeSW Carry In",
				"cri_base_no": cri_base_no,
				**{k: v for k, v in fields.items() if v is not None},
			}
		)
		doc.insert()
	else:
		doc = frappe.get_doc("TANeSW Carry In", cri_base_no)
		for k, v in fields.items():
			if v is not None:
				setattr(doc, k, v)
		doc.save()
	return {"status": "ok", "name": doc.name}


@frappe.whitelist(methods=["POST"])
def import_booking_record(tansad_no: Scalar):
	"""Import a Joint Inspection Booking with full details and PGAs from TANeSW into ERPNext."""
	require_tanesw_user()
	detail = booking_detail(tansad_no)
	bkng = detail.get("jntInscBkngInfo") or {}
	bl = detail.get("blInfo") or {}
	tansad_info = detail.get("tansadInfo") or {}
	cntrs = detail.get("cntrInfo") or detail.get("jntInscCntrInfo") or []

	# Ensure declaration exists
	try:
		import_declaration_from_tansad(tansad_no)
	except Exception:
		_outage_log_error(title=f"TANeSW: declaration {tansad_no} not imported")

	# RKM0019: A Received, B Approved, C Confirmed, D Submitted, E Rejected,
	# F Returned, G Re-submit, H Re-submitted, I Inspected
	code = bkng.get("prcsStatCd")
	status_val = {"B": "Approved", "C": "Approved", "I": "Approved", "E": "Rejected", "F": "Rejected"}.get(
		code, "Requested"
	)
	fields = {
		"declaration_record": tansad_no if frappe.db.exists("TANeSW Declaration", tansad_no) else None,
		"booking_request_date": bkng.get("bkngRqstDt"),
		"booking_approval_datetime": bkng.get("bkngAprvDtm"),
		"process_status_code": code,
		"status": status_val,
		"warehouse_code": bkng.get("mdfyGodsLoctWrhsCd")
		or bkng.get("godsLoctWrhsCd")
		or tansad_info.get("godsLoctReffCn"),
		"customs_office": tansad_no[:4],
		"consignee_tin": tansad_info.get("tin"),
		"consignee_name": tansad_info.get("coNm"),
		"company_name": tansad_info.get("dcltNm") or bkng.get("coNm"),
		"bl_no": bkng.get("blNo") or tansad_info.get("blNo"),
		"container_count": bkng.get("cntrCnt") if bkng.get("cntrCnt") is not None else len(cntrs),
		"cargo_type": bkng.get("cntrLstCn"),
		"goods_description": bl.get("godsDesc"),
		"raw_response": frappe.as_json(detail),
	}

	if not frappe.db.exists("TANeSW Inspection Booking", tansad_no):
		doc = frappe.get_doc({"doctype": "TANeSW Inspection Booking", "tansad_no": tansad_no, **fields})
	else:
		doc = frappe.get_doc("TANeSW Inspection Booking", tansad_no)
		for k, v in fields.items():
			if v is not None:
				setattr(doc, k, v)

	# Participating agencies = TANeSW approval history (003S 'Approval History' tab)
	try:
		hist = get_approval_history(tansad_no)
		rows = (hist.get("aprvHistList") or {}).get("content") or []
	except Exception:
		frappe.clear_messages()
		rows = None
	if rows is not None:
		doc.set("participating_agencies", [])
		for h in rows:
			doc.append(
				"participating_agencies",
				{
					"agency_code": h.get("orgCd"),
					"agency_name": h.get("orgNm") or h.get("orgCd"),
					"inspection_status": h.get("prcssStatNm") or h.get("prcssStatCd"),
					"officer_name": h.get("asnmtOfcrTpNm") or h.get("asnmtOfcrTpCd"),
					"action_date": h.get("prcssDtm"),
					"findings_remarks": "\n".join(x for x in [h.get("prcssCn"), h.get("rmrk")] if x),
				},
			)

	doc.save()
	return {"status": "ok", "name": doc.name}
