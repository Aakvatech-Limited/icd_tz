import frappe

# Each pricing table and the parent it belongs to
CATEGORY_TABLES = {
	"ICD TZ Service Detail": "ICD Setting",
	"ICD TZ Loose Detail": "ICD Setting",
	"ICD TZ Settings Detail": "ICD Setting",
	"Storage Contract Detail": "Contract",
}


def execute():
	"""Price every existing ICD Setting and Contract storage row as Normal cargo

	Dangerous, OOG and Reefer containers then find no row until their own rows are set up.
	"""

	for doctype, parenttype in CATEGORY_TABLES.items():
		table = frappe.qb.DocType(doctype)
		(
			frappe.qb.update(table)
			.set(table.cargo_category, "Normal")
			.where(table.parenttype == parenttype)
			.where(table.cargo_category.isnull() | (table.cargo_category == ""))
		).run()

	frappe.clear_cache(doctype="ICD Setting")
	frappe.clear_cache(doctype="Contract")
