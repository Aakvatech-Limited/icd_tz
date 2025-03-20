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
            "label": _("M B/L No."),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "container_size",
            "label": _("Size"),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "c_and_f_company",
            "label": _("C & F Company"),
            "fieldtype": "Link",
            "options": "Clearing and Forwarding Company",
            "width": 150
        },
        {
            "fieldname": "seal",
            "label": _("Seal"),
            "fieldtype": "Data",
            "width": 360
        },
        {
            "fieldname": "posting_datetime",
            "label": _("Date"),
            "fieldtype": "Datetime",
            "width": 150
        },
        {
            "fieldname": "transporter",
            "label": _("Transporter"),
            "fieldtype": "Link",
            "options": "Transporter",
            "width": 150
        },
        {
            "fieldname": "truck",
            "label": _("Truck"),
            "fieldtype": "Link",
            "options": "Vehicle",
            "width": 150
        },
        {
            "fieldname": "trailer",
            "label": _("Trailer"),
            "fieldtype": "Link",
            "options": "Vehicle",
            "width": 150
        },
        {
            "fieldname": "driver",
            "label": _("Driver"),
            "fieldtype": "Link",
            "options": "Driver",
            "width": 150
        },
        {
            "fieldname": "driver_lisence",
            "label": _("Lisence"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "container_location",
            "label": _("Location"),
            "fieldtype": "Link",
            "options": "Container Location",
            "width": 150
        }
    ]

def get_data(filters):
    filters = filters or {}
    m_bl_no = filters.get('m_bl_no')
    
    conditions = "1=1"
    if m_bl_no:
        conditions += " AND cb.m_bl_no = %(m_bl_no)s"

    sql_query = f"""
    SELECT 
			cb.container_no,
			c.m_bl_no,
			cb.container_size,
			cb.c_and_f_company,
			cb.posting_datetime,
			CONCAT_WS(', ', c.seal_no_1, c.seal_no_2, c.seal_no_3) AS seal,
			cr.transporter,
			cr.truck,
			cr.trailer,
			cr.driver,
			cr.driver_lisence,
			cr.container_location
    FROM 
			`tabIn Yard Container Booking` AS cb
    LEFT JOIN
			`tabContainer` AS c ON cb.container_id = c.name
    LEFT JOIN
			`tabContainer Reception` AS cr ON c.container_reception = cr.name
    WHERE 
			{conditions}
    """
    return frappe.db.sql(sql_query, filters, as_dict=True)


