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
            "fieldname": "cargo_type",
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
            "fieldname": "port_of_destination",
            "label": _("Port Operator"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "consignee",
            "label": _("Consignee Name"),
            "fieldtype": "Data",
            "width": 200
        },
        {
            "fieldname": "cargo_description",
            "label": _("Description of Goods"),
            "fieldtype": "Data",
            "width": 200
        },
        {
            "fieldname": "sline",
            "label": _("Shipping Line"),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "ship",
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
        
    query = f"""
        SELECT DISTINCT
            c.m_bl_no as bl_no,
            c.container_no,
            c.cargo_type,
            c.received_date,
            c.arrival_date,
            c.port_of_destination,
            c.consignee,
            c.cargo_description,
            c.sline,
            c.ship
        FROM 
            `tabContainer` c
        WHERE 
            c.arrival_date >= %(from_date)s AND c.arrival_date <= %(to_date)s
    """
        
    data=frappe.db.sql(query, filters, as_dict=1)
    return data
        


