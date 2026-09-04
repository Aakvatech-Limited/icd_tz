import frappe
from frappe.utils import cint, nowdate

# Containers on these statuses are leaving or have left the ICD
DELIVERED_CONTAINER_STATUSES = ["At Gate Confirmation", "Delivered"]


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
