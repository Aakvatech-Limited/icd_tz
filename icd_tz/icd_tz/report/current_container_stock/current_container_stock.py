# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	columns, data = get_columns(), get_data(filters)
	return columns, data


def get_columns():
    return [
        {
            "fieldname": "container_no",
            "label": _("Container No."),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "m_bl_no",
            "label": _("B/L No."),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "size",
            "label": _("Size (FT)"),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "consignee",
            "label": _("Consignee"),
            "fieldtype": "Link",
            "options": "Consignee",
            "width": 150
        },
        {
            "fieldname": "status",
            "label": _("Status"),
            "fieldtype": "Select",
            "options": [
				"In Yard", 
				"In Transit", 
				"At Port", 
				"Delivered", 
				"On Hold"
			],
            "width": 150
        },
        {
            "fieldname": "port",
            "label": _("Port Operator"),
            "fieldtype": "Select",
            "options": [
				"DP WORLD", 
				"TEAGTL"
			],
            "width": 160
        },
        {
            "fieldname": "ship",
            "label": _("Shipping Line"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "ship_dc_date",
            "label": _("Discharge Date"),
            "fieldtype": "Date",
            "width": 150
        },
        {
            "fieldname": "received_date",
            "label": _("Carry In Date"),
            "fieldtype": "Date",
            "width": 150
        },
        {
            "fieldname": "cargo_type",
            "label": _("Cargo Type"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "vessel_name",
            "label": _("Vessel Name"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "goods_description",
            "label": _("Goods Description"),
            "fieldtype": "Small Text",
            "width": 200
        }
    ]
 

 
def get_data(filters=None):
    # Define status groups
    in_house_statuses = ["In Yard", "At Booking", "At Inspection", "At Payments"]
    delivered_statuses = ["Delivered"]

    # Initialize conditions list and parameters
    conditions = []
    params = []

    # Apply filters based on status_filter
    if filters and filters.get("status_filter"):
        status_filter = filters["status_filter"]
        if status_filter == "In House":
            conditions.append(f"c.status IN ({', '.join(['%s'] * len(in_house_statuses))})")
            params.extend(in_house_statuses)
        elif status_filter == "Delivered":
            conditions.append(f"c.status IN ({', '.join(['%s'] * len(delivered_statuses))})")
            params.extend(delivered_statuses)
    else:
        # Default condition to exclude 'Delivered' status
        conditions.append(f"c.status NOT IN ({', '.join(['%s'] * len(delivered_statuses))})")
        params.extend(delivered_statuses)

    # Combine conditions into a single string
    where_clause = " AND ".join(conditions) if conditions else "1=1"

    sql_query = f"""
    SELECT 
        c.container_no,
        c.m_bl_no,
        c.size,
        c.consignee,
        c.status,
        c.container_reception,
        cr.port,
        cr.ship,
        cr.name,
        cr.ship_dc_date,
        cr.received_date,
        cr.cargo_type,
        gp.goods_description,
        gp.vessel_name
    FROM 
        `tabContainer` AS c
    LEFT JOIN 
        `tabContainer Reception` AS cr ON c.container_reception = cr.name
    LEFT JOIN
		`tabGate Pass` As gp ON c.name = gp.container_id
    WHERE {where_clause}
    """

    return frappe.db.sql(sql_query, params, as_dict=True)   
