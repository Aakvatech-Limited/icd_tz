# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt
import frappe

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns():
    return [
        {"label": "M B/L Number", "fieldname": "m_bl_no", "fieldtype": "Data", "width": 150},
        {"label": "Container No", "fieldname": "container_no", "fieldtype": "Data", "width": 150},
        {"label": "Size", "fieldname": "size", "fieldtype": "Data", "width": 100},
        {"label": "Carry Out Date", "fieldname": "posting_datetime", "fieldtype": "Date", "width": 120},
        {"label": "Carry In Date", "fieldname": "received_date", "fieldtype": "Date", "width": 120},
        {"label": "Stripped Date", "fieldname": "last_inspection_date", "fieldtype": "Date", "width": 120}
    ]

def get_data(filters):
    conditions = []
    if filters.get('from_date'):
        conditions.append(f"c.arrival_date >= '{filters['from_date']}'")
    if filters.get('to_date'):
        conditions.append(f"c.arrival_date <= '{filters['to_date']}'")
    if filters.get('m_bl_no'):
        conditions.append(f"g.m_bl_no = '{filters['m_bl_no']}'")
    
    query_conditions = " AND ".join(conditions)
    query = f"""
        SELECT
            g.m_bl_no,
            g.container_no,
            c.size,
            g.posting_datetime,
            c.received_date,
            c.last_inspection_date
        FROM `tabContainer Inspection` g
        JOIN `tabContainer` c ON g.container_id = c.name
        WHERE 1=1
        {' AND ' + query_conditions if query_conditions else ''}
    """
    
    return frappe.db.sql(query, as_dict=1)