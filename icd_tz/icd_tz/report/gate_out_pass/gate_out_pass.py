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
            "fieldname": "h_bl_no",
            "label": _("H B/L No."),
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
            "fieldname": "vessel_name",
            "label": _("Vessel Name"),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "c_and_f_company",
            "label": _("C & F Company"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "voyage_no",
            "label": _("Voyage No"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "sline",
            "label": _("Sline"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "consignee",
            "label": _("Consignee"),
            "fieldtype": "Link",
            "options": "Consignee",
            "width": 150
        },
        {
            "fieldname": "freight_indicator",
            "label": _("Status"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "place_of_destination",
            "label": _("Destination"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "ship_dc_date",
            "label": _("Ship D/C Date"),
            "fieldtype": "Date",
            "width": 150
        },
        {
            "fieldname": "arrival_date",
            "label": _("Date In"),
            "fieldtype": "Date",
            "width": 150
        },
        {
            "fieldname": "gate_out_date",
            "label": _("Gate Out Date"),
            "fieldtype": "Date",
            "width": 150
        }
    ]


def get_data(filters=None):
  conditions = get_conditions(filters)
  query = f"""
  SELECT 
    gp.container_no,
    gp.m_bl_no,
    gp.h_bl_no,
    gp.size,
    gp.consignee,
    gp.sline,
    gp.c_and_f_company,
    gp.vessel_name,
    gp.voyage_no,
    c.freight_indicator,
    c.place_of_destination,
    gp.ship_dc_date,
    c.arrival_date,
    gp.gate_out_date
  FROM 
    `tabGate Pass` AS gp
  JOIN
    `tabContainer` AS c ON gp.container_id = c.name
  WHERE 
    gp.docstatus = 1
    AND gp.workflow_state = 'Gate Out Confirmed'
    {conditions}
  """
  return frappe.db.sql(query, filters, as_dict=True)


def get_conditions(filters):
  filters = filters or {}
  conditions = []
  if filters.get("m_bl_no"):
    conditions.append("gp.m_bl_no = %(m_bl_no)s")
  if filters.get("h_bl_no"):
    conditions.append("gp.h_bl_no = %(h_bl_no)s")
  if filters.get("from_date"):
    conditions.append("gp.gate_out_date >= %(from_date)s")
  if filters.get("to_date"):
    conditions.append("gp.gate_out_date <= %(to_date)s")
  return " AND " + " AND ".join(conditions) if conditions else ""
