# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.utils import get_icd_setting
from icd_tz.icd_tz.doctype.container_reception.container_reception import get_received_date
from icd_tz.patches import (
	create_icd_setting_company_record,
	rename_icd_tz_settings_to_icd_setting,
	set_contract_company,
	set_edi_partner_company,
)
from icd_tz.patches.flag_draft_container_expenses import flag_drafts
from icd_tz.tests.utils import (
	get_company_without_setting,
	get_test_company,
	get_test_icd_setting,
	insert_purchase_order,
	insert_row,
	set_test_icd_setting,
)

test_ignore = ["Company", "Cost Center"]


def keep_only_the_test_setting():
	"""The company patches need one ICD Setting, the rollback brings the others back"""

	test_setting = get_test_icd_setting().name
	frappe.db.delete("ICD Setting", {"name": ("!=", test_setting)})


class TestRenamePatch(FrappeTestCase):
	def test_a_second_run_does_nothing(self):
		self.assertFalse(frappe.db.exists("DocType", "ICD TZ Settings"))

		rename_icd_tz_settings_to_icd_setting.execute()

		self.assertTrue(frappe.db.exists("DocType", "ICD Setting"))


class TestCompanyRecordPatch(FrappeTestCase):
	def setUp(self):
		self.company = get_company_without_setting()
		if not self.company:
			self.skipTest("this test needs a company without an ICD Setting")

		self.wip = frappe.db.get_value(
			"Account", {"company": self.company, "is_group": 0, "root_type": "Asset"}, "name"
		)

	def tearDown(self):
		frappe.db.rollback()

	def add_single_values(self, values: dict):
		for field, value in values.items():
			insert_row("Singles", {"doctype": "ICD Setting", "field": field, "value": value})

	def add_old_child_row(self, name: str, idx: int):
		insert_row(
			"ICD TZ Settings Detail",
			{
				"name": name,
				"parent": "ICD TZ Settings",
				"parenttype": "ICD Setting",
				"parentfield": "storage_days",
				"idx": idx,
				"destination": "Local",
				"charge": "Free",
			},
		)

	def test_the_single_values_move_to_the_record_of_the_wip_account_company(self):
		self.add_single_values(
			{"icd_code": "_TMOVE", "gate_pass_expiry_hours": "36", "wip_account": self.wip}
		)
		self.add_old_child_row("_T-MOVE-ROW-1", 1)
		self.add_old_child_row("_T-MOVE-ROW-2", 2)

		create_icd_setting_company_record.execute()

		record = frappe.get_doc("ICD Setting", {"company": self.company})
		self.assertEqual(record.icd_code, "_TMOVE")
		self.assertEqual(record.gate_pass_expiry_hours, 36)
		self.assertEqual([row.name for row in record.storage_days], ["_T-MOVE-ROW-1", "_T-MOVE-ROW-2"])
		self.assertFalse(frappe.db.get_singles_dict("ICD Setting"))

	def test_nothing_changes_when_the_company_has_a_record(self):
		get_test_icd_setting()
		self.add_single_values({"icd_code": "_TKEEP"})

		with patch(
			"icd_tz.patches.create_icd_setting_company_record.get_company", return_value=get_test_company()
		):
			create_icd_setting_company_record.execute()

		self.assertEqual(frappe.db.get_singles_dict("ICD Setting").get("icd_code"), "_TKEEP")

	def test_a_second_run_does_nothing(self):
		self.add_single_values({"icd_code": "_TMOVE", "wip_account": self.wip})
		create_icd_setting_company_record.execute()

		create_icd_setting_company_record.execute()

		self.assertEqual(frappe.db.count("ICD Setting", {"company": self.company}), 1)


