import frappe

UNSAFE = "eval:parent.m_bl_no"
SAFE = "eval:parent && parent.m_bl_no"


def execute():
	"""`parent` is null in dialogs and absent in report view, so a bare parent.x throws there.

	Frappe catches it and shows 'Invalid "depends_on" expression'.
	"""
	property_setters = frappe.get_all(
		"Property Setter",
		filters={"property": ["like", "%depends_on%"], "value": UNSAFE},
		pluck="name",
	)
	for name in property_setters:
		frappe.db.set_value("Property Setter", name, "value", SAFE, update_modified=False)

	if property_setters:
		frappe.clear_cache()
