# Copyright (c) 2026, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from icd_tz.icd_tz.api.port_expenses import get_buying_rates
from icd_tz.icd_tz.api.transport_charges import (
	get_transport_price_list,
	get_transport_row,
	get_transport_rows,
	get_unpaid_transport_containers,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date"))

	containers = get_unpaid_transport_containers(
		filters.company, filters.transporter, filters.from_date, filters.to_date, filters.manifest
	)

	return get_columns(), get_rows(containers)


def get_columns() -> list:
	return [
		{"fieldname": "container_no", "label": _("Container No"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "manifest",
			"label": _("Manifest"),
			"fieldtype": "Link",
			"options": "Manifest",
			"width": 140,
		},
		{"fieldname": "received_date", "label": _("Received Date"), "fieldtype": "Date", "width": 110},
		{
			"fieldname": "transporter",
			"label": _("Transporter"),
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 160,
		},
		{"fieldname": "size", "label": _("Size"), "fieldtype": "Data", "width": 70},
		{"fieldname": "port", "label": _("Port"), "fieldtype": "Data", "width": 100},
		{
			"fieldname": "transport_item",
			"label": _("Transport Item"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 160,
		},
		{"fieldname": "rate", "label": _("Rate"), "fieldtype": "Currency", "width": 110},
		{
			"fieldname": "price_list",
			"label": _("Price List"),
			"fieldtype": "Link",
			"options": "Price List",
			"width": 160,
		},
	]


def get_rows(containers: list) -> list:
	"""One row per container, priced the way Get Transport Services would price it today"""

	criteria_rows = get_transport_rows()
	price_lists = {
		transporter: get_transport_price_list(transporter)[0]
		for transporter in {container.transporter for container in containers if container.transporter}
	}

	rows = []
	for container in containers:
		criteria_row = get_transport_row(container, criteria_rows)
		rows.append(
			{
				**container,
				"transport_item": criteria_row.expense_item if criteria_row else None,
				"price_list": price_lists.get(container.transporter),
			}
		)

	set_rates(rows)

	return rows


def set_rates(rows: list):
	"""The rate of each row on today, one price lookup per price list"""

	items_by_price_list = {}
	for row in rows:
		if row["transport_item"] and row["price_list"]:
			items_by_price_list.setdefault(row["price_list"], set()).add(row["transport_item"])

	rates = {
		price_list: get_buying_rates(items, price_list, nowdate())
		for price_list, items in items_by_price_list.items()
	}
	for row in rows:
		row["rate"] = rates.get(row["price_list"], {}).get(row["transport_item"])
