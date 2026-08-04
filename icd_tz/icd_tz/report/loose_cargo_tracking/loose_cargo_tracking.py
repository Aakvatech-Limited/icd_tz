# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt


import frappe


def execute(filters=None):
	filters = filters or {}
	columns = get_columns(filters)
	data = get_data(filters)
	return columns, data


def get_columns(filters):
	report_type = filters.get("report_type", "Current Loose Stock")

	base_columns = [
		{"label": "M B/L Number", "fieldname": "bl_no", "fieldtype": "Data", "width": 150},
		{"label": "H B/L No", "fieldname": "h_bl_no", "fieldtype": "Data", "width": 150},
		{"label": "Discharge Date", "fieldname": "ship_dc_date", "fieldtype": "Date", "width": 120},
		{"label": "Carry In Date", "fieldname": "received_date", "fieldtype": "Date", "width": 120},
		{
			"label": "Description of Goods",
			"fieldname": "cargo_description",
			"fieldtype": "Small Text",
			"width": 250,
		},
		{"label": "Consignee Name", "fieldname": "consignee", "fieldtype": "Data", "width": 200},
		{"label": "No.of Packages", "fieldname": "no_of_packages", "fieldtype": "Data", "width": 200},
		{"label": "Cargo Type", "fieldname": "cargo_type", "fieldtype": "Data", "width": 200},
	]

	if report_type == "Exited Loose Cargo":
		base_columns.append(
			{"label": "Gate Out Date", "fieldname": "gate_out_date", "fieldtype": "Date", "width": 150}
		)

	if report_type == "Received Loose Cargo":
		base_columns.extend(
			[
				{"label": "Size", "fieldname": "size", "fieldtype": "Data", "width": 100},
				{"label": "Container No", "fieldname": "container_no", "fieldtype": "Data", "width": 150},
			]
		)

	return base_columns


def get_data(filters):
	report_type = filters.get("report_type", "Current Loose Stock")

	container = frappe.qb.DocType("Container")

	query = (
		frappe.qb.from_(container)
		.select(
			container.m_bl_no.as_("bl_no"),
			container.h_bl_no,
			container.ship_dc_date,
			container.received_date,
			container.cargo_description,
			container.consignee,
			container.no_of_packages,
			container.cargo_type,
		)
		.where(container.freight_indicator == "LCL")
		.where(container.has_hbl == 1)
	)

	# each report type is filtered on the date that drives it
	if report_type == "Exited Loose Cargo":
		query = query.select(container.gate_out_date).where(container.status == "Delivered")
		date_field = container.gate_out_date

	elif report_type == "Received Loose Cargo":
		query = query.select(container.size, container.container_no)
		date_field = container.posting_date

	else:
		query = query.where(container.status != "Delivered")
		date_field = container.received_date

	if filters.get("from_date"):
		query = query.where(date_field >= filters.get("from_date"))

	if filters.get("to_date"):
		query = query.where(date_field <= filters.get("to_date"))

	if filters.get("bl_no"):
		query = query.where(container.m_bl_no == filters.get("bl_no"))

	return query.run(as_dict=True)
