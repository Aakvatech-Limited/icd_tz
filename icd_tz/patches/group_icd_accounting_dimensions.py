import frappe

from icd_tz.icd_tz.api.accounting_dimensions import ACCOUNTING_SECTION, DIMENSION_DISPLAY_ORDER


def execute():
	"""Put the ICD dimension fields together under the Accounting Dimensions section

	erpnext alternates each new dimension between two anchors, one of which
	(dimension_col_break) does not exist on every doctype. A field anchored to a missing
	one is appended to the end of the form, which scattered Manifest, ICD Master BL and
	ICD Container across unrelated sections.
	"""

	for doctype in get_doctypes_to_group():
		group_fields(doctype)


def get_doctypes_to_group() -> list:
	"""Doctypes carrying at least one ICD dimension field"""

	return frappe.get_all(
		"Custom Field",
		filters={"fieldname": ("in", DIMENSION_DISPLAY_ORDER)},
		pluck="dt",
		distinct=True,
	)


def group_fields(doctype: str):
	"""Chain the dimension fields one after another, starting at the section break"""

	fieldnames = [field.fieldname for field in frappe.get_meta(doctype).fields]
	if ACCOUNTING_SECTION not in fieldnames:
		return

	anchor = ACCOUNTING_SECTION
	moved = []
	for fieldname in DIMENSION_DISPLAY_ORDER:
		custom_field = frappe.db.get_value(
			"Custom Field", {"dt": doctype, "fieldname": fieldname}, ["name", "insert_after"], as_dict=True
		)
		if not custom_field:
			continue

		if custom_field.insert_after != anchor:
			frappe.db.set_value("Custom Field", custom_field.name, "insert_after", anchor)
			moved.append(fieldname)

		anchor = fieldname

	if moved:
		frappe.clear_cache(doctype=doctype)
		print(f"Grouped {', '.join(moved)} under {ACCOUNTING_SECTION} on {doctype}")
