import frappe
import requests
from frappe.utils import getdate

TRACKING_URL = "https://tanesw.tra.go.tz/api/cgm/api/v1/cgme/trkng"
REQUEST_TIMEOUT = 15

# tracking event raised when the Discharge Result Report of a container is approved
DISCHARGE_APPROVAL_CODE = "B21"


def get_discharge_date(container_no, m_bl_no, crns=None):
	"""Actual discharge date of a container, taken from the TANeSW cargo tracking API

	A container number is reused across shipments, so the bill of lading is what
	says which one is meant. Passing the cargo reference numbers of that bill
	skips the search call that resolves them.
	"""

	if not container_no or not (m_bl_no or crns):
		return None

	for crn in crns or get_bill_crns(m_bl_no):
		detail = call_tracking_api("cntr-dtl", {"srchCrn": crn, "srchCntrNo": container_no})

		for record in get_rows((detail or {}).get("trkngCntrDtl")):
			if record.get("cntrNo") != container_no:
				continue

			discharge_date = get_discharge_event_date(record)
			if discharge_date:
				return discharge_date

	return None


def get_bill_crns(m_bl_no) -> list:
	"""Cargo reference numbers of a bill, resolved by the one search call"""

	cargo = call_tracking_api("srch", {"srchBlNo": m_bl_no})

	return sorted({row.get("crn") for row in get_rows((cargo or {}).get("trkngDtl")) if row.get("crn")})


def get_discharge_event_date(record):
	"""Date the Discharge Result Report of a container was approved, if it was"""

	for event in record.get("cntrPrcssLst") or []:
		if event.get("cagTrkngPrcssCd") == DISCHARGE_APPROVAL_CODE and event.get("prcssDt"):
			return getdate(event.get("prcssDt"))

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
