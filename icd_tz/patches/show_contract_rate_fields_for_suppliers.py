import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from icd_tz.patches.create_custom_fields import load_json

FIELDS = ("is_rate_based", "price_list")


def execute():
	"""Show Rate Based and Price List on Supplier contracts

	after_migrate creates the contract fields with update=False, so an existing site
	keeps the old C&F only conditions until they are updated here.
	"""

	fields = [field for field in load_json("06_icd_on_contract.json") if field["fieldname"] in FIELDS]
	create_custom_fields({"Contract": fields}, update=True)
	frappe.clear_cache(doctype="Contract")
