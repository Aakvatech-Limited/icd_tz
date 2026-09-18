from icd_tz.icd_tz.api.accounting_dimensions import add_accounting_dimension


def execute():
	"""Add the Manifest as an accounting dimension so ICD revenue can be reported per manifest"""

	add_accounting_dimension("Manifest")
