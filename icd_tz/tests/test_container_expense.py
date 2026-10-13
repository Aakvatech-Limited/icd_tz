# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.model.mapper import get_mapped_doc
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.container_expense import before_validate
from icd_tz.tests.utils import (
	get_company_without_setting,
	get_test_company,
	get_test_icd_setting,
	insert_purchase_order,
	make_test_account,
	make_test_item,
	set_item_accounts,
	set_test_icd_setting,
)

test_ignore = ["Company", "Cost Center"]

EXPENSE_ITEM = "_Test ICD Container Expense"
OFFICE_ITEM = "_Test ICD Office Expense"
DIMENSIONS = {"icd_container": "_T-BOX-1", "icd_master_bl": "_T-MBL-1", "manifest": "_T-MANIFEST-1"}


class ContainerExpenseTestCase(FrappeTestCase):
	def setUp(self):
		self.company = get_test_company()
		self.wip = make_test_account("_Test ICD WIP", "Asset")
		self.cogs = make_test_account("_Test ICD COGS", "Expense")
		self.office_account = make_test_account("_Test ICD Office Expenses", "Expense")
		self.item = make_test_item(EXPENSE_ITEM)
		self.office_item = make_test_item(OFFICE_ITEM)
		set_item_accounts(self.item, self.wip, self.cogs)

		settings_doc = get_test_icd_setting()
		settings_doc.expense_types = []
		settings_doc.append("expense_types", {"expense_type": "Shore", "expense_item": self.item})
		settings_doc.flags.ignore_mandatory = True
		settings_doc.save(ignore_permissions=True)
		set_test_icd_setting({"enable_wip_and_cogs_for_expenses": 1})

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_document_cache("ICD Setting", get_test_icd_setting().name)

	def make_doc(self, doctype: str, flagged: int, *lines: dict, company: str | None = None):
		doc = frappe.new_doc(doctype)
		doc.update({"company": company or self.company, "is_icd_container_expense": flagged})
		for line in lines:
			doc.append("items", line)

		return doc

	def container_line(self, item_code=None, expense_account=None, **values) -> dict:
		return {
			"item_code": item_code or self.item,
			"expense_account": expense_account or self.office_account,
			**DIMENSIONS,
			**values,
		}


class TestContainerExpenseDocument(ContainerExpenseTestCase):
	def test_a_line_without_a_container_is_refused(self):
		for field in DIMENSIONS:
			doc = self.make_doc("Purchase Invoice", 1, self.container_line(**{field: None}))

			self.assertRaises(frappe.ValidationError, before_validate, doc)

	def test_a_line_of_another_expense_is_refused(self):
		doc = self.make_doc("Purchase Invoice", 1, self.container_line(self.office_item))

		self.assertRaises(frappe.ValidationError, before_validate, doc)

	def test_a_changed_account_is_set_back_to_the_wip_account_of_the_item(self):
		for doctype in ("Purchase Order", "Purchase Invoice"):
			doc = self.make_doc(doctype, 1, self.container_line(expense_account=self.office_account))
			before_validate(doc)

			self.assertEqual(doc.items[0].expense_account, self.wip)

	def test_an_item_without_accounts_stops_the_save(self):
		set_item_accounts(self.item, None, None)
		doc = self.make_doc("Purchase Invoice", 1, self.container_line())

		self.assertRaises(frappe.ValidationError, before_validate, doc)

	def test_the_account_rules_are_skipped_while_wip_is_disabled(self):
		set_test_icd_setting({"enable_wip_and_cogs_for_expenses": 0})
		doc = self.make_doc("Purchase Invoice", 1, self.container_line())
		before_validate(doc)

		self.assertEqual(doc.items[0].expense_account, self.office_account)

	def test_the_line_rules_apply_while_wip_is_disabled(self):
		set_test_icd_setting({"enable_wip_and_cogs_for_expenses": 0})
		doc = self.make_doc("Purchase Invoice", 1, self.container_line(manifest=None))

		self.assertRaises(frappe.ValidationError, before_validate, doc)


class TestInvoiceFromOrders(ContainerExpenseTestCase):
	def test_an_invoice_of_flagged_orders_is_flagged(self):
		insert_purchase_order("_T-PO-FLAGGED-1", flagged=1)
		insert_purchase_order("_T-PO-FLAGGED-2", flagged=1)
		doc = self.make_doc(
			"Purchase Invoice",
			0,
			self.container_line(purchase_order="_T-PO-FLAGGED-1"),
			self.container_line(purchase_order="_T-PO-FLAGGED-2"),
		)
		before_validate(doc)

		self.assertEqual(doc.is_icd_container_expense, 1)
		self.assertEqual({row.expense_account for row in doc.items}, {self.wip})

	def test_an_invoice_that_mixes_flagged_and_other_orders_is_refused(self):
		insert_purchase_order("_T-PO-FLAGGED-1", flagged=1)
		insert_purchase_order("_T-PO-OFFICE-1", flagged=0)
		doc = self.make_doc(
			"Purchase Invoice",
			0,
			self.container_line(purchase_order="_T-PO-FLAGGED-1"),
			self.container_line(purchase_order="_T-PO-OFFICE-1"),
		)

		self.assertRaises(frappe.ValidationError, before_validate, doc)

	def test_the_flag_is_copied_from_the_order_to_the_invoice(self):
		insert_purchase_order("_T-PO-FLAGGED-1", flagged=1)
		invoice = get_mapped_doc(
			"Purchase Order", "_T-PO-FLAGGED-1", {"Purchase Order": {"doctype": "Purchase Invoice"}}
		)

		self.assertEqual(invoice.is_icd_container_expense, 1)


class TestOfficeExpense(ContainerExpenseTestCase):
	def test_the_selected_account_stays(self):
		doc = self.make_doc(
			"Purchase Invoice", 0, {"item_code": self.office_item, "expense_account": self.office_account}
		)
		before_validate(doc)

		self.assertEqual(doc.items[0].expense_account, self.office_account)

	def test_a_wip_account_without_the_dimensions_is_refused(self):
		doc = self.make_doc(
			"Purchase Invoice", 0, {"item_code": self.office_item, "expense_account": self.wip}
		)

		self.assertRaises(frappe.ValidationError, before_validate, doc)

	def test_a_wip_account_with_the_dimensions_is_allowed(self):
		doc = self.make_doc(
			"Purchase Invoice", 0, {"item_code": self.office_item, "expense_account": self.wip, **DIMENSIONS}
		)
		before_validate(doc)

		self.assertEqual(doc.items[0].expense_account, self.wip)

	def test_a_company_without_an_icd_setting_is_left_alone(self):
		other_company = get_company_without_setting()
		if not other_company:
			self.skipTest("this test needs a company without an ICD Setting")

		doc = self.make_doc(
			"Purchase Invoice",
			0,
			{"item_code": self.office_item, "expense_account": self.office_account},
			company=other_company,
		)
		before_validate(doc)

		self.assertEqual(doc.items[0].expense_account, self.office_account)
