import frappe
from frappe.utils import cint, nowdate


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
