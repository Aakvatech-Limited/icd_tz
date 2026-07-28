import frappe


def execute():
    icd_settings_doc = frappe.get_doc("ICD TZ Settings")

    if icd_settings_doc.received_date_threshold_hours:
        return

    icd_settings_doc.received_date_threshold_hours = 48
    icd_settings_doc.save(ignore_permissions=True)
