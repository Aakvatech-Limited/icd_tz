import frappe
import requests
from frappe.utils import getdate

TRACKING_URL = "https://tanesw.tra.go.tz/api/cgm/api/v1/cgme/trkng"
REQUEST_TIMEOUT = 15


def get_discharge_date(container_no, m_bl_no):
	"""Actual discharge date of a container, taken from the TANeSW cargo tracking API"""

	# a container number is reused across voyages, the B/L is what pins down the shipment
	if not m_bl_no:
		return None

	cargo = call_tracking_api("srch", {"srchBlNo": m_bl_no})
	if not cargo:
		return None

	cargo_rows = get_rows(cargo.get("trkngDtl"))

	discharge_date = find_container_date(cargo_rows, container_no)
	if discharge_date:
		return discharge_date

	for crn in {row.get("crn") for row in cargo_rows if row.get("crn") and not row.get("blCntrLst")}:
		detail = call_tracking_api("cntr-dtl", {"srchCrn": crn, "srchCntrNo": container_no})

		discharge_date = find_container_date(get_rows((detail or {}).get("trkngCntrDtl")), container_no)
		if discharge_date:
			return discharge_date

	# transit cargo is tracked at B/L level only, it lists no containers to match against
	for row in cargo_rows:
		if not row.get("blCntrLst") and row.get("actlArvlDt"):
			return getdate(row.get("actlArvlDt"))

	return None


def find_container_date(rows, container_no):
	"""Discharge date of the container, taken from the row itself or from its B/L container list"""

	if not container_no:
		return None

	for row in rows:
		for container in row.get("blCntrLst") or [row]:
			if container.get("cntrNo") == container_no and container.get("actlArvlDt"):
				return getdate(container.get("actlArvlDt"))

	return None


def call_tracking_api(path, params):
	"""A failed lookup must never block the document being saved, so errors are only logged"""

	try:
		response = requests.get(f"{TRACKING_URL}/{path}", params=params, timeout=REQUEST_TIMEOUT)
		response.raise_for_status()

		return response.json()

	except Exception:
		frappe.log_error(
			title=f"TANeSW tracking request failed: {path}",
			message=f"Params: {params}\n\n{frappe.get_traceback()}",
		)

		return None


def get_rows(section):
	"""The API returns a single match as a dict and several matches as a list"""

	content = (section or {}).get("content")
	if isinstance(content, list):
		return content

	return [content] if content else []
