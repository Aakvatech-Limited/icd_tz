import frappe


def execute():
	icd_settings_doc = frappe.get_doc("ICD TZ Settings")

	try:
		icd_settings_doc.default_price_list = "Standard Selling"
		icd_settings_doc.transport_item = "Transport Charges"
		icd_settings_doc.in_yard_booking_item = "Stripping and De-Stuffing charges"
		icd_settings_doc.custom_verification_item = "Custom Verification Handling Charges"
		icd_settings_doc.removal_item = "Removal Charges"
		icd_settings_doc.corridor_levy_item = "Corridor Levy"
		icd_settings_doc.shore_handling_item_t1_20ft = "Shore Handling Charges T1 20ft"
		icd_settings_doc.shore_handling_item_t1_40ft = "Shore Handling Charges T1 40ft"
		icd_settings_doc.shore_handling_item_t2_20ft = "Shore Handling Charges T2 20ft"
		icd_settings_doc.shore_handling_item_t2_40ft = "Shore Handling Charges T2 40ft"
		icd_settings_doc.storage_item_single_20ft = "Storage Charges (single 20ft)"
		icd_settings_doc.storage_item_single_40ft = "Storage Charges (single 40ft)"
		icd_settings_doc.storage_item_double_20ft = "Storage charges (double 20ft)"
		icd_settings_doc.storage_item_double_40ft = "Storage charges (double 40ft)"
		icd_settings_doc.save(ignore_permissions=True)

	except Exception:
		frappe.log_error("Failed to update ICD TZ Settings", frappe.get_traceback())
