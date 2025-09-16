# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt


import frappe

def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data

def get_columns(filters):
    report_type = filters.get('report_type', 'Current Loose Stock')
    
    base_columns = [
        {"label": "M B/L Number", "fieldname": "bl_no", "fieldtype": "Data", "width": 150},
        {"label": "H B/L No", "fieldname": "h_bl_no", "fieldtype": "Data", "width": 150},
        {"label": "Discharge Date", "fieldname": "arrival_date", "fieldtype": "Date", "width": 120},
        {"label": "Carry In Date", "fieldname": "received_date", "fieldtype": "Date", "width": 120},
        {"label": "Description of Goods", "fieldname": "cargo_description", "fieldtype": "Small Text", "width": 250},
        {"label": "Consignee Name", "fieldname": "consignee", "fieldtype": "Data", "width": 200},
        {"label": "No.of Packages", "fieldname": "no_of_packages", "fieldtype": "Data", "width": 200},
        {"label": "Cargo Type", "fieldname": "cargo_type", "fieldtype": "Data", "width": 200}
    ]
    
    if report_type == 'Exited Loose Cargo':
        base_columns.append({
            "label": "Gate Out Date", 
            "fieldname": "gate_out_date", 
            "fieldtype": "Datetime", 
            "width": 150
        })
    
    if report_type == 'Received Loose Cargo':
        base_columns.extend([
            {"label": "Size", "fieldname": "size", "fieldtype": "Data", "width": 100},
            {"label": "Container No", "fieldname": "container_no", "fieldtype": "Data", "width": 150}
        ])
    
    return base_columns

def get_data(filters):
    report_type = filters.get('report_type', 'Current Loose Stock')
    from_date = filters.get('from_date')
    to_date = filters.get('to_date')
    bl_no = filters.get('bl_no')

    conditions = ["c.freight_indicator = 'LCL'"]

    if from_date:
        conditions.append(f"c.arrival_date >= '{from_date}'")
    if to_date:
        conditions.append(f"c.arrival_date <= '{to_date}'")
    if bl_no:
        conditions.append(f"c.m_bl_no = '{bl_no}'")

    query_conditions = " AND ".join(conditions)

    if report_type == 'Current Loose Stock':
        query = f"""
            SELECT 
                c.m_bl_no as bl_no,
                c.h_bl_no,
                c.arrival_date,
                c.received_date,
                c.cargo_description,
                c.consignee,
                c.no_of_packages,
                c.cargo_type
            FROM `tabContainer` c
            WHERE {query_conditions}
            AND c.status= 'In Yard'
        """

    elif report_type == 'Exited Loose Cargo':
        query = f"""
            SELECT 
                c.m_bl_no as bl_no,
                c.h_bl_no,
                c.arrival_date,
                c.received_date,
                c.cargo_description,
                c.consignee,
                c.no_of_packages,
                c.cargo_type,
                CONCAT(g.submitted_date, ' ', g.submitted_time) as gate_out_date
            FROM `tabContainer` c
            JOIN `tabGate Pass` g ON c.m_bl_no = g.bl_no
            WHERE {query_conditions}
            AND c.status != 'In Yard' AND g.docstatus = 1 AND g.workflow_state = 'Gate Out Confirmed'
        """

    elif report_type == 'Received Loose Cargo':
        query = f"""
            SELECT 
                c.m_bl_no as bl_no,
                c.h_bl_no,
                c.arrival_date,
                c.received_date,
                c.cargo_description,
                c.consignee,
                c.no_of_packages,
                c.size,
                c.container_no,
                c.cargo_type
            FROM `tabContainer` c
            WHERE {query_conditions}
        """

    return frappe.db.sql(query, as_dict=1)
