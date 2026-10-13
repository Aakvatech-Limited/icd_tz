import frappe
from frappe.query_builder.functions import Lower
from frappe.utils import cint, flt

from icd_tz.icd_tz.api.icd_services import CHANGE_OF_STATUS, LIFT_ON_OFF

# Word in the old inspection service name and the Container service it is now charged on
SERVICE_WORDS = {"lift": LIFT_ON_OFF, "change": CHANGE_OF_STATUS}


def execute():
	"""Move the Lift and Change of Status services of submitted Container Inspections to their new fields

	The Container gets each charge and its submitted invoice. A Change of Status also gives the
	inspection its LCL status, volume, packages and ICD Official. Container Inspection Detail is
	removed after the migration, its table stays in the database.
	"""

	if not frappe.db.table_exists("Container Inspection Detail"):
		return

	container_updates, inspection_updates = {}, {}
	for row in get_inspection_service_rows():
		service = get_service(row.service)
		values = container_updates.setdefault(row.container_id, {})
		values[service.flag_field] = 1
		if row.sales_invoice:
			values[service.invoice_field] = row.sales_invoice

		if service == CHANGE_OF_STATUS:
			inspection_updates[row.inspection] = {
				"container_status": "LCL",
				"icd_official": row.icd_official,
				"volume": flt(row.volume),
				"counted_packages": cint(row.counted_packages),
			}

	frappe.db.bulk_update("Container", container_updates, update_modified=False)
	frappe.db.bulk_update("Container Inspection", inspection_updates, update_modified=False)


def get_service(service_name: str):
	service_name = service_name.lower()
	return next(service for word, service in SERVICE_WORDS.items() if word in service_name)


def get_inspection_service_rows() -> list:
	"""Lift and Change rows of submitted inspections, with the invoice only when it is submitted

	A cancelled invoice stays on the inspection row, so it is not read.
	"""

	inspection = frappe.qb.DocType("Container Inspection")
	detail = frappe.qb.DocType("Container Inspection Detail")
	invoice = frappe.qb.DocType("Sales Invoice")
	service_name = Lower(detail.service)

	return (
		frappe.qb.from_(detail)
		.inner_join(inspection)
		.on(detail.parent == inspection.name)
		.left_join(invoice)
		.on((invoice.name == detail.sales_invoice) & (invoice.docstatus == 1))
		.select(
			inspection.name.as_("inspection"),
			inspection.container_id,
			detail.service,
			detail.icd_official,
			detail.volume,
			detail.counted_packages,
			invoice.name.as_("sales_invoice"),
		)
		.where(
			(detail.parenttype == "Container Inspection")
			& (inspection.docstatus == 1)
			& inspection.container_id.isnotnull()
			& (service_name.like("%lift%") | service_name.like("%change%"))
		)
	).run(as_dict=True)
