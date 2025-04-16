import frappe
from frappe.utils import nowdate
from icd_tz.icd_tz.api.utils import validate_qty_storage_item


def before_save(doc, method):
    validate_qty_storage_item(doc)

def on_trash(doc, method):
    unlink_sales_order(doc)

def unlink_sales_order(doc):
    if not doc.m_bl_no:
        return
    
    service_orders = frappe.db.get_all("Service Order", filters={"sales_order": doc.name})
    if len(service_orders) > 0:
        for row in service_orders:
            frappe.db.set_value(
                "Service Order",
                row.name,
                "sales_order",
                "",
                update_modified=False
            )

@frappe.whitelist()
def make_sales_order(doc_type=None, doc_name=None, m_bl_no=None):
    items = []
    company = None
    consignee = None
    c_and_f_company = None
    order_m_bl_no = m_bl_no if m_bl_no else None

    settings_doc = frappe.get_cached_doc("ICD TZ Settings")

    items += get_storage_services(m_bl_no)

    service_order_items, service_docs = get_service_order_items(doc_type=doc_type, doc_name=doc_name, m_bl_no=m_bl_no)
    
    items += service_order_items
    if len(items) == 0:
        return
    
    if len(service_docs) > 0:
        source_doc = service_docs[0]

        if not consignee:
            consignee = source_doc.consignee
        
        if not company:
            company = source_doc.company
        
        if not c_and_f_company:
            c_and_f_company = source_doc.c_and_f_company
        
        if not order_m_bl_no:
            order_m_bl_no = source_doc.m_bl_no
    
    sales_order = frappe.get_doc({
        "doctype": "Sales Order",
        "company": company,
        "customer": consignee,
        "c_and_f_company": c_and_f_company,
        "transaction_date": nowdate(),
        "delivery_date": nowdate(),
        "selling_price_list": settings_doc.get("default_price_list"),
        "currency": frappe.get_cached_value("Price List", settings_doc.get("default_price_list"), "currency"),
        "items": items,
        "consignee": consignee,
        "m_bl_no": order_m_bl_no,
    })
    
    sales_order.insert()
    sales_order.set_missing_values()
    sales_order.calculate_taxes_and_totals()
    sales_order.save(ignore_permissions=True)
    sales_order.reload()

    for doc in service_docs:
        doc.db_set("sales_order", sales_order.name)
    
    frappe.msgprint(f"Sales Order <b>{sales_order.name}</b> created successfully", alert=True)
    return sales_order.name


def get_storage_services(m_bl_no):
    services = []

    containers = frappe.db.get_all(
        "Container", filters={"m_bl_no": m_bl_no},
        fields=["name", "days_to_be_billed"]
    )
    if len(containers) == 0:
        return

    settings_doc = frappe.get_cached_doc("ICD TZ Settings")

    for container in containers:
        if container.days_to_be_billed == 0:
            continue
        
        container_doc = frappe.get_doc("Container", container.name)

        single_days, double_days = get_container_days_to_be_billed(
            container_doc,
            settings_doc
        )

        if container_doc.has_single_charge == 1:
            single_storage_item = None

            for row in settings_doc.service_types:
                if row.service_type == "Storage-Single":
                    if "2" in str(row.size)[0] and "2" in str(container_doc.size)[0]:
                        single_storage_item = row.service_name
                        break

                    elif "4" in str(row.size)[0] and "4" in str(container_doc.size)[0]:
                        single_storage_item = row.service_name
                        break

                    else:
                        continue
                
            if not single_storage_item:
                frappe.throw(
                    f"Storage-Single Pricing Criteria for Size: {container_doc.size} is not set in ICD TZ Settings, Please set it to continue"
                )
            
            if len(single_days) > 0:
                services.append({
                    'item_code': single_storage_item,
                    'qty': len(single_days),
                    'container_no': container_doc.container_no,
                    'container_id': container_doc.name,
                    "container_child_refs": ",".join(single_days)
                })

        
        if container_doc.has_double_charge == 1:
            double_storage_item = None

            for row in settings_doc.service_types:
                if row.service_type == "Storage-Double":
                    if "2" in str(row.size)[0] and "2" in str(container_doc.size)[0]:
                        double_storage_item = row.service_name
                        break

                    elif "4" in str(row.size)[0] and "4" in str(container_doc.size)[0]:
                        double_storage_item = row.service_name
                        break

                    else:
                        continue
            
            if not double_storage_item:
                frappe.throw(
                    f"Storage-Double Pricing Criteria for Size: {container_doc.size} is not set in ICD TZ Settings, Please set it to continue"
                )
            
            if len(double_days) > 0:
                services.append({
                    'item_code': double_storage_item,
                    'qty': len(double_days),
                    'container_no': container_doc.container_no,
                    'container_id': container_doc.name,
                    "container_child_refs": ",".join(double_days)
                })
        
        if (
            not container_doc.r_sales_invoice and
            container_doc.has_removal_charges == "Yes"
        ):
            removal_item = None
            
            for row in settings_doc.service_types:
                if row.service_type == "Removal":
                    if "2" in str(row.size)[0] and "2" in str(container_doc.size)[0]:
                        removal_item = row.service_name
                        break

                    elif "4" in str(row.size)[0] and "4" in str(container_doc.size)[0]:
                        removal_item = row.service_name
                        break

                    else:
                        continue
            
            if not removal_item:
                frappe.throw(
                    f"Removal Pricing Criteria for Size: {container_doc.size} is not set in ICD TZ Settings, Please set it to continue"
                )
            
            services.append({
                'item_code': removal_item,
                'qty': 1,
                'container_no': container_doc.container_no,
                'container_id': container_doc.name,
            })
                
    return services

