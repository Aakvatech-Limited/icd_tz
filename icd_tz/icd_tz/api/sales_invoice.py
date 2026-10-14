import frappe

from icd_tz.icd_tz.api.icd_services import get_item_services
from icd_tz.icd_tz.api.utils import get_icd_setting, get_service_items, validate_qty_storage_item


def before_save(doc, method):
	validate_qty_storage_item(doc)


def on_submit(doc, method):
	update_sales_references(doc)


def on_cancel(doc, method):
	update_sales_references(doc, is_cancelled=True)


def get_invoice_change(doc, is_cancelled: bool = False) -> tuple[str | None, str | None]:
	"""Invoice this document adds to the ICD records, and the invoice it removes

	A return removes the invoice it reverses. Cancelling undoes either one.
	"""

	added, removed = (None, doc.return_against) if doc.is_return else (doc.name, None)
	return (removed, added) if is_cancelled else (added, removed)


def update_sales_references(doc, is_cancelled: bool = False):
	if not doc.m_bl_no and not doc.h_bl_no:
		return

	added, removed = get_invoice_change(doc, is_cancelled)

	settings_doc = get_icd_setting(doc.company)
	item_services = get_item_services(settings_doc)
	storage_items = get_service_items(settings_doc, "Storage-Single") + get_service_items(
		settings_doc, "Storage-Double"
	)

	for item in doc.items:
		service = item_services.get(item.item_code)
		if service:
			service.set_invoice(item.container_id, added, removed)

		elif item.item_code in storage_items:
			update_storage_date_refs(item.container_id, added, removed, item.container_child_refs)

	service_orders = frappe.db.get_all(
		"Service Order",
		filters={"sales_order": doc.items[0].sales_order},
		fields=["name", "sales_invoice"],
	)
	for row in service_orders:
		if added or row.sales_invoice == removed:
			frappe.db.set_value("Service Order", row.name, "sales_invoice", added)

	# a cancelled invoice is owed again, unless the box has already left
	if is_cancelled and not doc.is_return:
		reopen_payment(item.container_id for item in doc.items if item.container_id)


def reopen_payment(container_ids):
	for container_id in set(container_ids):
		if frappe.db.get_value("Container", container_id, "status") == "At Gatepass":
			frappe.db.set_value("Container", container_id, "status", "At Payments")


def update_storage_date_refs(container_id, added, removed, child_refs):
	container_doc = frappe.get_doc("Container", container_id)
	for child in container_doc.container_dates:
		if child.name in child_refs and (added or child.sales_invoice == removed):
			child.sales_invoice = added

	container_doc.status = "At Gatepass"
	container_doc.save(ignore_permissions=True)
