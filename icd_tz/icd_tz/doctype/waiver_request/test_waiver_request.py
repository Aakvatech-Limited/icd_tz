# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.doctype.waiver_request.waiver_request import (
	apply_approved_waiver,
	create_waiver_request,
	get_item_key,
	get_items,
)

test_dependencies = ["Item", "Customer"]


class TestWaiverRequest(FrappeTestCase):
	def setUp(self):
		self.sales_order = make_test_sales_order()

	def tearDown(self):
		frappe.db.rollback()

	def get_item_row(self, target):
		return next(
			row
			for row in self.sales_order.items
			if get_item_key(row)
			== (target["item_code"], target["container_no"] or "", target["container_id"] or "")
		)

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
		target = get_items(self.sales_order.name)[0]
		name = make_single_item_waiver(self.sales_order.name, target, discount_amount=20)

		waiver_request = frappe.get_doc("Waiver Request", name)
		self.assertEqual(waiver_request.total_actual_amount, target["actual_price"])
		self.assertEqual(waiver_request.total_discounted_amount, 20)

		waiver_request.decision = "Approved"
		waiver_request.submit()

		self.sales_order.reload()
		item_row = self.get_item_row(target)
		self.assertEqual(item_row.rate, target["actual_price"] - 20)
		self.assertEqual(item_row.discount_amount, 20)
		self.assertEqual(self.sales_order.waiver_status, "Approved")

	def test_single_item_waiver_on_multi_qty_item_reduces_amount_by_discount(self):
		self.sales_order = make_test_sales_order(qty=5)
		target = get_items(self.sales_order.name)[0]
		self.assertEqual(target["actual_price"], 500)

		waiver_request = frappe.get_doc(
			"Waiver Request", make_single_item_waiver(self.sales_order.name, target, discount_amount=20)
		)
		waiver_request.decision = "Approved"
		waiver_request.submit()

		self.sales_order.reload()
		item_row = self.get_item_row(target)
		self.assertEqual(item_row.qty, 5)
		self.assertEqual(item_row.rate, 96)
		self.assertEqual(item_row.amount, 480)
		self.assertEqual(item_row.margin_rate_or_amount, 0)
		self.assertEqual(self.sales_order.grand_total, 480)

	def test_single_item_waiver_above_item_amount_is_clamped_to_zero(self):
		target = get_items(self.sales_order.name)[0]
		waiver_request = frappe.get_doc(
			"Waiver Request",
			make_single_item_waiver(
				self.sales_order.name, target, discount_amount=target["actual_price"] + 500
			),
		)
		self.assertEqual(waiver_request.items[0].amount_after_discount, 0)
		self.assertEqual(waiver_request.total_amount_after_discount, 0)

		waiver_request.decision = "Approved"
		waiver_request.submit()

		self.sales_order.reload()
		item_row = self.get_item_row(target)
		self.assertEqual(item_row.rate, 0)
		self.assertEqual(item_row.amount, 0)
		self.assertEqual(self.sales_order.grand_total, 0)

	def test_single_item_waiver_matches_real_world_storage_charge_line(self):
		self.sales_order = make_test_sales_order(qty=373, rate=80000)
		target = get_items(self.sales_order.name)[0]
		self.assertEqual(target["actual_price"], 29840000)

		waiver_request = frappe.get_doc(
			"Waiver Request",
			make_single_item_waiver(self.sales_order.name, target, discount_amount=300000),
		)
		waiver_request.decision = "Approved"
		waiver_request.submit()

		self.sales_order.reload()
		item_row = self.get_item_row(target)
		self.assertEqual(item_row.qty, 373)
		self.assertEqual(item_row.margin_rate_or_amount, 0)
		self.assertAlmostEqual(item_row.amount, 29540000, delta=1)
		self.assertAlmostEqual(self.sales_order.grand_total, 29540000, delta=1)

	def test_waiver_carries_sales_order_currency_onto_items(self):
		self.sales_order = make_test_sales_order(currency="USD")
		target = get_items(self.sales_order.name)[0]
		waiver_request = frappe.get_doc(
			"Waiver Request", make_single_item_waiver(self.sales_order.name, target, discount_amount=20)
		)

		self.assertEqual(waiver_request.currency, "USD")
		self.assertEqual(waiver_request.items[0].currency, "USD")

	def test_waiver_survives_update_items_rebuilding_sales_order_rows(self):
		self.sales_order = make_test_sales_order(qty=5, container_no="TLLU7988901", container_id="ICD-C-1")
		ensure_item_price(self.sales_order, rate=100)
		target = get_items(self.sales_order.name)[0]
		self.assertEqual(target["container_no"], "TLLU7988901")

		waiver_request = frappe.get_doc(
			"Waiver Request", make_single_item_waiver(self.sales_order.name, target, discount_amount=20)
		)
		waiver_request.decision = "Approved"
		waiver_request.submit()

		self.sales_order.reload()
		original_row_name = self.sales_order.items[0].name
		self.assertEqual(self.sales_order.items[0].amount, 480)

		versions_before = frappe.db.count(
			"Version", {"ref_doctype": "Sales Order", "docname": self.sales_order.name}
		)
		rebuild_sales_order_items(self.sales_order, qty=8)
		self.assertNotEqual(self.sales_order.items[0].name, original_row_name)

		self.assertEqual(self.sales_order.items[0].qty, 8)
		self.assertEqual(self.sales_order.items[0].amount, 780)
		self.assertEqual(self.sales_order.grand_total, 780)

		versions_after = frappe.db.count(
			"Version", {"ref_doctype": "Sales Order", "docname": self.sales_order.name}
		)
		self.assertEqual(versions_after - versions_before, 1)

	def test_reapplying_waiver_twice_does_not_stack_the_discount(self):
		self.sales_order = make_test_sales_order(qty=5, container_no="TLLU7988901", container_id="ICD-C-1")
		target = get_items(self.sales_order.name)[0]

		waiver_request = frappe.get_doc(
			"Waiver Request", make_single_item_waiver(self.sales_order.name, target, discount_amount=20)
		)
		waiver_request.decision = "Approved"
		waiver_request.submit()

		self.sales_order.reload()
		for _ in range(2):
			apply_approved_waiver(self.sales_order)
			self.sales_order.save()

		self.assertEqual(self.sales_order.items[0].amount, 480)

	def test_waiver_is_not_reapplied_when_it_was_rejected(self):
		self.sales_order = make_test_sales_order(qty=5, container_no="TLLU7988901", container_id="ICD-C-1")
		ensure_item_price(self.sales_order, rate=100)
		target = get_items(self.sales_order.name)[0]

		waiver_request = frappe.get_doc(
			"Waiver Request", make_single_item_waiver(self.sales_order.name, target, discount_amount=20)
		)
		waiver_request.decision = "Rejected"
		waiver_request.submit()

		self.sales_order.reload()
		rebuild_sales_order_items(self.sales_order, qty=8)
		self.assertEqual(self.sales_order.items[0].amount, 800)


