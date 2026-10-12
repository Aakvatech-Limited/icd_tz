import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from icd_tz.patches.create_custom_fields import load_json


def execute():
	"""Give every existing Contract the company of the ICD Setting

	after_migrate creates the custom fields only after the patches run, so the
	company field is created here before it is filled.
	"""

	fields = [field for field in load_json("06_icd_on_contract.json") if field["fieldname"] == "company"]
	create_custom_fields({"Contract": fields}, update=True)

	if not frappe.db.exists("Contract", {"company": ("is", "not set")}):
		return

	companies = frappe.get_all("ICD Setting", pluck="company")
	if len(companies) != 1:
		frappe.throw(
			f"Contract: found {len(companies)} ICD Setting records, so the company of the existing "
			"contracts is not known. Set the Company on each Contract, then run the migration again."
		)

	frappe.db.set_value(
		"Contract", {"company": ("is", "not set")}, "company", companies[0], update_modified=False
	)
	print(f"Contract: set the company {companies[0]} on the existing contracts")
