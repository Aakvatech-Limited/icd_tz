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
            "fieldname": "bl_no",
            "label": _("M B/L No."),
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
            "fieldname": "received_date",
            "label": _("Date Out"),
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
    gp.submitted_date
  FROM 
    `tabGate Pass` AS gp
  LEFT JOIN
    `tabContainer` AS c ON gp.container_id = c.name
  WHERE 
    gp.docstatus = 1 
    {conditions}
  """
  return frappe.db.sql(query, filters, as_dict=True)


def get_conditions(filters):
  conditions = []
  if filters.get("m_bl_no"):
    conditions.append("gp.bl_no = %(m_bl_no)s")
  return " AND " + " AND ".join(conditions) if conditions else ""


