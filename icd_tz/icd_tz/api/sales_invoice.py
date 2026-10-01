import frappe

from icd_tz.icd_tz.api.icd_services import get_item_services
from icd_tz.icd_tz.api.utils import get_service_items, validate_qty_storage_item


def before_save(doc, method):
	validate_qty_storage_item(doc)


def on_submit(doc, method):
	update_sales_references(doc)


def update_sales_references(doc):
	if not doc.m_bl_no and not doc.h_bl_no:
		return

	invoice_id = doc.name
	if doc.is_return:
		invoice_id = None

	settings_doc = frappe.get_cached_doc("ICD TZ Settings")
	item_services = get_item_services(settings_doc)
	storage_items = get_service_items(settings_doc, "Storage-Single") + get_service_items(
		settings_doc, "Storage-Double"
	)

	for item in doc.items:
		service = item_services.get(item.item_code)
		if service:
			service.set_invoice(item.container_id, doc)

		elif item.item_code in storage_items:
			update_storage_date_refs(item.container_id, invoice_id, item.container_child_refs)

		else:
			update_container_insp(item.container_id, item.item_code, invoice_id)

	sales_order = doc.items[0].sales_order
	service_orders = frappe.db.get_all(
		"Service Order",
		filters={"sales_order": sales_order},
	)
	for row in service_orders:
		frappe.db.set_value("Service Order", row.name, "sales_invoice", invoice_id)


def update_storage_date_refs(container_id, invoice_id, child_refs):
	container_doc = frappe.get_doc("Container", container_id)
	for child in container_doc.container_dates:
		if child.name in child_refs:
			child.sales_invoice = invoice_id

	container_doc.status = "At Gatepass"
	container_doc.save(ignore_permissions=True)


def update_container_insp(container_id, item_code, invoice_id):
	container_inspections = frappe.db.get_all(
		"Container Inspection", {"container_id": container_id, "docstatus": 1}, pluck="name"
	)
	if len(container_inspections) == 0:
		return

	for inspeaction in container_inspections:
		insp_doc = frappe.get_doc("Container Inspection", inspeaction)
		for row in insp_doc.services:
			if row.service == item_code:
				frappe.db.set_value("Container Inspection Detail", row.name, "sales_invoice", invoice_id)
