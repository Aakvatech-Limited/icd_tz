# Copyright (c) 2026, ICD TZ and contributors
# For license information, please see license.txt

import frappe
from frappe import _


STATUS_FLOW = (
	"In Yard",
	"At Booking",
	"At Inspection",
	"At Payments",
	"At Gate Confirmation",
	"Delivered",
)

CHART_LABEL_MAP = {
	"At Gate Confirmation": "At Gate Conf.",
}


def execute(filters=None):
	filters = normalize_filters(filters)
	columns = get_columns()
	data = get_data()
	chart = get_chart_data(data)
	return columns, data, None, chart


def normalize_filters(filters):
	"""Handle dashboard/chart filters that may come as JSON string or list."""
	if not filters:
		return frappe._dict()

	parsed_filters = frappe.parse_json(filters) if isinstance(filters, str) else filters
	if isinstance(parsed_filters, dict):
		return frappe._dict(parsed_filters)

	# Ignore list-style filters for this fixed-order report.
	return frappe._dict()


def get_columns():
	return [
		{
			"fieldname": "status",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 190,
		},
		{
			"fieldname": "count",
			"label": _("Containers"),
			"fieldtype": "Int",
			"width": 130,
		},
	]


def get_data():
	rows = []
	for status in STATUS_FLOW:
		count = frappe.db.count(
			"Container",
			{
				"docstatus": ["!=", 2],
				"status": status,
			},
		)
		rows.append({"status": status, "count": count})

	return rows


def get_chart_data(data):
	labels = []
	for row in data:
		status = row.get("status")
		labels.append(CHART_LABEL_MAP.get(status, status))

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{
					"name": _("Containers"),
					"values": [row.get("count") for row in data],
				}
			],
		},
		"type": "pie",
		"height": 280,
		"colors": ["#2563EB", "#22C55E", "#F59E0B", "#EF4444", "#8B5CF6", "#06B6D4"],
	}
