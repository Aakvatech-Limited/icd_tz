import frappe

from icd_tz.icd_tz.api.accounting_dimensions import (
	DIMENSIONS,
	GUARDED_DOCTYPES,
	add_accounting_dimension,
)


def execute():
	"""Add ICD Container and ICD Master BL as accounting dimensions

	They let a Purchase Order or Purchase Invoice be costed per container or per bill of
	lading while the Container record does not exist yet.
	"""

	for document_type, fieldname in DIMENSIONS.items():
		add_accounting_dimension(document_type)
		index_dimension_field(fieldname)


def index_dimension_field(fieldname: str):
	"""erpnext creates dimension fields without an index, the cancellation guard filters them

	Without this the guard scans GL Entry, the largest table on the site, on every
	Manifest cancellation.
	"""

	for doctype in GUARDED_DOCTYPES:
		if not frappe.db.has_column(doctype, fieldname):
			continue

		frappe.db.add_index(doctype, [fieldname])
		print(f"Indexed {doctype}.{fieldname}")
