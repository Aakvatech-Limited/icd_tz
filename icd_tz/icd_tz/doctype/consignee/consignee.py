# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import create_batch


class Consignee(Document):
	pass


def create_customer():
	"""
	Create a customer from the consignee for billing purposes
	"""

	consignees = frappe.db.get_all("Consignee", filters={"customer": ["=", ""]}, fields=["*"])

	for records in create_batch(consignees, 100):
		for row in records:
			customer = frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": row.consignee_name,
					"customer_group": "All Customer Groups",
					"territory": "All Territories",
					"customer_type": "Company",
					"mobile_no": row.consignee_tel,
					"tax_id": row.consignee_tin,
					"primary_address": row.consignee_address,
				}
			)

			if frappe.get_meta("Customer").get_field("vfd_cust_id"):
				customer.vfd_cust_id = row.consignee_tin
				customer.vfd_cust_id_type = "1- TIN"

			customer.flags.ignore_permissions = True
			customer.insert()
			customer.reload()

			frappe.db.set_value("Consignee", row.name, "customer", customer.name)
