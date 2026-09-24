# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.expense_release import (
	get_invoice_dimensions,
	get_release_accounts,
	get_wip_balance,
	mark_released,
	release_expenses,
	reverse_release,
	unmark_released,
)
from icd_tz.tests.test_edi_movement import make_manifest, make_reception

test_ignore = ["Company", "Cost Center"]


class TestExpenseRelease(FrappeTestCase):
	"""Moving a container's port expenses from WIP to COGS once it is billed"""

	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		accounts = frappe.get_all(
			"Account",
			{"company": self.company, "is_group": 0, "root_type": "Expense"},
			pluck="name",
			limit=2,
		)
		if len(accounts) < 2:
			self.skipTest(f"{self.company} has fewer than two postable expense accounts")

		self.wip, self.cogs = accounts
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		self.manifest = make_manifest()
		self.reception = make_reception()
		self.container = self.make_icd_container()

	def tearDown(self):
		frappe.clear_document_cache("ICD TZ Settings", "ICD TZ Settings")

	def make_icd_container(self):
		container = frappe.new_doc("ICD Container")
		container.update({"container_no": "RELU1234567", "manifest": self.manifest.name})
		container.flags.ignore_mandatory = True
		container.insert(ignore_permissions=True)

		return container.name

	def enable_wip(self):
		frappe.db.set_single_value(
			"ICD TZ Settings",
			{"enable_wip_for_expenses": 1, "wip_account": self.wip, "cogs_account": self.cogs},
		)

	# --- when the move applies at all ------------------------------------

	def test_nothing_moves_while_the_setting_is_off(self):
		frappe.db.set_single_value("ICD TZ Settings", "enable_wip_for_expenses", 0)

		self.assertEqual(get_release_accounts(self.company), {})

	def test_the_two_accounts_are_read_from_the_settings(self):
		self.enable_wip()

		self.assertEqual(
			get_release_accounts(self.company), {"wip_account": self.wip, "cogs_account": self.cogs}
		)

	def test_another_company_is_left_alone(self):
		other = frappe.db.get_value("Company", {"name": ("!=", self.company)}, "name")
		if not other:
			self.skipTest("this test needs a second company")

		self.enable_wip()

		self.assertEqual(get_release_accounts(other), {})

	def test_nothing_moves_while_an_account_is_missing(self):
		frappe.db.set_single_value(
			"ICD TZ Settings", {"enable_wip_for_expenses": 1, "wip_account": self.wip, "cogs_account": None}
		)

		self.assertEqual(get_release_accounts(self.company), {})

	# --- what an invoice covers ------------------------------------------

	def test_an_invoice_with_no_container_lines_releases_nothing(self):
		self.assertEqual(get_invoice_dimensions("SINV-NONE"), [])

	# --- the balance the ledger reports ----------------------------------

	def test_a_container_that_never_held_an_expense_has_no_balance(self):
		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 0.0)

	# --- recording the release -------------------------------------------

	def test_releasing_records_the_entry_and_the_date(self):
		mark_released(self.container, "ACC-JV-TEST-1")
		row = frappe.db.get_value(
			"ICD Container",
			self.container,
			["expenses_released", "expense_release_entry", "expenses_released_on"],
			as_dict=True,
		)

		self.assertEqual(row.expenses_released, 1)
		self.assertEqual(row.expense_release_entry, "ACC-JV-TEST-1")
		self.assertTrue(row.expenses_released_on)

	def test_reversing_clears_the_record(self):
		mark_released(self.container, "ACC-JV-TEST-1")

		unmark_released(self.container, "ACC-JV-TEST-1")
		row = frappe.db.get_value(
			"ICD Container",
			self.container,
			["expenses_released", "expense_release_entry", "expenses_released_on"],
			as_dict=True,
		)

		self.assertEqual(row.expenses_released, 0)
		self.assertFalse(row.expense_release_entry)
		self.assertIsNone(row.expenses_released_on)

	def test_the_entries_of_a_container_accumulate(self):
		mark_released(self.container, "ACC-JV-TEST-1")
		mark_released(self.container, "ACC-JV-TEST-2")

		self.assertEqual(
			frappe.db.get_value("ICD Container", self.container, "expense_release_entry"),
			"ACC-JV-TEST-1,ACC-JV-TEST-2",
		)

	def test_taking_one_release_back_leaves_the_other(self):
		mark_released(self.container, "ACC-JV-TEST-1")
		mark_released(self.container, "ACC-JV-TEST-2")

		unmark_released(self.container, "ACC-JV-TEST-1")
		row = frappe.db.get_value(
			"ICD Container", self.container, ["expenses_released", "expense_release_entry"], as_dict=True
		)

		self.assertEqual(row.expense_release_entry, "ACC-JV-TEST-2")
		self.assertEqual(row.expenses_released, 1)

	def test_taking_the_last_release_back_clears_the_flag(self):
		mark_released(self.container, "ACC-JV-TEST-1")

		unmark_released(self.container, "ACC-JV-TEST-1")
		row = frappe.db.get_value(
			"ICD Container", self.container, ["expenses_released", "expense_release_entry"], as_dict=True
		)

		self.assertEqual(row.expenses_released, 0)
		self.assertFalse(row.expense_release_entry)


