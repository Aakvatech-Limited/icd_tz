# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


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
		{"fieldname": "c_and_f_company", "label": _("C/Agent Company"), "fieldtype": "Data", "width": 150},
		{"fieldname": "clearing_agent", "label": _("C/Agent Name"), "fieldtype": "Data", "width": 150},
		{"fieldname": "vessel_name", "label": _("Vessel Name"), "fieldtype": "Data", "width": 150},
		{"fieldname": "d_do_no", "label": _("D/DO NO"), "fieldtype": "Data", "width": 120},
		{"fieldname": "container_size", "label": _("Size"), "fieldtype": "Data", "width": 100},
		{"fieldname": "containers", "label": _("Containers"), "fieldtype": "Int", "width": 50},
	]

	currency = filters.get("currency")
	if not currency:
		base_columns.extend(
			[
				{
					"fieldname": "amount_tzs",
					"label": _("Amount (TZS)"),
					"fieldtype": "Float",
					"width": 120,
					"precision": 2,
				},
				{
					"fieldname": "amount_usd",
					"label": _("Amount (USD)"),
					"fieldtype": "Float",
					"width": 120,
					"precision": 2,
				},
				{"fieldname": "vat", "label": _("VAT"), "fieldtype": "Float", "width": 120, "precision": 2},
			]
		)
	elif currency == "USD":
		base_columns.append(
			{
				"fieldname": "amount_usd",
				"label": _("Amount (USD)"),
				"fieldtype": "Float",
				"width": 120,
				"precision": 2,
			}
		)
	else:
		base_columns.append(
			{
				"fieldname": "amount_tzs",
				"label": _("Amount (TZS)"),
				"fieldtype": "Float",
				"width": 120,
				"precision": 2,
			}
		)

	return base_columns


def get_service_order_details(service_order):
	"""Retrieve service order details."""
	if not service_order:
		return {"vessel_name": "", "container_size": "", "c_and_f_company": "", "clearing_agent": ""}

	try:
		service_order_doc = frappe.get_doc("Service Order", service_order)
		return {
			"vessel_name": service_order_doc.vessel_name or "",
			"container_size": service_order_doc.container_size or "",
			"c_and_f_company": service_order_doc.c_and_f_company or "",
			"clearing_agent": service_order_doc.clearing_agent or "",
		}
	except Exception:
		frappe.log_error(f"Error fetching Service Order details for {service_order}")
		return {"vessel_name": "", "container_size": "", "c_and_f_company": "", "clearing_agent": ""}


def format_currency_amount(amount, currency):
	"""Format currency with proper prefix."""
	if amount == 0:
		return f"{currency} 0.00"
	return f"{currency} {flt(amount, 2):,.2f}"


def get_data(filters):
	"""Fetch and process report data."""
	conditions = []
	if filters.get("from_date"):
		conditions.append("si.posting_date >= %(from_date)s")
	if filters.get("to_date"):
		conditions.append("si.posting_date <= %(to_date)s")
	if filters.get("m_bl_no"):
		conditions.append("si.m_bl_no = %(m_bl_no)s")

	currency_filter = ""
	if filters.get("currency"):
		currency_filter = "AND si.currency = %(currency)s"

	conditions = " AND ".join(conditions) if conditions else "1=1"

	query = f"""
        SELECT
            si.posting_date AS date,
            #si.name AS receipt_no,
            si.service_order,
            si.currency,
            '' AS d_do_no,
            (SELECT COUNT(DISTINCT item.container_no)
             FROM `tabSales Invoice Item` item
             WHERE item.parent = si.name) AS containers,
            si.currency,
            CASE
                WHEN si.currency = 'TZS' THEN si.grand_total
                ELSE 0
            END AS raw_amount_tzs,
            CASE
                WHEN si.currency = 'USD' THEN si.grand_total
                ELSE 0
            END AS raw_amount_usd,
            si.total_taxes_and_charges AS raw_vat
        FROM `tabSales Invoice` si
        WHERE si.docstatus = 1 {currency_filter}
        AND {conditions}
        ORDER BY si.posting_date DESC
    """

	data = frappe.db.sql(query, filters, as_dict=1)

	# Process the data and format currencies
	processed_data = []
	for row in data:
		processed_row = row.copy()

		# Get service order details
		if row.service_order:
			processed_row.update(get_service_order_details(row.service_order))

		# Format currency amounts with proper prefix
		if row.currency == "USD":
			processed_row["amount_tzs"] = "TZS 0.00"
			processed_row["amount_usd"] = format_currency_amount(row.raw_amount_usd, "USD")
			processed_row["vat"] = format_currency_amount(row.raw_vat, "USD")
		else:  # TZS
			processed_row["amount_tzs"] = format_currency_amount(row.raw_amount_tzs, "TZS")
			processed_row["amount_usd"] = "USD 0.00"
			processed_row["vat"] = format_currency_amount(row.raw_vat, "TZS")

		processed_data.append(processed_row)

	return processed_data


def execute(filters=None):
	"""Main execution function for the report."""
	if not filters:
		filters = {}

	columns = get_columns(filters)
	data = get_data(filters)

	return columns, data
