# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import Order


def execute(filters=None):
	"""
	Main execution function for the Received Containers report
	Args:
	    filters (dict): Filter parameters
	Returns:
	    tuple: (columns, data)
	"""
	columns = get_columns()
	data = get_data(filters)

	return columns, data


def get_columns():
	"""Define columns for the report"""
	return [
		{"fieldname": "bl_no", "label": _("M B/L No."), "fieldtype": "Data", "width": 120},
		{"fieldname": "ship_dc_date", "label": _("Discharge Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "port_of_destination", "label": _("Port Operator"), "fieldtype": "Data", "width": 120},
		{"fieldname": "cargo_type", "label": _("Cargo Type"), "fieldtype": "Data", "width": 100},
		{"fieldname": "container_no", "label": _("Container No."), "fieldtype": "Data", "width": 120},
		{"fieldname": "size", "label": _("Size"), "fieldtype": "Data", "width": 80},
		{"fieldname": "consignee_name", "label": _("Consignee Name"), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "description_of_goods",
			"label": _("Description of Goods"),
			"fieldtype": "Data",
			"width": 200,
		},
		{"fieldname": "sline", "label": _("Shipping Line"), "fieldtype": "Data", "width": 120},
		{"fieldname": "ship", "label": _("Vessel"), "fieldtype": "Data", "width": 120},
		{"fieldname": "transporter", "label": _("Transporter"), "fieldtype": "Data", "width": 120},
	]


def get_data(filters=None):
	"""
	Fetch and return report data
	Args:
	    filters (dict): Filter parameters
	Returns:
	    list: List of dictionaries containing report data
	"""
	filters = filters or {}

	container = frappe.qb.DocType("Container")
	reception = frappe.qb.DocType("Container Reception")

	query = (
		frappe.qb.from_(container)
		.inner_join(reception)
		.on(container.container_reception == reception.name)
		.select(
			container.m_bl_no.as_("bl_no"),
			container.ship_dc_date,
			container.port_of_destination,
			container.cargo_type,
			container.container_no,
			container.size,
			container.consignee.as_("consignee_name"),
			container.cargo_description.as_("description_of_goods"),
			container.sline,
			container.ship,
			reception.transporter,
		)
		.where(container.has_hbl == 0)
		.orderby(container.posting_date, order=Order.desc)
	)

	if filters.get("from_date"):
		query = query.where(container.posting_date >= filters.get("from_date"))

	if filters.get("to_date"):
		query = query.where(container.posting_date <= filters.get("to_date"))

	if filters.get("bl_no"):
		query = query.where(container.m_bl_no == filters.get("bl_no"))

	return query.run(as_dict=True)
