import frappe


def execute():
	if not frappe.db.exists("Item Group", "ICD Services"):
		item_group = {
			"doctype": "Item Group",
			"item_group_name": "ICD Services",
			"parent_item_group": "All Item Groups",
		}
		frappe.get_doc(item_group).insert(ignore_permissions=True)
		frappe.db.commit()
