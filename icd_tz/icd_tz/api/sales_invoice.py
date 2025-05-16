# sales_invoice.py
import frappe
from icd_tz.icd_tz.api.utils import validate_qty_storage_item

def before_save(doc, method):
    validate_qty_storage_item(doc)

def on_submit(doc, method):
    update_sales_references(doc)

def update_sales_references(doc):
    if not doc.m_bl_no:
        return
    
    invoice_id = doc.name
    if doc.is_return:
        invoice_id = None

    settings_doc = frappe.get_cached_doc("ICD TZ Settings")
    
    # Existing service lists
    corridor_services = [row.service_name for row in settings_doc.service_types if row.service_type == "Levy"]
    verification_services = [row.service_name for row in settings_doc.service_types if row.service_type == "Verification"]
    stripping_services = [row.service_name for row in settings_doc.service_types if row.service_type == "Stripping"]
    removal_services = [row.service_name for row in settings_doc.service_types if row.service_type == "Removal"]
    transport_services = [row.service_name for row in settings_doc.service_types if row.service_type == "Transport"]
    storage_services = [row.service_name for row in settings_doc.service_types if row.service_type in ["Storage-Single", "Storage-Double"]]
    shore_services = [row.service_name for row in settings_doc.service_types if row.service_type == "Shore"]
    
    # New: Reefer services list
    reefer_services = [row.service_name for row in settings_doc.service_types if row.service_type in ["Reefer-Single", "Reefer-Double"]]

    # For loose containers (existing code)
    corridor_services += [row.service_name for row in settings_doc.loose_types if row.service_type == "Levy"]
    verification_services += [row.service_name for row in settings_doc.loose_types if row.service_type == "Verification"]
    stripping_services += [row.service_name for row in settings_doc.loose_types if row.service_type == "Stripping"]
    removal_services += [row.service_name for row in settings_doc.loose_types if row.service_type == "Removal"]
    transport_services += [row.service_name for row in settings_doc.loose_types if row.service_type == "Transport"]
    storage_services += [row.service_name for row in settings_doc.loose_types if row.service_type in ["Storage-Single", "Storage-Double"]]
    shore_services += [row.service_name for row in settings_doc.loose_types if row.service_type == "Shore"]
    
    # New: Add loose container reefer services
    reefer_services += [row.service_name for row in settings_doc.loose_types if row.service_type in ["Reefer-Single", "Reefer-Double"]]


    # Item processing (existing code structure)
    for item in doc.items:
        if item.item_code in transport_services:
            update_container_reception(item.container_id, invoice_id, "t_sales_invoice")
        
        elif item.item_code in shore_services:
            update_container_reception(item.container_id, invoice_id, "s_sales_invoice")
        
        elif item.item_code in stripping_services:
            update_booking_refs(item.container_id, invoice_id, "s_sales_invoice")
        
        elif item.item_code in verification_services:
            update_booking_refs(item.container_id, invoice_id, "cv_sales_invoice")
        
        elif item.item_code in removal_services:
            update_container_refs(item.container_id, invoice_id, "r_sales_invoice")
        
        elif item.item_code in corridor_services:
            update_container_refs(item.container_id, invoice_id, "c_sales_invoice")
        
        elif item.item_code in storage_services:
            update_storage_date_refs(item.container_id, invoice_id, item.container_child_refs)
        
        # New: Reefer charge handling
        elif item.item_code in reefer_services:
            update_reefer_date_refs(item.container_id, invoice_id, item.container_child_refs)
        
        else:
            update_container_insp(item.container_id, item.item_code, invoice_id)

    # Existing service order update
    sales_order = doc.items[0].sales_order
    service_orders = frappe.db.get_all(
        "Service Order",
        filters={"sales_order": sales_order},
    )
    for row in service_orders:
        frappe.db.set_value(
            "Service Order",
            row.name,
            "sales_invoice",
            invoice_id
        )

# New function added for reefer charges
def update_reefer_date_refs(container_id, invoice_id, child_refs):
    container_doc = frappe.get_doc("Container", container_id)
    for child in container_doc.container_dates:
        if child.name in child_refs:
            child.reefer_payment_reference = invoice_id
    container_doc.status = "At Gatepass"
    container_doc.save(ignore_permissions=True)

# All original helper functions below remain unchanged
def update_container_reception(container_id, invoice_id, field):
    container_reception = frappe.db.get_value(
        "Container",
        container_id,
        "container_reception"
    )

    if container_reception:
        frappe.db.set_value(
            "Container Reception",
            container_reception,
            field,
            invoice_id
        )

def update_booking_refs(container_id, invoice_id, field):
    filters = {
        "container_id": container_id,
        "docstatus": 1
    }

    booking_ids = frappe.db.get_all("In Yard Container Booking", filters, pluck="name")
    if len(booking_ids) == 0:
        return
    
    for booking_id in booking_ids:
        frappe.db.set_value(
            "In Yard Container Booking",
            booking_id,
            field,
            invoice_id
        )

def update_container_refs(container_id, invoice_id, field):
    container_doc = frappe.get_doc("Container", container_id)
    container_doc.update({
        field: invoice_id
    })
    container_doc.status = "At Gatepass"
    container_doc.save(ignore_permissions=True)

def update_storage_date_refs(container_id, invoice_id, child_refs):
    container_doc = frappe.get_doc("Container", container_id)
    for child in container_doc.container_dates:
        if child.name in child_refs:
            child.sales_invoice = invoice_id
    
    container_doc.status = "At Gatepass"
    container_doc.save(ignore_permissions=True)

def update_container_insp(container_id, item_code, invoice_id):
    container_inspections = frappe.db.get_all("Container Inspection", {"container_id": container_id, "docstatus": 1}, pluck="name")
    if len(container_inspections) == 0:
        return
    
    for inspeaction in container_inspections:
        insp_doc = frappe.get_doc("Container Inspection", inspeaction)
        for row in insp_doc.services:
            if row.service == item_code:
                frappe.db.set_value(
                    "Container Inspection Detail",
                    row.name,
                    "sales_invoice",
                    invoice_id
                )