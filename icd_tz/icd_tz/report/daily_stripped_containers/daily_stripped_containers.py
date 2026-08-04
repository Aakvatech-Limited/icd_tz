# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt
import frappe
from frappe.query_builder import Order


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": "M B/L No", "fieldname": "m_bl_no", "fieldtype": "Data", "width": 150},
		{"label": "Container No", "fieldname": "container_no", "fieldtype": "Data", "width": 150},
		{"label": "Size", "fieldname": "size", "fieldtype": "Data", "width": 100},
		{"label": "Carry Out Date", "fieldname": "gate_out_date", "fieldtype": "Date", "width": 120},
		{"label": "Carry In Date", "fieldname": "received_date", "fieldtype": "Date", "width": 120},
		{"label": "Stripped Date", "fieldname": "last_inspection_date", "fieldtype": "Date", "width": 120},
	]


def get_data(filters):
	inspection = frappe.qb.DocType("Container Inspection")
	container = frappe.qb.DocType("Container")

	query = (
		frappe.qb.from_(inspection)
		.inner_join(container)
		.on(inspection.container_id == container.name)
		.select(
			container.m_bl_no,
			container.container_no,
			container.size,
			container.gate_out_date,
			container.received_date,
			container.last_inspection_date,
		)
		.where(inspection.docstatus == 1)
		.where(container.has_hbl == 0)
		.orderby(container.last_inspection_date, order=Order.desc)
	)

	# last_inspection_date is stamped once the inspection is done, it is the stripping date
	if filters.get("from_date"):
		query = query.where(container.last_inspection_date >= filters.get("from_date"))

	if filters.get("to_date"):
		query = query.where(container.last_inspection_date <= filters.get("to_date"))

	if filters.get("m_bl_no"):
		query = query.where(container.m_bl_no == filters.get("m_bl_no"))

	return query.run(as_dict=True)
