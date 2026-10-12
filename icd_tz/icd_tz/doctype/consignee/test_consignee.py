# Copyright (c) 2024, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

CONSIGNEE_NAME = "_Test ICD Consignee"


class TestConsignee(FrappeTestCase):
	"""The Create Customer button on one consignee"""

	def tearDown(self):
		frappe.db.rollback()

	def make_consignee(self, customer=None):
		consignee = frappe.new_doc("Consignee")
		consignee.update(
			{"consignee_name": CONSIGNEE_NAME, "consignee_tin": "123456789", "customer": customer}
		)
		consignee.flags.ignore_links = True
		consignee.insert(ignore_permissions=True)

		return consignee

	def test_a_customer_is_created_and_linked(self):
		consignee = self.make_consignee()

		customer = consignee.create_customer()

		self.assertEqual(frappe.db.get_value("Customer", customer, "customer_name"), CONSIGNEE_NAME)
		self.assertEqual(frappe.db.get_value("Consignee", consignee.name, "customer"), customer)

	def test_a_customer_with_the_same_name_is_reused(self):
		consignee = self.make_consignee()
		first = consignee.create_customer()
		frappe.db.set_value("Consignee", consignee.name, "customer", None)
		consignee.reload()

		self.assertEqual(consignee.create_customer(), first)
		self.assertEqual(frappe.db.count("Customer", {"customer_name": CONSIGNEE_NAME}), 1)

	def test_a_linked_consignee_is_refused(self):
		consignee = self.make_consignee(customer="_Test Linked Customer")

		self.assertRaises(frappe.ValidationError, consignee.create_customer)
