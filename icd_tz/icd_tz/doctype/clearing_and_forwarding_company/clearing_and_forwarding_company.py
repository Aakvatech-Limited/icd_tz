# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ClearingandForwardingCompany(Document):
	def create_customer(self):
		"""Create a customer from this company for billing. Not called on insert by design."""
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": self.company_name,
				"customer_group": "All Customer Groups",
				"territory": "All Territories",
				"customer_type": "Company",
				"mobile_no": self.phone,
				"email_id": self.email,
				"tax_id": self.tin,
				"vrn": self.vrn,
				"primary_address": self.physical_address,
			}
		)

		customer.flags.ignore_permissions = True
		customer.insert()

		self.customer = customer.name
		self.save()
		self.reload()

		return customer
