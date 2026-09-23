# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.purchase_invoice import set_wip_account
from icd_tz.icd_tz.api.purchase_order import (
	add_container_line,
	get_required_wip_account,
	get_wip_account,
)

test_ignore = ["Company", "Cost Center"]

EXPENSE_ITEM = "_Test WIP Expense Item"


def get_accounts(company):
	return frappe.get_all(
		"Account", {"company": company, "is_group": 0, "root_type": "Expense"}, pluck="name", limit=2
	)


def make_expense_item():
	if not frappe.db.exists("Item", EXPENSE_ITEM):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": EXPENSE_ITEM,
				"item_name": EXPENSE_ITEM,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)

	return EXPENSE_ITEM


class WipTestCase(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		accounts = get_accounts(self.company)
		if len(accounts) < 2:
			self.skipTest(f"{self.company} has fewer than two postable expense accounts")

		self.wip, self.cogs = accounts
		self.other_company = frappe.db.get_value("Company", {"name": ("!=", self.company)}, "name")
		settings_doc = frappe.get_single("ICD TZ Settings")
		if settings_doc.expense_types:
			self.item = settings_doc.expense_types[0].expense_item
		else:
			self.item = make_expense_item()
			settings_doc.append("expense_types", {"expense_type": "Shore", "expense_item": self.item})
			settings_doc.flags.ignore_mandatory = True
			settings_doc.save(ignore_permissions=True)

	def tearDown(self):
		frappe.clear_document_cache("ICD TZ Settings", "ICD TZ Settings")

	def enable_wip(self, wip_account=None):
		frappe.db.set_single_value(
			"ICD TZ Settings",
			{
				"enable_wip_for_expenses": 1,
				"wip_account": wip_account or self.wip,
				"cogs_account": self.cogs,
			},
		)

	def disable_wip(self):
		frappe.db.set_single_value("ICD TZ Settings", "enable_wip_for_expenses", 0)


class TestWipAccountSetting(WipTestCase):
	"""Which account port expenses are booked to"""

	def test_no_account_is_chosen_while_the_setting_is_off(self):
		# ERPNext keeps choosing the expense account from the item and company defaults
		self.disable_wip()

		self.assertIsNone(get_wip_account(self.company))
		get_required_wip_account(self.company)

	def test_the_wip_account_is_used_while_the_setting_is_on(self):
		self.enable_wip()

		self.assertEqual(get_wip_account(self.company), self.wip)

	def test_another_company_is_left_alone_rather_than_blocked(self):
		# one settings record holds one account, and an account belongs to one company
		if not self.other_company:
			self.skipTest("this test needs a second company")

		self.enable_wip()

		self.assertIsNone(get_wip_account(self.other_company))

	def test_an_order_for_a_company_the_account_cannot_serve_is_refused(self):
		if not self.other_company:
			self.skipTest("this test needs a second company")

		self.enable_wip()

		self.assertRaises(frappe.ValidationError, get_required_wip_account, self.other_company)

	def test_an_order_is_refused_while_the_account_is_missing(self):
		frappe.db.set_single_value("ICD TZ Settings", {"enable_wip_for_expenses": 1, "wip_account": None})

		self.assertRaises(frappe.ValidationError, get_required_wip_account, self.company)

	def test_turning_it_on_without_the_accounts_is_refused(self):
		settings_doc = frappe.get_single("ICD TZ Settings")
		settings_doc.update({"enable_wip_for_expenses": 1, "wip_account": None, "cogs_account": None})

		self.assertRaises(frappe.ValidationError, settings_doc.validate_wip_accounts)

	def test_the_two_accounts_must_differ(self):
		settings_doc = frappe.get_single("ICD TZ Settings")
		settings_doc.update({"enable_wip_for_expenses": 1, "wip_account": self.wip, "cogs_account": self.wip})

		self.assertRaises(frappe.ValidationError, settings_doc.validate_wip_accounts)

	def test_two_accounts_of_different_companies_are_refused(self):
		if not self.other_company:
			self.skipTest("this test needs a second company")

		other_accounts = get_accounts(self.other_company)
		if not other_accounts:
			self.skipTest(f"{self.other_company} has no postable expense account")

		settings_doc = frappe.get_single("ICD TZ Settings")
		settings_doc.update(
			{
				"enable_wip_for_expenses": 1,
				"wip_account": self.wip,
				"cogs_account": other_accounts[0],
			}
		)

		self.assertRaises(frappe.ValidationError, settings_doc.validate_wip_accounts)

	def test_a_group_account_is_refused(self):
		group = frappe.db.get_value("Account", {"company": self.company, "is_group": 1}, "name")
		settings_doc = frappe.get_single("ICD TZ Settings")
		settings_doc.update({"enable_wip_for_expenses": 1, "wip_account": group, "cogs_account": self.cogs})

		self.assertRaises(frappe.ValidationError, settings_doc.validate_wip_accounts)


class TestOrderAndInvoiceLines(WipTestCase):
	"""Holding the expense on WIP from the order through to the invoice"""

	def make_order_line(self, wip_account):
		purchase_order = frappe.new_doc("Purchase Order")
		purchase_order.schedule_date = frappe.utils.nowdate()
		row = {
			"item_code": self.item,
			"rate": 100,
			"expense_type": "Shore",
			"size": "20ft",
			"cargo_type": None,
			"destination": None,
			"port": None,
		}
		container = {
			"qty": 1,
			"container_no": "TEST1234567",
			"day_rows": [],
			"icd_master_bl": "MBL-1",
			"icd_container": "CNT-1",
		}
		add_container_line(purchase_order, "ICD-M-0001", row, container, wip_account)

		return purchase_order.items[0]

	def make_invoice(self, item_code, icd_container="CNT-1", expense_account="SOMETHING ELSE"):
		# frappe._dict cannot carry an "items" attribute, it shadows the dict method
		return SimpleNamespace(
			company=self.company,
			items=[
				frappe._dict(
					item_code=item_code, icd_container=icd_container, expense_account=expense_account
				)
			],
		)

	def test_an_order_line_carries_the_wip_account(self):
		self.assertEqual(self.make_order_line(self.wip).expense_account, self.wip)

	def test_an_order_line_carries_no_account_while_the_setting_is_off(self):
		self.assertIsNone(self.make_order_line(None).expense_account)

	def test_an_invoice_line_for_a_port_expense_is_held_on_wip(self):
		self.enable_wip()
		doc = self.make_invoice(self.item)

		set_wip_account(doc)

		self.assertEqual(doc.items[0].expense_account, self.wip)

	def test_a_line_that_is_not_a_configured_expense_is_left_alone(self):
		# a container can be tagged on any purchase, and the rest of that invoice is
		# ERPNext's to account for, stock items above all
		self.enable_wip()
		doc = self.make_invoice("_Test Item")

		set_wip_account(doc)

		self.assertEqual(doc.items[0].expense_account, "SOMETHING ELSE")

	def test_a_line_with_no_container_is_left_alone(self):
		self.enable_wip()
		doc = self.make_invoice(self.item, icd_container=None)

		set_wip_account(doc)

		self.assertEqual(doc.items[0].expense_account, "SOMETHING ELSE")

	def test_an_invoice_is_left_alone_while_the_setting_is_off(self):
		self.disable_wip()
		doc = self.make_invoice(self.item)

		set_wip_account(doc)

		self.assertEqual(doc.items[0].expense_account, "SOMETHING ELSE")
