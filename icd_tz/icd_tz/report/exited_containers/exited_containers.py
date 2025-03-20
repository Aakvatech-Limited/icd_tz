# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt

# import frappe

import frappe
from frappe import _


def execute(filters=None):
    """
    Main execution function for the Exited Containers report
    Args:
        filters (dict): Filter parameters
    Returns:
        tuple: (columns, data)
    """
    columns=get_columns()
    data= get_data(filters)
    return columns, data

def get_columns():
    """
    Define and return columns for the report
    Returns:
        list: List of column dictionaries
    """
    return [
        {
            "fieldname": "bl_no",
            "label": _("M B/L No"),
            "fieldtype": "Data", 
            "width": 120
        },
        {
            "fieldname": "container_no",
            "label": _("Container No"),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "type_of_container",
            "label": _("Cargo Type"),
            "fieldtype": "Data",
            "width": 100
        },
        {
            "fieldname": "received_date",
            "label": _("Carry In Date"),
            "fieldtype": "Date",
            "width": 100
        },
        {
            "fieldname": "arrival_date",
            "label": _("Ship D/C Date"),
            "fieldtype": "Date",
            "width": 100
        },
        {
            "fieldname": "submitted_date",
            "label": _("Carryout Date"),
            "fieldtype": "Date",
            "width": 100
        },
        {
            "fieldname": "port_of_destination",
            "label": _("Port Operator"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "consignee_name",
            "label": _("Consignee Name"),
            "fieldtype": "Data",
            "width": 200
        },
        {
            "fieldname": "goods_description",
            "label": _("Description of Goods"),
            "fieldtype": "Data",
            "width": 200
        },
        {
            "fieldname": "shipping_line",
            "label": _("Shipping Line"),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "vessel_name",
            "label": _("Vessel"),
            "fieldtype": "Data",
            "width": 120
        }
    ]
    
def get_data(filters):
    """
    Fetch and return report data for Exited Containers
    Args:
        filters (dict): Filter parameters
    Returns:
        list: List of dictionaries containing report data
    """
    
    conditions = get_conditions(filters)
        
    query = f"""
        SELECT
            c.m_bl_no as bl_no,
            c.container_no,
            c.received_date,
            c.arrival_date,
            gp.submitted_date,
            c.port_of_destination,
            IFNULL(c.consignee, gp.consignee) as consignee_name,
            IFNULL(gp.goods_description, c.cargo_description) as goods_description,
            IFNULL(c.sline, gp.sline) as shipping_line,
            gp.vessel_name
        FROM 
            `tabContainer` c
        LEFT JOIN
            `tabGate Pass` gp ON c.name = gp.container_id
        WHERE 
            gp.docstatus = 1 
            {conditions}
        ORDER BY 
            c.modified DESC
    """.format(conditions=conditions)
        
    data=frappe.db.sql(query, filters, as_dict=1)
    return data
        

def get_conditions(filters):
    """
    Generate SQL conditions based on filters
    Args:
        filters (dict): Filter parameters
    Returns:
        str: SQL WHERE conditions
    """    
    conditions = []
    
    if filters.get("from_date"):
        conditions.append("c.arrival_date >= %(from_date)s")
        
    if filters.get("to_date"):
        conditions.append("c.arrival_date <= %(to_date)s")
    
    if filters.get("bl_no"):
        conditions.append("c.m_bl_no = %(bl_no)s")
        
    return " AND " + " AND ".join(conditions) if conditions else ""

