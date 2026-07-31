import frappe


def execute():
	for state in get_state_map():
		if not frappe.db.exists("Container State", state):
			state = {
				"doctype": "Container State",
				"state": state,
			}
			frappe.get_doc(state).insert(ignore_permissions=True)
			frappe.db.commit()


def get_state_map():
	return [
		"T: TORN",
		"R: RUSTED",
		"PI: PUSHED IN",
		"PO: PUSHED OUT",
		"M: MISSING",
		"L: LOOSE",
		"H: HOLE",
		"DI: DISTORTED",
		"D: DENT",
		"C: CUT",
		"CR: CRACKED",
		"B: BRUSHED",
		"BR: BROKEN",
		"BE: BENT",
	]
