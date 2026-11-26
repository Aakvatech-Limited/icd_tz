import frappe


def execute():
	"""The one port storage band set in use so far becomes the Local cargo bands

	Transit containers are then skipped, with an Error Log, until their own bands are set.
	"""

	table = frappe.qb.DocType("ICD TZ Port Storage Detail")
	(
		frappe.qb.update(table)
		.set(table.cargo_type, "Local")
		.where(table.parenttype == "ICD Setting")
		.where(table.cargo_type.isnull() | (table.cargo_type == ""))
	).run()

	frappe.clear_cache(doctype="ICD Setting")