class TestReleasePosts(FrappeTestCase):
	"""What the release actually posts to the ledger"""

	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		accounts = frappe.get_all(
			"Account",
			{"company": self.company, "is_group": 0, "root_type": "Expense"},
			pluck="name",
			limit=2,
		)
		if len(accounts) < 2:
			self.skipTest(f"{self.company} has fewer than two postable expense accounts")

		self.cogs, self.wip = accounts
		self.cost_center = frappe.db.get_value(
			"Cost Center", {"company": self.company, "is_group": 0}, "name"
		)
		self.item = frappe.get_single("ICD TZ Settings").expense_types[0].expense_item
		frappe.db.set_single_value(
			"ICD TZ Settings",
			{"enable_wip_for_expenses": 1, "wip_account": self.wip, "cogs_account": self.cogs},
		)
		self.manifest = make_manifest()
		self.container = self.make_icd_container()

	def tearDown(self):
		frappe.clear_document_cache("ICD TZ Settings", "ICD TZ Settings")

	def make_icd_container(self):
		container = frappe.new_doc("ICD Container")
		container.update(
			{"container_no": "POST1234567", "manifest": self.manifest.name, "company": self.company}
		)
		container.flags.ignore_mandatory = True
		container.insert(ignore_permissions=True)

		return container.name

	def hold_in_wip(self, amount):
		invoice = frappe.new_doc("Purchase Invoice")
		invoice.update(
			{
				"supplier": frappe.db.get_value("Supplier", {}, "name"),
				"company": self.company,
				"posting_date": frappe.utils.nowdate(),
				"due_date": frappe.utils.nowdate(),
			}
		)
		invoice.append(
			"items",
			{
				"item_code": self.item,
				"qty": 1,
				"rate": amount,
				"icd_container": self.container,
				"expense_account": self.wip,
				"cost_center": self.cost_center,
			},
		)
		invoice.flags.ignore_permissions = True
		invoice.flags.ignore_mandatory = True
		invoice.insert()
		invoice.submit()

	def bill_the_container(self):
		invoice = frappe.new_doc("Sales Invoice")
		invoice.update(
			{
				"customer": frappe.db.get_value("Customer", {}, "name"),
				"company": self.company,
				"posting_date": frappe.utils.nowdate(),
			}
		)
		invoice.append(
			"items",
			{
				"item_code": self.item,
				"qty": 1,
				"rate": 400000,
				"icd_container": self.container,
				"cost_center": self.cost_center,
			},
		)
		invoice.flags.ignore_permissions = True
		invoice.flags.ignore_mandatory = True
		invoice.insert()
		invoice.submit()

		return invoice

	def test_the_balance_moves_from_wip_to_cogs(self):
		self.hold_in_wip(250000)
		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 250000)
		invoice = self.bill_the_container()

		release_expenses(invoice.name)

		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 0)
		entry = frappe.db.get_value("ICD Container", self.container, "expense_release_entry")
		accounts = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": entry},
			fields=["account", "debit", "credit", "icd_container"],
		)
		self.assertEqual(
			sorted((row.account, row.debit, row.credit) for row in accounts),
			sorted([(self.cogs, 250000, 0), (self.wip, 0, 250000)]),
		)
		self.assertEqual({row.icd_container for row in accounts}, {self.container})

	def test_running_it_again_posts_nothing(self):
		self.hold_in_wip(250000)
		invoice = self.bill_the_container()
		release_expenses(invoice.name)

		release_expenses(invoice.name)

		self.assertEqual(
			frappe.db.count("Journal Entry", {"user_remark": ("like", f"%{invoice.name}%"), "docstatus": 1}),
			1,
		)

	def test_an_expense_booked_after_a_release_is_still_moved(self):
		# the ledger is what says how much is left, not the released flag
		self.hold_in_wip(250000)
		first = self.bill_the_container()
		release_expenses(first.name)

		self.hold_in_wip(90000)
		second = self.bill_the_container()
		release_expenses(second.name)

		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 0)

	def test_cancelling_the_invoice_puts_the_expense_back(self):
		self.hold_in_wip(250000)
		invoice = self.bill_the_container()
		release_expenses(invoice.name)

		invoice.reload()
		invoice.cancel()
		reverse_release(invoice.name)

		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 250000)
		self.assertEqual(frappe.db.get_value("ICD Container", self.container, "expenses_released"), 0)

	def test_cancelling_one_invoice_leaves_another_release_alone(self):
		self.hold_in_wip(250000)
		first = self.bill_the_container()
		release_expenses(first.name)
		entry = frappe.db.get_value("ICD Container", self.container, "expense_release_entry")

		second = self.bill_the_container()
		reverse_release(second.name)

		self.assertEqual(frappe.db.get_value("Journal Entry", entry, "docstatus"), 1)
		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 0)

	def test_a_cancelled_invoice_is_released_again_by_the_next_one(self):
		# the services stay unpaid, so another invoice is raised for them, and the
		# expenses move again. This is the LCL case, where one box is billed to
		# several consignees and any of their invoices can be cancelled and reissued
		self.hold_in_wip(250000)
		first = self.bill_the_container()
		release_expenses(first.name)
		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 0)

		# the reversal is queued by the invoice being cancelled, so it runs after it
		first.reload()
		first.cancel()
		reverse_release(first.name)
		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 250000)

		second = self.bill_the_container()
		release_expenses(second.name)

		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 0)
		entries = frappe.db.get_value("ICD Container", self.container, "expense_release_entry").split(",")
		self.assertEqual(len(entries), 1, "the cancelled entry is not left on the container")
		self.assertEqual(frappe.db.get_value("Journal Entry", entries[0], "icd_sales_invoice"), second.name)

	def test_the_entry_names_the_invoice_it_released(self):
		self.hold_in_wip(250000)
		invoice = self.bill_the_container()

		release_expenses(invoice.name)

		entry = frappe.db.get_value("ICD Container", self.container, "expense_release_entry")
		self.assertEqual(frappe.db.get_value("Journal Entry", entry, "icd_sales_invoice"), invoice.name)

	def test_the_invoice_can_still_be_cancelled_after_a_release(self):
		# the entry records the invoice it released, and a Link there would hold the
		# invoice open for ever, so this walks the real cancel rather than the job
		self.hold_in_wip(250000)
		invoice = self.bill_the_container()
		release_expenses(invoice.name)

		invoice.reload()
		invoice.cancel()

		self.assertEqual(invoice.docstatus, 2)

	def test_the_release_cannot_be_cancelled_while_its_invoice_stands(self):
		# the invoice recognised the revenue, so taking only the cost back would leave
		# that revenue with no cost against it
		self.hold_in_wip(250000)
		invoice = self.bill_the_container()
		release_expenses(invoice.name)
		entry = frappe.db.get_value("ICD Container", self.container, "expense_release_entry")

		journal_entry = frappe.get_doc("Journal Entry", entry)

		self.assertRaises(frappe.ValidationError, journal_entry.cancel)
		self.assertEqual(frappe.db.get_value("ICD Container", self.container, "expenses_released"), 1)
		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 0)

	def test_the_release_can_be_cancelled_once_its_invoice_has_gone(self):
		self.hold_in_wip(250000)
		invoice = self.bill_the_container()
		release_expenses(invoice.name)
		entry = frappe.db.get_value("ICD Container", self.container, "expense_release_entry")

		invoice.reload()
		invoice.cancel()
		journal_entry = frappe.get_doc("Journal Entry", entry)
		journal_entry.cancel()

		self.assertEqual(frappe.db.get_value("ICD Container", self.container, "expenses_released"), 0)
		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 250000)

	def test_a_credit_note_releases_nothing(self):
		self.hold_in_wip(250000)
		invoice = self.bill_the_container()
		frappe.db.set_value("Sales Invoice", invoice.name, "is_return", 1)

		release_expenses(invoice.name)

		self.assertEqual(get_wip_balance({"icd_container": self.container}, self.wip), 250000)
