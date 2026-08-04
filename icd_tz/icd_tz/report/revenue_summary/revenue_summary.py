# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.utils import flt


def execute(filters=None):
	"""Main execution function for the report."""
	filters = filters or {}

	columns = get_columns(filters)
	data = get_data(filters)
	report_summary = get_report_summary(data, filters)

	return columns, data, None, None, report_summary


def get_columns(filters):
	"""Define the columns structure for the report."""
	base_columns = [
		{
			"fieldname": "receipt_no",
			"label": _("Receipt No"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 130,
		},
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "c_and_f_company", "label": _("C/Agent Company"), "fieldtype": "Data", "width": 150},
		{"fieldname": "clearing_agent", "label": _("C/Agent Name"), "fieldtype": "Data", "width": 150},
		{"fieldname": "vessel_name", "label": _("Vessel Name"), "fieldtype": "Data", "width": 150},
		{"fieldname": "container_no", "label": _("Container No"), "fieldtype": "Data", "width": 130},
		{"fieldname": "container_size", "label": _("Size"), "fieldtype": "Data", "width": 80},
		{"fieldname": "item_code", "label": _("Service"), "fieldtype": "Data", "width": 200},
	]

	currency = filters.get("currency")

	if not currency or currency == "TZS":
		base_columns.append(
			{"fieldname": "amount_tzs", "label": _("Amount (TZS)"), "fieldtype": "Float", "width": 130}
		)

	if not currency or currency == "USD":
		base_columns.append(
			{"fieldname": "amount_usd", "label": _("Amount (USD)"), "fieldtype": "Float", "width": 130}
		)

	base_columns.append({"fieldname": "vat", "label": _("VAT (TZS)"), "fieldtype": "Float", "width": 130})

	return base_columns


def get_data(filters):
	"""One row per Sales Invoice Item, priced in both the invoice and the company currency"""
	invoice = frappe.qb.DocType("Sales Invoice")
	invoice_item = frappe.qb.DocType("Sales Invoice Item")

	query = (
		frappe.qb.from_(invoice)
		.inner_join(invoice_item)
		.on(invoice_item.parent == invoice.name)
		.select(
			invoice.name.as_("receipt_no"),
			invoice.posting_date,
			invoice.currency,
			invoice.c_and_f_company,
			invoice.base_net_total,
			invoice.base_total_taxes_and_charges,
			invoice_item.item_code,
			invoice_item.container_id,
			invoice_item.container_no,
			invoice_item.amount,
			invoice_item.base_amount,
			invoice_item.base_net_amount,
		)
		.where(invoice.docstatus == 1)
		.orderby(invoice.posting_date, order=Order.desc)
	)

	if filters.get("from_date"):
		query = query.where(invoice.posting_date >= filters.get("from_date"))

	if filters.get("to_date"):
		query = query.where(invoice.posting_date <= filters.get("to_date"))

	if filters.get("m_bl_no"):
		query = query.where(invoice.m_bl_no == filters.get("m_bl_no"))

	if filters.get("currency"):
		query = query.where(invoice.currency == filters.get("currency"))

	rows = query.run(as_dict=True)

	container_ids = [row.container_id for row in rows if row.container_id]
	containers = get_container_details(container_ids)
	clearing_agents = get_clearing_agents(container_ids)

	for row in rows:
		container = containers.get(row.container_id) or {}
		row.vessel_name = container.get("ship")
		row.container_size = container.get("size")
		row.clearing_agent = clearing_agents.get(row.container_id)

		# base_ fields are always in company currency, the invoice currency keeps its own column
		row.amount_tzs = flt(row.base_amount)
		row.amount_usd = flt(row.amount) if row.currency == "USD" else 0

		# tax is only kept on the invoice, share it across its items so the column still adds up
		row.vat = 0
		if row.base_net_total:
			row.vat = (
				flt(row.base_total_taxes_and_charges) * flt(row.base_net_amount) / flt(row.base_net_total)
			)

	return rows


def get_container_details(container_ids):
	"""Vessel and size of every container on the report, keyed by container id"""
	if len(container_ids) == 0:
		return {}

	containers = frappe.db.get_all(
		"Container", filters={"name": ["in", container_ids]}, fields=["name", "ship", "size"]
	)

	return {container.name: container for container in containers}


def get_clearing_agents(container_ids):
	"""Clearing agent of every container on the report, taken from its Service Order"""
	if len(container_ids) == 0:
		return {}

	service_orders = frappe.db.get_all(
		"Service Order",
		filters={"container_id": ["in", container_ids], "docstatus": ["!=", 2]},
		fields=["container_id", "clearing_agent"],
	)

	return {order.container_id: order.clearing_agent for order in service_orders}


def get_report_summary(data, filters):
	"""Totals of the invoice lines shown on the report"""
	total_tzs = sum(flt(row.get("amount_tzs")) for row in data)
	total_usd = sum(flt(row.get("amount_usd")) for row in data)
	total_vat = sum(flt(row.get("vat")) for row in data)

	summary = [
		{"label": _("Invoices"), "value": len({row.get("receipt_no") for row in data}), "datatype": "Int"},
		{
			"label": _("Containers"),
			"value": len({row.get("container_no") for row in data if row.get("container_no")}),
			"datatype": "Int",
		},
	]

	currency = filters.get("currency")

	if not currency or currency == "TZS":
		summary.append(
			{
				"label": _("Amount (TZS)"),
				"value": total_tzs,
				"datatype": "Currency",
				"options": "TZS",
				"indicator": "Green",
			}
		)

	if not currency or currency == "USD":
		summary.append(
			{
				"label": _("Amount (USD)"),
				"value": total_usd,
				"datatype": "Currency",
				"options": "USD",
				"indicator": "Blue",
			}
		)

	summary.append(
		{
			"label": _("VAT (TZS)"),
			"value": total_vat,
			"datatype": "Currency",
			"options": "TZS",
			"indicator": "Orange",
		}
	)

	return summary
