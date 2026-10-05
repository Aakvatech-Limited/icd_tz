from icd_tz.icd_tz.api.accounting_dimensions import DIMENSIONS, add_accounting_dimension


def execute():
	"""Add Manifest, ICD Container and ICD Master BL as accounting dimensions

	Manifest reports ICD revenue per manifest. ICD Container and ICD Master BL let a Purchase
	Order or Purchase Invoice be costed per container or per bill of lading while the
	Container record does not exist yet.
	"""

	for document_type in ("Manifest", *DIMENSIONS):
		add_accounting_dimension(document_type)
