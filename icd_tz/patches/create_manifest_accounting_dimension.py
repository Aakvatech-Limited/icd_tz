import frappe
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	make_dimension_in_accounting_doctypes,
)


def execute():
	"""Add the Manifest as an accounting dimension so ICD revenue can be reported per manifest"""

	if frappe.db.exists("Accounting Dimension", {"document_type": "Manifest"}):
		return

	dimension = frappe.new_doc("Accounting Dimension")
	dimension.document_type = "Manifest"
	dimension.flags.ignore_permissions = True
	dimension.insert()

	# on_update only queues the field creation, run it here so the fields exist once the patch ends
	make_dimension_in_accounting_doctypes(doc=dimension)

	print(f"Added the Manifest accounting dimension, field: {dimension.fieldname}")