class TestContractCompanyPatch(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def add_contract(self, name: str):
		insert_row("Contract", {"name": name, "party_type": "Customer", "party_name": "x", "docstatus": 0})

	def run_patch(self):
		# the field already exists, and creating it again would commit the test transaction
		with patch("icd_tz.patches.set_contract_company.create_custom_fields"):
			set_contract_company.execute()

	def test_existing_contracts_take_the_company_of_the_icd_setting(self):
		keep_only_the_test_setting()
		self.add_contract("_T-CONTRACT-1")

		self.run_patch()

		self.assertEqual(frappe.db.get_value("Contract", "_T-CONTRACT-1", "company"), get_test_company())

	def test_the_company_is_not_guessed_from_several_icd_settings(self):
		get_test_icd_setting()
		other_company = get_company_without_setting()
		if not other_company:
			self.skipTest("this test needs a second company")

		get_test_icd_setting(other_company)
		self.add_contract("_T-CONTRACT-1")

		self.assertRaises(frappe.ValidationError, self.run_patch)


class TestDraftFlagPatch(FrappeTestCase):
	def setUp(self):
		self.company = get_test_company()
		self.container = frappe.db.get_value("ICD Container", {}, "name") or "_T-BOX"

	def tearDown(self):
		frappe.db.rollback()

	def add_order(self, name: str, docstatus: int, lines: list):
		insert_purchase_order(name, docstatus, company=self.company)
		for idx, (item_code, container) in enumerate(lines, 1):
			insert_row(
				"Purchase Order Item",
				{
					"name": f"{name}-{idx}",
					"parent": name,
					"parenttype": "Purchase Order",
					"parentfield": "items",
					"idx": idx,
					"item_code": item_code,
					"icd_container": container,
					"docstatus": docstatus,
				},
			)

	def test_drafts_of_container_expenses_only_are_flagged_and_mixed_drafts_listed(self):
		expense = "_T-PORT-EXPENSE"
		self.add_order("_T-PO-EXPENSES", 0, [(expense, self.container), (expense, self.container)])
		self.add_order("_T-PO-MIXED", 0, [(expense, self.container), ("_T-STATIONERY", None)])
		self.add_order("_T-PO-OFFICE", 0, [("_T-STATIONERY", None)])
		self.add_order("_T-PO-SUBMITTED", 1, [(expense, self.container)])

		mixed = flag_drafts("Purchase Order", self.company, {expense})

		flags = {
			name: frappe.db.get_value("Purchase Order", name, "is_icd_container_expense")
			for name in ("_T-PO-EXPENSES", "_T-PO-MIXED", "_T-PO-OFFICE", "_T-PO-SUBMITTED")
		}
		self.assertEqual(
			flags, {"_T-PO-EXPENSES": 1, "_T-PO-MIXED": 0, "_T-PO-OFFICE": 0, "_T-PO-SUBMITTED": 0}
		)
		self.assertEqual(len(mixed), 1)
		self.assertIn("_T-PO-MIXED", mixed[0])


class TestEDIPartnerPatch(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_each_partner_gets_the_company_and_is_renamed_by_code_and_abbreviation(self):
		keep_only_the_test_setting()
		insert_row(
			"EDI Partner",
			{
				"name": "_TPRT",
				"shipping_line_code": "_TPRT",
				"sender_id": "OWNID",
				"enable_edi": 1,
				"docstatus": 0,
			},
		)

		set_edi_partner_company.execute()

		abbr = frappe.get_cached_value("Company", get_test_company(), "abbr")
		partner = frappe.db.get_value(
			"EDI Partner", f"_TPRT-{abbr}", ["company", "abbr", "sender_id", "enable_edi"], as_dict=True
		)
		self.assertEqual(partner.company, get_test_company())
		self.assertEqual(partner.abbr, abbr)
		self.assertEqual((partner.sender_id, partner.enable_edi), ("OWNID", 1))
		self.assertFalse(frappe.db.exists("EDI Partner", "_TPRT"))


class TestTwoCompanies(FrappeTestCase):
	"""Each company reads its own ICD Setting"""

	def tearDown(self):
		frappe.db.rollback()

	def test_two_companies_keep_different_settings(self):
		other_company = get_company_without_setting()
		if not other_company:
			self.skipTest("this test needs a second company")

		set_test_icd_setting({"received_date_threshold_hours": 24})
		set_test_icd_setting({"received_date_threshold_hours": 72}, other_company)
		posting, ship_dc = "2026-10-05 12:00:00", "2026-10-03 12:00:00"

		self.assertEqual(get_icd_setting(get_test_company()).received_date_threshold_hours, 24)
		self.assertEqual(get_icd_setting(other_company).received_date_threshold_hours, 72)
		self.assertEqual(str(get_received_date(posting, ship_dc, get_test_company())), "2026-10-05")
		self.assertEqual(str(get_received_date(posting, ship_dc, other_company)), "2026-10-03")

	def test_a_company_without_an_icd_setting_is_told_to_create_one(self):
		other_company = get_company_without_setting()
		if not other_company:
			self.skipTest("this test needs a company without an ICD Setting")

		self.assertRaises(frappe.ValidationError, get_icd_setting, other_company)
		self.assertRaises(frappe.ValidationError, get_icd_setting, None)
