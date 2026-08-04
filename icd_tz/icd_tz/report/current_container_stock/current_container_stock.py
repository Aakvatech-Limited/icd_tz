# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	columns, data = get_columns(), get_data(filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "container_no", "label": _("Container No."), "fieldtype": "Data", "width": 120},
		{"fieldname": "m_bl_no", "label": _("B/L No."), "fieldtype": "Data", "width": 130},
		{"fieldname": "size", "label": _("Size"), "fieldtype": "Data", "width": 70},
		{
			"fieldname": "manifest",
			"label": _("Manifest"),
			"fieldtype": "Link",
			"options": "Manifest",
			"width": 150,
		},
		{
			"fieldname": "consignee",
			"label": _("Consignee"),
			"fieldtype": "Link",
			"options": "Consignee",
			"width": 160,
		},
		{
			"fieldname": "status",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "port",
			"label": _("Port Operator"),
			"fieldtype": "Data",
			"width": 120,
		},
		{"fieldname": "vessel_name", "label": _("Vessel Name"), "fieldtype": "Data", "width": 150},
		{"fieldname": "shipping_line", "label": _("Shipping Line"), "fieldtype": "Data", "width": 150},
		{"fieldname": "ship_dc_date", "label": _("Discharge Date"), "fieldtype": "Date", "width": 120},
		{"fieldname": "received_date", "label": _("Carry In Date"), "fieldtype": "Date", "width": 120},
		{"fieldname": "cargo_type", "label": _("Cargo Type"), "fieldtype": "Data", "width": 80},
		{
			"fieldname": "cargo_description",
			"label": _("Goods Description"),
			"fieldtype": "Small Text",
			"width": 200,
		},
	]


def get_data(filters=None):
	container = frappe.qb.DocType("Container")

	query = (
		frappe.qb.from_(container)
		.select(
			container.container_no,
			container.m_bl_no,
			container.size,
			container.manifest,
			container.consignee,
			container.status,
			container.cargo_description,
			container.port_of_destination.as_("port"),
			container.ship.as_("vessel_name"),
			container.sline.as_("shipping_line"),
			container.ship_dc_date,
			container.received_date,
			container.cargo_type,
		)
		.where(container.has_hbl == 0)
	)

	status_filter = filters.get("status_filter") if filters else None

	# a container that is not Delivered is still in house
	if status_filter == "Delivered":
		query = query.where(container.status == "Delivered")
	else:
		query = query.where(container.status != "Delivered")

	return query.run(as_dict=True)