def get_container_days_to_be_billed(container_doc, settings_doc):
    single_days = []
    double_days = []
    no_of_single_days = 0
    no_of_double_days = 0
    single_charge_count = 0
    double_charge_count = 0

    for d in settings_doc.storage_days:
        if d.destination == container_doc.place_of_destination:
            if d.charge == "Single":
                no_of_single_days = d.get("to") - d.get("from") + 1

            elif d.charge == "Double":
                no_of_double_days = d.get("to") - d.get("from") + 1
                
    for row in container_doc.container_dates:
        if (
            row.is_billable == 1 and
            container_doc.has_single_charge == 1 and
            single_charge_count < no_of_single_days
        ):
            single_days.append(row)
            single_charge_count += 1
        
        elif (
            row.is_billable == 1 and
            container_doc.has_double_charge == 1 and
            single_charge_count >= no_of_single_days and
            double_charge_count <= no_of_double_days
        ):
            double_days.append(row)
            double_charge_count += 1
    
    single_days = [row.name for row in single_days if not row.sales_invoice]
    double_days = [row.name for row in double_days if not row.sales_invoice]
    return single_days, double_days


def get_service_order_items(
    doc_type=None,
    doc_name=None,
    m_bl_no=None,
):
    items = []
    service_docs = []

    if m_bl_no:
        service_docs = get_service_orders(m_bl_no)
    
    if len(service_docs) == 0:
        if not doc_type or not doc_name:
            return None, None
        
        source_doc = frappe.get_cached_doc(doc_type, doc_name)
        service_docs.append(source_doc)

    for doc in service_docs:
        items += get_items(doc)
        
    return items, service_docs


def get_service_orders(m_bl_no):
    service_docs = []

    filters = {
        "m_bl_no": m_bl_no,
    }
    orders = frappe.db.get_all(
        "Service Order",
        filters=filters,
        fields=["name", "docstatus"]
    )
    if len(orders) == 0:
        return []
    
    draft_service_orders = [order for order in orders if order.docstatus == 0]
    if len(draft_service_orders) > 0:
        frappe.throw(f"Please submit all draft Service Orders for M BL No: <b>{m_bl_no}</b>")

    for entry in orders:
        source_doc = frappe.get_cached_doc("Service Order", entry.name)
        service_docs.append(source_doc)

    return service_docs
    

def get_items(doc):
    items = []
    for item in doc.get("services"):
        row_item = {
            'item_code': item.get("service"),
            'qty': 1,
            'container_no': doc.container_no,
            'container_id': doc.container_id
        }
        items.append(row_item)
    
    return items



@frappe.whitelist()
def create_sales_order(data):
	data = frappe.parse_json(data)
    
	return make_sales_order(m_bl_no=data.get("m_bl_no"))
