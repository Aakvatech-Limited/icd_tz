# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import create_batch

from icd_tz.icd_tz.api.utils import get_default_customer_group


class Consignee(Document):
	pass


def create_customer():
	"""
	Create a customer from the consignee for billing purposes
	"""

	consignees = frappe.db.get_all("Consignee", filters={"customer": ["=", ""]}, fields=["*"])

	for records in create_batch(consignees, 100):
		for row in records:
			if not row.consignee_name:
				continue

			# the customer may already exist, from an earlier consignee or from being added by hand
			customer_id = frappe.db.get_value("Customer", {"customer_name": row.consignee_name}, "name")

			if not customer_id:
				customer_id = create_customer_from_consignee(row)

			frappe.db.set_value("Consignee", row.name, "customer", customer_id)


def create_customer_from_consignee(consignee):
	"""Create the customer a consignee is billed through"""

	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": consignee.consignee_name,
			"customer_group": get_default_customer_group(),
			"territory": "All Territories",
			"customer_type": "Company",
			"mobile_no": consignee.consignee_tel,
			"tax_id": consignee.consignee_tin,
			"primary_address": consignee.consignee_address,
		}
	)

	if frappe.get_meta("Customer").get_field("vfd_cust_id"):
		customer.vfd_cust_id = consignee.consignee_tin
		customer.vfd_cust_id_type = "1- TIN"

	customer.flags.ignore_permissions = True
	customer.insert()

	return customer.name
