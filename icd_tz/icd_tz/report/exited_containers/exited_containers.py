# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt

# import frappe

import frappe
from frappe import _
from frappe.query_builder import Order


def execute(filters=None):
	"""
	Main execution function for the Exited Containers report
	Args:
	    filters (dict): Filter parameters
	Returns:
	    tuple: (columns, data)
	"""
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	"""
	Define and return columns for the report
	Returns:
	    list: List of column dictionaries
	"""
	return [
		{"fieldname": "m_bl_no", "label": _("M B/L No"), "fieldtype": "Data", "width": 120},
		{"fieldname": "h_bl_no", "label": _("H B/L No"), "fieldtype": "Data", "width": 120},
		{"fieldname": "container_no", "label": _("Container No"), "fieldtype": "Data", "width": 120},
		{"fieldname": "cargo_type", "label": _("Cargo Type"), "fieldtype": "Data", "width": 100},
		{"fieldname": "received_date", "label": _("Carry In Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "ship_dc_date", "label": _("Ship D/C Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "gate_out_date", "label": _("Carryout Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "port_of_destination", "label": _("Port Operator"), "fieldtype": "Data", "width": 150},
		{"fieldname": "consignee", "label": _("Consignee Name"), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "goods_description",
			"label": _("Description of Goods"),
			"fieldtype": "Data",
			"width": 200,
		},
		{"fieldname": "shipping_line", "label": _("Shipping Line"), "fieldtype": "Data", "width": 120},
		{"fieldname": "vessel_name", "label": _("Vessel"), "fieldtype": "Data", "width": 120},
	]


def get_data(filters=None):
	"""
	Fetch and return report data for Exited Containers
	Args:
	    filters (dict): Filter parameters
	Returns:
	    list: List of dictionaries containing report data
	"""
	filters = filters or {}

	container = frappe.qb.DocType("Container")

	query = (
		frappe.qb.from_(container)
		.select(
			container.m_bl_no,
			container.h_bl_no,
			container.container_no,
			container.cargo_type,
			container.received_date,
			container.ship_dc_date,
			container.gate_out_date,
			container.port_of_destination,
			container.consignee,
			container.cargo_description.as_("goods_description"),
			container.sline.as_("shipping_line"),
			container.ship.as_("vessel_name"),
		)
		.where(container.status == "Delivered")
		.where(container.has_hbl == 0)
		.orderby(container.gate_out_date, order=Order.desc)
	)

	if filters.get("from_date"):
		query = query.where(container.gate_out_date >= filters.get("from_date"))

	if filters.get("to_date"):
		query = query.where(container.gate_out_date <= filters.get("to_date"))

	if filters.get("bl_no"):
		query = query.where(container.m_bl_no == filters.get("bl_no"))

	return query.run(as_dict=True)
