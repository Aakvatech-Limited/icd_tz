import frappe

from icd_tz.patches.create_custom_fields import create_fields_from_json, load_json

CONTRACT_FIELDS_JSON = "06_icd_on_contract.json"
CF_PARTY_TYPE = "Clearing and Forwarding Company"


def execute():
	"""Tick Rate Based on C&F contracts that already price through their price list

	Before Rate Based existed a contract price list applied on its own. The new
	checkbox defaults to 0, so without this those contracts would silently stop
	pricing. Custom fields are created in `after_migrate`, which runs after
	patches, so the field may not exist yet on the first migrate.
	"""

	if not frappe.db.has_column("Contract", "is_rate_based"):
		create_fields_from_json(load_json(CONTRACT_FIELDS_JSON))

	contracts = frappe.get_all(
		"Contract",
		filters={"party_type": CF_PARTY_TYPE, "price_list": ["is", "set"], "is_rate_based": 0},
		pluck="name",
	)
	if not contracts:
		return

	frappe.db.set_value("Contract", {"name": ("in", contracts)}, "is_rate_based", 1, update_modified=False)

	for name in contracts:
		frappe.clear_document_cache("Contract", name)
