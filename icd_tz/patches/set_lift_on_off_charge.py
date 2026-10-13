import frappe
from frappe.query_builder.functions import Lower, Max


def execute():
	"""Flag the containers whose submitted Container Inspection has a Lift service

	The invoice on the inspection row is copied, so a Gate Pass does not ask again for a paid charge.
	"""

	for container_id, invoice in get_lift_services().items():
		values = {"has_lift_on_off_charge": 1}
		if invoice:
			values["lo_sales_invoice"] = invoice

		frappe.db.set_value("Container", container_id, values, update_modified=False)


def get_lift_services() -> dict:
	"""Submitted invoice of the Lift service of each inspected container, None when there is none

	A cancelled invoice stays on the inspection row, so only a submitted one is copied.
	"""

	inspection = frappe.qb.DocType("Container Inspection")
	detail = frappe.qb.DocType("Container Inspection Detail")
	invoice = frappe.qb.DocType("Sales Invoice")
	rows = (
		frappe.qb.from_(detail)
		.inner_join(inspection)
		.on(detail.parent == inspection.name)
		.left_join(invoice)
		.on((invoice.name == detail.sales_invoice) & (invoice.docstatus == 1))
		.select(inspection.container_id, Max(invoice.name))
		.where(
			(detail.parenttype == "Container Inspection")
			& (inspection.docstatus == 1)
			& inspection.container_id.isnotnull()
			& Lower(detail.service).like("%lift%")
		)
		.groupby(inspection.container_id)
	).run()

	return dict(rows)
