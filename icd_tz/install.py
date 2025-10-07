import frappe

def before_install():
    create_default_price_list()

def create_default_price_list():
    if not frappe.db.exists("Price List", "Standard Selling"):
        price_list = frappe.get_doc({
            "doctype": "Price List",
            "price_list_name": "Standard Selling",
            "enabled": 1,
            "buying": 0,
            "selling": 1,
            "currency": frappe.defaults.get_global_default("currency") or "USD"
        })
        price_list.insert(ignore_permissions=True)
        frappe.db.commit()