import frappe
from frappe.query_builder import Case


def execute():
	"""Store the Yes/No values as 1/0 so the Select to Check column change keeps them"""

	container = frappe.qb.DocType("Container")
	for field in ("has_removal_charges", "has_corridor_levy_charges"):
		# an int column casts 'Yes' to 0, so a re-run would tick every unticked row
		if frappe.db.get_column_type("Container", field).startswith("int"):
			continue

		column = container[field]
		frappe.qb.update(container).set(column, Case().when(column == "Yes", "1").else_("0")).run()
