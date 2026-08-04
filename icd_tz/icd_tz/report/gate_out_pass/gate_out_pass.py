# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import Order


def execute(filters=None):
	columns, data = get_columns(), get_data(filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "container_no", "label": _("Container No."), "fieldtype": "Data", "width": 120},
		{"fieldname": "m_bl_no", "label": _("M B/L No."), "fieldtype": "Data", "width": 120},
		{"fieldname": "h_bl_no", "label": _("H B/L No."), "fieldtype": "Data", "width": 120},
		{"fieldname": "size", "label": _("Size (FT)"), "fieldtype": "Data", "width": 120},
		{"fieldname": "vessel_name", "label": _("Vessel Name"), "fieldtype": "Data", "width": 120},
		{"fieldname": "c_and_f_company", "label": _("C & F Company"), "fieldtype": "Data", "width": 150},
		{"fieldname": "voyage_no", "label": _("Voyage No"), "fieldtype": "Data", "width": 150},
		{"fieldname": "sline", "label": _("Sline"), "fieldtype": "Data", "width": 150},
		{
			"fieldname": "consignee",
			"label": _("Consignee"),
			"fieldtype": "Link",
			"options": "Consignee",
			"width": 150,
		},
		{"fieldname": "container_status", "label": _("Status"), "fieldtype": "Data", "width": 150},
		{"fieldname": "place_of_destination", "label": _("Destination"), "fieldtype": "Data", "width": 150},
		{"fieldname": "ship_dc_date", "label": _("Ship D/C Date"), "fieldtype": "Date", "width": 150},
		{"fieldname": "received_date", "label": _("Date In"), "fieldtype": "Date", "width": 150},
		{"fieldname": "gate_out_date", "label": _("Gate Out Date"), "fieldtype": "Datetime", "width": 150},
	]


def get_data(filters=None):
	filters = filters or {}

	gate_pass = frappe.qb.DocType("Gate Pass")
	# Destination is the only column that is not kept on the Gate Pass
	container = frappe.qb.DocType("Container")

	query = (
		frappe.qb.from_(gate_pass)
		.left_join(container)
		.on(gate_pass.container_id == container.name)
		.select(
			gate_pass.container_no,
			gate_pass.m_bl_no,
			gate_pass.h_bl_no,
			gate_pass.size,
			gate_pass.consignee,
			gate_pass.sline,
			gate_pass.c_and_f_company,
			gate_pass.vessel_name,
			gate_pass.voyage_no,
			gate_pass.container_status,
			gate_pass.ship_dc_date,
			gate_pass.received_date,
			container.place_of_destination,
			gate_pass.gate_out_date,
		)
		.where(gate_pass.docstatus == 1)
		.where(gate_pass.gate_out_date.isnotnull())
		.orderby(gate_pass.gate_out_date, order=Order.desc)
	)

	if filters.get("m_bl_no"):
		query = query.where(gate_pass.m_bl_no == filters.get("m_bl_no"))

	if filters.get("h_bl_no"):
		query = query.where(gate_pass.h_bl_no == filters.get("h_bl_no"))

	if filters.get("from_date"):
		query = query.where(gate_pass.gate_out_date >= filters.get("from_date"))

	if filters.get("to_date"):
		query = query.where(gate_pass.gate_out_date <= filters.get("to_date"))

	return query.run(as_dict=True)