def rebuild_sales_order_items(sales_order, qty):
	"""Mimic the Update Items button: drop every row and append fresh ones carrying no rate."""
	rows = [
		{
			"item_code": row.item_code,
			"warehouse": row.warehouse,
			"delivery_date": row.delivery_date,
			"qty": qty,
			"container_no": row.container_no,
			"container_id": row.container_id,
		}
		for row in sales_order.items
	]
	sales_order.items = []
	for row in rows:
		sales_order.append("items", row)

	sales_order.set_missing_values()
	apply_approved_waiver(sales_order)

	# ignore_version defaults to on inside tests, so ask for the version log production gets
	sales_order.save(ignore_version=False)
	sales_order.reload()


def ensure_item_price(sales_order, rate):
	"""Update Items appends rows with no rate, so ERPNext must find one in the price list."""
	for row in sales_order.items:
		if frappe.db.exists(
			"Item Price", {"item_code": row.item_code, "price_list": sales_order.selling_price_list}
		):
			continue

		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": row.item_code,
				"price_list": sales_order.selling_price_list,
				"price_list_rate": rate,
				"currency": sales_order.currency,
			}
		).insert(ignore_permissions=True)


def make_single_item_waiver(sales_order, target, discount_amount):
	return create_waiver_request(
		sales_order=sales_order,
		apply_discount_on="Single Item",
		discount_criteria="Waiver Based on Actual Amount",
		waiver_reason="Customer requested a waiver on one item",
		discount_amount=discount_amount,
		items=[
			{
				"item_code": target["item_code"],
				"item_name": target["item_name"],
				"actual_price": target["actual_price"],
				"discount_amount": discount_amount,
				"amount_after_discount": target["actual_price"] - discount_amount,
				"container_no": target["container_no"],
				"container_id": target["container_id"],
			}
		],
	)


def create_and_get_waiver_request(sales_order, discount_amount=0):
	return create_waiver_request(
		sales_order=sales_order,
		apply_discount_on="Grand Total",
		discount_criteria="Waiver Based on Actual Amount",
		waiver_reason="Customer requested a waiver",
		discount_amount=discount_amount,
	)


def make_test_sales_order(qty=1, rate=100, currency=None, container_no=None, container_id=None):
	sales_order = make_sales_order(
		qty=qty, rate=rate, price_list_rate=rate, currency=currency, do_not_save=True
	)
	for row in sales_order.items:
		row.container_no = container_no
		row.container_id = container_id

	sales_order.insert()
	return sales_order
