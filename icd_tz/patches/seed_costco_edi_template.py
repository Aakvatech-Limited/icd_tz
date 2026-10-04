import frappe


def execute():
	"""Give every existing EDI Partner the shipped template of each type it lacks.

	The rows are inserted on their own, so a partner whose other settings no
	longer pass validation still gets them and the migration does not stop.
	"""

	for name in frappe.get_all("EDI Partner", pluck="name"):
		partner = frappe.get_doc("EDI Partner", name)

		for row in partner.seed_templates():
			row.db_insert()
