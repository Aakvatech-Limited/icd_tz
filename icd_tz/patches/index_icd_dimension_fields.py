import frappe

from icd_tz.icd_tz.api.accounting_dimensions import DIMENSIONS, GUARDED_DOCTYPES

# expense_release.get_wip_balance filters GL Entry by the WIP account, then by container
WIP_BALANCE_INDEX = ["account", "icd_container"]


def execute():
	"""Index the ICD dimension fields the cancellation guard and the WIP release filter on

	The index is declared through search_index on the Custom Field. A bare index added
	during migrate has nothing behind it, so the next schema sync of the table drops it.
	"""

	for doctype in GUARDED_DOCTYPES:
		index_custom_fields(doctype, get_guarded_fields(doctype))

	if frappe.db.has_column("GL Entry", "icd_container"):
		frappe.db.add_index("GL Entry", WIP_BALANCE_INDEX)
		print(f"Indexed GL Entry on {', '.join(WIP_BALANCE_INDEX)}")


def get_guarded_fields(doctype: str) -> list:
	"""The cancellation guard also filters GL Entry by manifest on its own"""

	fieldnames = list(DIMENSIONS.values())
	return [*fieldnames, "manifest"] if doctype == "GL Entry" else fieldnames


def index_custom_fields(doctype: str, fieldnames: list):
	"""Set search_index on the dimension Custom Fields and let the schema sync add the index"""

	unindexed = frappe.get_all(
		"Custom Field",
		filters={"dt": doctype, "fieldname": ("in", fieldnames), "search_index": 0},
		pluck="name",
	)
	for name in unindexed:
		frappe.db.set_value("Custom Field", name, "search_index", 1)

	frappe.clear_cache(doctype=doctype)
	frappe.db.updatedb(doctype)
	print(f"Indexed {doctype} on {', '.join(fieldnames)}")
