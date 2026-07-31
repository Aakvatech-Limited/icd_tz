# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.doctype.waiver_request.waiver_request import create_waiver_request


class TestWaiverRequest(FrappeTestCase):
    def setUp(self):
        self.sales_order = make_test_sales_order()

    def tearDown(self):
        frappe.db.rollback()

    def test_creating_waiver_request_marks_sales_order_pending(self):
        waiver_request = frappe.get_doc(
            create_and_get_waiver_request(self.sales_order.name)
        )

        self.sales_order.reload()
        self.assertEqual(self.sales_order.waiver_status, "Pending")
        self.assertRaises(frappe.ValidationError, self.sales_order.submit)
        self.assertEqual(waiver_request.docstatus, 0)

    def test_approving_waiver_request_applies_discount_on_sales_order(self):
        waiver_request = frappe.get_doc(
            create_and_get_waiver_request(self.sales_order.name, discount_amount=50)
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
            create_and_get_waiver_request(self.sales_order.name, discount_amount=50)
        )
        waiver_request.decision = "Rejected"
        waiver_request.submit()

        self.sales_order.reload()
        self.assertEqual(self.sales_order.waiver_status, "Rejected")
        self.assertEqual(self.sales_order.discount_amount, 0)
        self.sales_order.submit()
        self.assertEqual(self.sales_order.docstatus, 1)


def create_and_get_waiver_request(sales_order, discount_amount=0):
    name = create_waiver_request(
        sales_order=sales_order,
        apply_discount_on="Grand Total",
        waiver_reason="Customer requested a waiver",
        discount_amount=discount_amount,
    )
    return "Waiver Request", name


def make_test_sales_order():
    customer = frappe.db.get_value("Customer", {}, "name") or frappe.get_doc(
        {"doctype": "Customer", "customer_name": "_Test Waiver Customer"}
    ).insert(ignore_permissions=True).name
    item = frappe.db.get_value("Item", {"is_sales_item": 1}, "name") or frappe.db.get_value(
        "Item", {}, "name"
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
