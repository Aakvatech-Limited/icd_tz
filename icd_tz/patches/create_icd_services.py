import frappe


def execute():
	for row in get_item_map():
		if not frappe.db.exists("Item", row["item_code"]):
			row.update({"doctype": "Item"})
			item = frappe.get_doc(row)
			item.insert(ignore_permissions=True)
			frappe.db.commit()


def get_item_map():
	return [
		{
			"item_code": "Transport Charges",
			"item_name": "Transport Charges",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Transport Charges",
			"is_sales_item": 1,
		},
		{
			"item_code": "Corridor Levy",
			"item_name": "Corridor Levy",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Corridor Levy",
			"is_sales_item": 1,
		},
		{
			"item_code": "Removal Charges",
			"item_name": "Removal Charges",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Removal Charges",
			"is_sales_item": 1,
		},
		{
			"item_code": "Container Change of status",
			"item_name": "Container Change of status",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Container Change of status",
			"is_sales_item": 1,
		},
		{
			"item_code": "Container Lift on/off",
			"item_name": "Container Lift on/off",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Container Lift on/off",
			"is_sales_item": 1,
		},
		{
			"item_code": "Stripping and De-Stuffing charges",
			"item_name": "Stripping and De-Stuffing charges",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Stripping and De-Stuffing charges",
			"is_sales_item": 1,
		},
		{
			"item_code": "Custom Verification Handling Charges",
			"item_name": "Custom Verification Handling Charges",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Custom Verification Handling Charges",
			"is_sales_item": 1,
		},
		{
			"item_code": "Shore Handling Charges T1 20ft",
			"item_name": "Shore Handling Charges T1 20ft",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Shore Handling Charges T1 20ft",
			"is_sales_item": 1,
		},
		{
			"item_code": "Shore Handling Charges T1 40ft",
			"item_name": "Shore Handling Charges T1 40ft",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Shore Handling Charges T1 40ft",
			"is_sales_item": 1,
		},
		{
			"item_code": "Shore Handling Charges T2 20ft",
			"item_name": "Shore Handling Charges T2 20ft",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Shore Handling Charges T2 20ft",
			"is_sales_item": 1,
		},
		{
			"item_code": "Shore Handling Charges T2 40ft",
			"item_name": "Shore Handling Charges T2 40ft",
			"item_group": "ICD Services",
			"stock_uom": "Nos",
			"description": "Shore Handling Charges T2 40ft",
			"is_sales_item": 1,
		},
		{
			"item_code": "Storage Charges (single 20ft)",
			"item_name": "Storage Charges (single 20ft)",
			"item_group": "ICD Services",
			"stock_uom": "Day",
			"description": "Storage Charges (single 20ft)",
			"is_sales_item": 1,
		},
		{
			"item_code": "Storage Charges (single 40ft)",
			"item_name": "Storage Charges (single 40ft)",
			"item_group": "ICD Services",
			"stock_uom": "Day",
			"description": "Storage Charges (single 40ft)",
			"is_sales_item": 1,
		},
		{
			"item_code": "Storage charges (double 20ft)",
			"item_name": "Storage charges (double 20ft)",
			"item_group": "ICD Services",
			"stock_uom": "Day",
			"description": "Storage charges (double 20ft)",
			"is_sales_item": 1,
		},
		{
			"item_code": "Storage charges (double 40ft)",
			"item_name": "Storage charges (double 40ft)",
			"item_group": "ICD Services",
			"stock_uom": "Day",
			"description": "Storage charges (double 40ft)",
			"is_sales_item": 1,
		},
	]
