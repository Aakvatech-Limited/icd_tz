# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.item_accounts import get_expense_accounts, get_wip_cogs_map
from icd_tz.tests.utils import get_foreign_expense_account, get_test_company, make_test_account

test_ignore = ["Company", "Cost Center"]

ITEM_GROUP = "_Test ICD Expense Group"


class ItemAccountsTestCase(FrappeTestCase):
	def setUp(self):
		self.company = get_test_company()
		self.wip = make_test_account("_Test ICD WIP", "Asset")
		self.other_wip = make_test_account("_Test ICD WIP Two", "Asset")
		self.cogs = make_test_account("_Test ICD COGS", "Expense")
		self.other_cogs = make_test_account("_Test ICD COGS Two", "Expense")
		self.warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		if not frappe.db.exists("Item Group", ITEM_GROUP):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": ITEM_GROUP,
					"parent_item_group": "All Item Groups",
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def make_item(self, item_code: str, wip_account=None, cogs_account=None, item_group=ITEM_GROUP):
		return frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_group": item_group,
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"item_defaults": [self.get_row(wip_account, cogs_account)],
			}
		).insert(ignore_permissions=True)

	def set_group_accounts(self, wip_account, cogs_account):
		group = frappe.get_doc("Item Group", ITEM_GROUP)
		group.item_group_defaults = []
		group.append("item_group_defaults", self.get_row(wip_account, cogs_account))
		group.save(ignore_permissions=True)

	def get_row(self, wip_account, cogs_account) -> dict:
		return {
			"company": self.company,
			"default_warehouse": self.warehouse,
			"wip_account": wip_account,
			"cogs_account": cogs_account,
		}

	def add_wip_balance(self, wip_account: str, amount: float = 100):
		frappe.db.sql(
			"""insert into `tabGL Entry` (name, account, debit, credit, is_cancelled, icd_container, company)
			values (%s, %s, %s, 0, 0, '_T-ACCOUNTS-BOX', %s)""",
			(frappe.generate_hash(length=10), wip_account, amount, self.company),
		)


class TestItemAccountChecks(ItemAccountsTestCase):
	def test_both_accounts_are_set_or_neither(self):
		self.assertRaises(frappe.ValidationError, self.make_item, "_T-ACC-1", self.wip)
		self.assertRaises(frappe.ValidationError, self.make_item, "_T-ACC-2", None, self.cogs)
		self.make_item("_T-ACC-3")

	def test_the_two_accounts_differ(self):
		self.assertRaises(frappe.ValidationError, self.make_item, "_T-ACC-1", self.cogs, self.cogs)

	def test_the_wip_account_is_an_asset_and_the_cogs_account_an_expense(self):
		self.assertRaises(frappe.ValidationError, self.make_item, "_T-ACC-1", self.cogs, self.other_cogs)
		self.assertRaises(frappe.ValidationError, self.make_item, "_T-ACC-2", self.wip, self.other_wip)

	def test_an_account_of_another_company_is_refused(self):
		foreign_cogs = get_foreign_expense_account(self.company)
		if not foreign_cogs:
			self.skipTest("this test needs an expense account of a second company")

		self.assertRaises(frappe.ValidationError, self.make_item, "_T-ACC-1", self.wip, foreign_cogs)

	def test_a_group_account_is_refused(self):
		group = frappe.db.get_value(
			"Account", {"company": self.company, "is_group": 1, "root_type": "Expense"}, "name"
		)

		self.assertRaises(frappe.ValidationError, self.make_item, "_T-ACC-1", self.wip, group)


class TestWipPairing(ItemAccountsTestCase):
	def test_items_can_share_one_pair(self):
		self.make_item("_T-ACC-1", self.wip, self.cogs)
		self.make_item("_T-ACC-2", self.wip, self.cogs)

	def test_a_wip_account_pairs_with_only_one_cogs_account(self):
		self.make_item("_T-ACC-1", self.wip, self.cogs)

		self.assertRaises(frappe.ValidationError, self.make_item, "_T-ACC-2", self.wip, self.other_cogs)

	def test_two_wip_accounts_can_pair_with_one_cogs_account(self):
		self.make_item("_T-ACC-1", self.wip, self.cogs)
		self.make_item("_T-ACC-2", self.other_wip, self.cogs)

	def test_the_pairing_rule_covers_item_groups(self):
		self.make_item("_T-ACC-1", self.wip, self.cogs)

		self.assertRaises(frappe.ValidationError, self.set_group_accounts, self.wip, self.other_cogs)


class TestBlockedChange(ItemAccountsTestCase):
	def test_a_pair_changes_while_its_wip_account_holds_nothing(self):
		item = self.make_item("_T-ACC-1", self.wip, self.cogs)
		item.item_defaults[0].cogs_account = self.other_cogs
		item.save(ignore_permissions=True)

	def test_a_pair_cannot_change_while_its_wip_account_holds_a_container_balance(self):
		item = self.make_item("_T-ACC-1", self.wip, self.cogs)
		self.add_wip_balance(self.wip)
		item.reload()
		item.item_defaults[0].cogs_account = self.other_cogs

		self.assertRaises(frappe.ValidationError, item.save, ignore_permissions=True)

	def test_a_released_balance_no_longer_blocks_the_change(self):
		item = self.make_item("_T-ACC-1", self.wip, self.cogs)
		self.add_wip_balance(self.wip, 100)
		self.add_wip_balance(self.wip, -100)
		item.reload()
		item.item_defaults[0].cogs_account = self.other_cogs
		item.save(ignore_permissions=True)

	def test_an_unrelated_save_is_not_blocked(self):
		item = self.make_item("_T-ACC-1", self.wip, self.cogs)
		self.add_wip_balance(self.wip)
		item.reload()
		item.description = "changed"
		item.save(ignore_permissions=True)


class TestFindingTheAccounts(ItemAccountsTestCase):
	def test_the_item_row_comes_first(self):
		self.set_group_accounts(self.other_wip, self.other_cogs)
		self.make_item("_T-ACC-1", self.wip, self.cogs)

		self.assertEqual(
			get_expense_accounts("_T-ACC-1", self.company),
			{"wip_account": self.wip, "cogs_account": self.cogs},
		)

	def test_the_item_group_row_is_the_fallback(self):
		self.set_group_accounts(self.other_wip, self.other_cogs)
		self.make_item("_T-ACC-1")

		self.assertEqual(
			get_expense_accounts("_T-ACC-1", self.company),
			{"wip_account": self.other_wip, "cogs_account": self.other_cogs},
		)

	def test_an_item_without_accounts_has_none(self):
		self.make_item("_T-ACC-1")

		self.assertEqual(get_expense_accounts("_T-ACC-1", self.company), {})

	def test_the_map_covers_items_and_item_groups(self):
		self.make_item("_T-ACC-1", self.wip, self.cogs)
		self.set_group_accounts(self.other_wip, self.other_cogs)

		wip_cogs_map = get_wip_cogs_map(self.company)

		self.assertEqual(wip_cogs_map[self.wip], self.cogs)
		self.assertEqual(wip_cogs_map[self.other_wip], self.other_cogs)
