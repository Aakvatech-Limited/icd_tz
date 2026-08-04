# Copyright (c) 2026, ICD TZ and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Count

# At Gate Confirmation is reported together with At Gatepass
STATUS_FLOW = {
	"In Yard": ["In Yard"],
	"At Booking": ["At Booking"],
	"At Inspection": ["At Inspection"],
	"At Payments": ["At Payments"],
	"At Gatepass": ["At Gatepass", "At Gate Confirmation"],
	"Delivered": ["Delivered"],
}


def execute(filters=None):
	columns = get_columns()
	data = get_data()
	chart = get_chart_data(data)
	return columns, data, None, chart


def get_columns():
	return [
		{
			"fieldname": "status",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 190,
		},
		{
			"fieldname": "containers",
			"label": _("Containers"),
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"fieldname": "loose_cargo",
			"label": _("Loose Cargo"),
			"fieldtype": "Int",
			"width": 130,
		},
	]


def get_data():
	container = frappe.qb.DocType("Container")

	counts = (
		frappe.qb.from_(container)
		.select(container.status, container.has_hbl, Count(container.name).as_("total"))
		.groupby(container.status, container.has_hbl)
	).run(as_dict=True)

	rows = []
	for status, grouped_statuses in STATUS_FLOW.items():
		matched = [count for count in counts if count.status in grouped_statuses]

		rows.append(
			{
				"status": status,
				"containers": sum(count.total for count in matched if count.has_hbl == 0),
				"loose_cargo": sum(count.total for count in matched if count.has_hbl == 1),
			}
		)

	return rows


def get_chart_data(data):
	return {
		"data": {
			"labels": [row.get("status") for row in data],
			"datasets": [
				{
					"name": _("Containers"),
					"values": [row.get("containers") for row in data],
				},
				{
					"name": _("Loose Cargo"),
					"values": [row.get("loose_cargo") for row in data],
				},
			],
		},
		"type": "bar",
		"height": 280,
		"colors": ["#2563EB", "#F59E0B"],
	}
