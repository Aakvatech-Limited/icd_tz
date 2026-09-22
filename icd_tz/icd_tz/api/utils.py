import re

import frappe
from frappe.utils import cint, nowdate

# Containers on these statuses are leaving or have left the ICD
DELIVERED_CONTAINER_STATUSES = ["At Gate Confirmation", "Delivered"]

# First character of an ISO 6346 size code is its length in feet. Letters are lengths
# too: reading digits alone takes the height code instead, so M2G1, a 48ft box, reads
# as 20ft.
LENGTH_CODES = {
	"1": 10,
	"2": 20,
	"3": 30,
	"4": 40,
	"9": 45,
	"A": 23,
	"B": 24,
	"C": 24,
	"D": 24,
	"E": 26,
	"F": 27,
	"G": 41,
	"H": 43,
	"K": 45,
	"L": 45,
	"M": 48,
	"N": 49,
	"P": 53,
}

# An ISO 6346 size code is four characters: length, height, then a type group whose
# first character is always a letter. That is what tells L5G1, a 45ft box, apart from
# free text such as HC20 or FT40, where the letters are a prefix and the digits are
# the size. Size is a free text field, so both reach here.
ISO_SIZE_CODE = re.compile(r"^[0-9A-Z][0-9A-Z][A-Z][0-9A-Z]$")

NON_DIGITS = re.compile(r"\D")

# Pricing sizes in feet, largest first. A container is charged at the largest size it
# reaches, so 30ft and 24ft are charged as 20ft and 45ft and 48ft as 40ft.
SIZE_BUCKETS = ((40, "40ft"), (20, "20ft"))


def get_container_length(size: str | None) -> int | None:
	"""Length in feet of a container size, from its ISO 6346 code or from its digits"""

	code = str(size or "").strip().upper()
	if not code:
		return None

	if ISO_SIZE_CODE.match(code):
		return LENGTH_CODES.get(code[0])

	digits = NON_DIGITS.sub("", code)

	return LENGTH_CODES.get(digits[:1]) if digits else None


def get_size_bucket(size: str | None) -> str | None:
	"""Pricing size of a container: the largest size its length reaches

	A size below the smallest pricing size has no bucket, so the caller reports it
	as missing criteria rather than charging it at a size it never reached.
	"""

	length = get_container_length(size)
	if not length:
		return None

	for feet, bucket in SIZE_BUCKETS:
		if length >= feet:
			return bucket

	return None


def get_service_items(settings_doc) -> dict:
	"""Service items in ICD TZ Settings, keyed by service type and pricing size

	Built once per run: the criteria are the same for every container being charged.
	"""

	service_items = {}
	for row in settings_doc.service_types:
		service_items.setdefault((row.service_type, get_size_bucket(row.size)), row.service_name)

	return service_items


def get_container_service_item(service_items: dict, service_type: str, size: str | None) -> str | None:
	"""Service item priced for a container size

	A container shorter than the smallest pricing size matches nothing, and the caller
	reports that as missing criteria rather than charging it at a size it never reached.
	"""

	size_bucket = get_size_bucket(size)

	return service_items.get((service_type, size_bucket)) if size_bucket else None


def validate_delivered_container(container_id, container_no=None, action="created"):
	"""Block records that would change a container which has already moved out of the ICD"""

	if not container_id:
		return

	status = frappe.db.get_value("Container", container_id, "status")
	if status not in DELIVERED_CONTAINER_STATUSES:
		return

	frappe.throw(
		f"Container: <b>{container_no or container_id}</b> is on <b>{status}</b> status, "
		f"this record cannot be {action}."
	)


def get_delivered_containers(container_ids):
	"""Containers that have moved out of the ICD, they must be left out of bulk creation"""

	if len(container_ids) == 0:
		return []

	return frappe.db.get_all(
		"Container",
		filters={"name": ["in", container_ids], "status": ["in", DELIVERED_CONTAINER_STATUSES]},
		pluck="name",
	)


def validate_delivered_containers(container_ids, action="cancelled"):
	"""Block a document that carries containers which have already moved out of the ICD"""

	delivered_containers = get_delivered_containers(container_ids)
	if len(delivered_containers) == 0:
		return

	container_nos = frappe.db.get_all(
		"Container", filters={"name": ["in", delivered_containers]}, pluck="container_no"
	)

	frappe.throw(
		f"Container: <b>{', '.join(container_nos)}</b> has already been moved out of the ICD, "
		f"this record cannot be {action}."
	)


def validate_cf_agent(doc):
	"""
	Validate the Clearing and Forwarding Agent
	"""
	if doc.c_and_f_company and doc.clearing_agent:
		cf_company = frappe.get_cached_value("Clearing Agent", doc.clearing_agent, "c_and_f_company")
		if doc.c_and_f_company != cf_company:
			frappe.throw(
				f"The selected Clearing Agent: <b>{doc.clearing_agent}</b> does not belong to the selected Clearing and Forwarding Company: <b>{doc.c_and_f_company}</b>"
			)


def set_container_cf_company(doc):
	"""Stamp the C&F company on the container once, the first document that carries it wins

	Container storage days are resolved from the C&F company contract, and the container
	itself has no other source for it.
	"""

	if not doc.get("container_id") or not doc.get("c_and_f_company"):
		return

	if frappe.db.get_value("Container", doc.container_id, "c_and_f_company"):
		return

	frappe.db.set_value(
		"Container", doc.container_id, "c_and_f_company", doc.c_and_f_company, update_modified=False
	)


def validate_draft_doc(doctype, docname):
	"""
	Validate linking of draft documents
	"""
	if frappe.db.get_value(doctype, docname, "docstatus") == 0:
		frappe.throw(
			f"Cannot link a draft document: <b>{doctype}- {docname}</b><br>Kindly submit the document first."
		)


def validate_qty_storage_item(doc):
	"""
	Validate the quantity of storage item if it matches the number of container child references.
	If the quantity does not match, it will adjust the container child references to match the quantity.
	"""

	if doc.get("h_bl_no") or not doc.get("m_bl_no"):
		return

	settings_doc = frappe.get_cached_doc("ICD TZ Settings")
	storage_services = [
		row.service_name
		for row in settings_doc.service_types
		if row.service_type in ["Storage-Single", "Storage-Double"]
	]
	for item in doc.items:
		if item.item_code in storage_services:
			if not item.container_child_refs:
				continue

			qty = cint(item.qty)
			child_references = item.container_child_refs.split(",")

			if qty < len(child_references):
				container_child_refs = child_references[:qty]
				item.container_child_refs = ",".join(container_child_refs)

			elif qty > len(child_references):
				frappe.throw(
					f"Qty: {qty} of the item: <b>{item.item_code}</b> cannot be greater than {len(child_references)} of container references"
				)


@frappe.whitelist()
def submit_doc(doc_type, doc_name):
	"""
	Submit the document
	"""

	doc = frappe.get_doc(doc_type, doc_name)
	doc.submit()

	return True
