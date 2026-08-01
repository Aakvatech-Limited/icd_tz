# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.doctype.waiver_request.waiver_request import create_waiver_request, get_items


class TestWaiverRequest(FrappeTestCase):
	def setUp(self):
		self.sales_order = make_test_sales_order()

	def tearDown(self):
		frappe.db.rollback()

	def test_creating_waiver_request_marks_sales_order_pending(self):
		waiver_request = frappe.get_doc(
			"Waiver Request", create_and_get_waiver_request(self.sales_order.name)
		)

		self.sales_order.reload()
		self.assertEqual(self.sales_order.waiver_status, "Pending")
		self.assertRaises(frappe.ValidationError, self.sales_order.submit)
		self.assertEqual(waiver_request.docstatus, 0)

	def test_approving_waiver_request_applies_discount_on_sales_order(self):
		waiver_request = frappe.get_doc(
			"Waiver Request", create_and_get_waiver_request(self.sales_order.name, discount_amount=50)
		)
		waiver_request.decision = "Approved"
		waiver_request.submit()

		self.sales_order.reload()
		self.assertEqual(self.sales_order.waiver_status, "Approved")
		self.assertEqual(self.sales_order.apply_discount_on, "Grand Total")
		self.assertEqual(self.sales_order.discount_amount, 50)
		self.sales_order.submit()
		self.assertEqual(self.sales_order.docstatus, 1)

	def test_rejecting_waiver_request_does_not_apply_discount(self):
		waiver_request = frappe.get_doc(
			"Waiver Request", create_and_get_waiver_request(self.sales_order.name, discount_amount=50)
		)
		waiver_request.decision = "Rejected"
		waiver_request.submit()

		self.sales_order.reload()
		self.assertEqual(self.sales_order.waiver_status, "Rejected")
		self.assertEqual(self.sales_order.discount_amount, 0)
		self.sales_order.submit()
		self.assertEqual(self.sales_order.docstatus, 1)

	def test_approving_single_item_waiver_discounts_only_that_item(self):
		items = get_items(self.sales_order.name)
		target = items[0]

		name = create_waiver_request(
			sales_order=self.sales_order.name,
			apply_discount_on="Single Item",
			discount_criteria="Waiver Based on Actual Amount",
			waiver_reason="Customer requested a waiver on one item",
			discount_amount=20,
			items=[
				{
					"item_code": target["item_code"],
					"item_name": target["item_name"],
					"actual_price": target["actual_price"],
					"discount_amount": 20,
					"amount_after_discount": target["actual_price"] - 20,
					"so_detail": target["so_detail"],
				}
			],
		)
		waiver_request = frappe.get_doc("Waiver Request", name)
		self.assertEqual(waiver_request.total_actual_amount, target["actual_price"])
		self.assertEqual(waiver_request.total_discounted_amount, 20)

		waiver_request.decision = "Approved"
		waiver_request.submit()

		self.sales_order.reload()
		item_row = next(row for row in self.sales_order.items if row.name == target["so_detail"])
		self.assertEqual(item_row.rate, target["actual_price"] - 20)
		self.assertEqual(item_row.discount_amount, 20)
		self.assertEqual(self.sales_order.waiver_status, "Approved")


def create_and_get_waiver_request(sales_order, discount_amount=0):
	return create_waiver_request(
		sales_order=sales_order,
		apply_discount_on="Grand Total",
		discount_criteria="Waiver Based on Actual Amount",
		waiver_reason="Customer requested a waiver",
		discount_amount=discount_amount,
	)


def make_test_sales_order():
	customer = (
		frappe.db.get_value("Customer", {}, "name")
		or frappe.get_doc({"doctype": "Customer", "customer_name": "_Test Waiver Customer"})
		.insert(ignore_permissions=True)
		.name
	)
	item = frappe.db.get_value("Item", {"is_sales_item": 1, "disabled": 0}, "name") or frappe.db.get_value(
		"Item", {"disabled": 0}, "name"
	)

	sales_order = frappe.get_doc(
		{
			"doctype": "Sales Order",
			"customer": customer,
			"delivery_date": frappe.utils.add_days(frappe.utils.nowdate(), 7),
			"items": [{"item_code": item, "qty": 1, "rate": 100}],
		}
	)
	sales_order.insert(ignore_permissions=True)
	return sales_order
