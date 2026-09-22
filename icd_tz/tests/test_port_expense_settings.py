# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.port_expenses import EXPENSE_TYPES, FREE_CHARGE, STORAGE_EXPENSE_TYPES

ITEM = "_Test ICD Settings Expense Item"


class TestPortExpenseSettings(FrappeTestCase):
	def setUp(self):
		make_item(ITEM)
		self.settings_doc = frappe.get_doc("ICD TZ Settings")
		self.settings_doc.expense_types = []
		self.settings_doc.port_storage_days = []
		self.settings_doc.flags.ignore_mandatory = True

	def tearDown(self):
		frappe.db.rollback()

	def test_two_criteria_rows_with_the_same_key_are_rejected(self):
		for _ in range(2):
			self.settings_doc.append(
				"expense_types",
				{"expense_type": "Shore", "expense_item": ITEM, "size": "20ft", "cargo_type": "Local"},
			)

		self.assertRaises(frappe.ValidationError, self.settings_doc.save)

	def test_criteria_rows_differing_by_one_field_are_allowed(self):
		for size in ("20ft", "40ft"):
			self.settings_doc.append(
				"expense_types", {"expense_type": "Shore", "expense_item": ITEM, "size": size}
			)

		self.settings_doc.save()

		self.assertEqual(len(self.settings_doc.expense_types), 2)

	def test_an_inverted_storage_band_is_rejected(self):
		add_bands(self.settings_doc)
		self.settings_doc.port_storage_days[0].update({"from": 8, "to": 3})

		self.assertRaises(frappe.ValidationError, self.settings_doc.save)

	def test_a_storage_band_starting_below_day_one_is_rejected(self):
		add_bands(self.settings_doc)
		self.settings_doc.port_storage_days[0].update({"from": 0})

		self.assertRaises(frappe.ValidationError, self.settings_doc.save)

	def test_a_duplicate_charge_is_rejected(self):
		add_bands(self.settings_doc)
		self.settings_doc.append("port_storage_days", {"charge": "Single", "from": 20, "to": 30})

		self.assertRaises(frappe.ValidationError, self.settings_doc.save)

	def test_a_half_defined_band_set_is_rejected(self):
		"""Only one band would silently price the other charge at zero days"""

		self.settings_doc.append("port_storage_days", {"charge": "Single", "from": 1, "to": 7})

		self.assertRaises(frappe.ValidationError, self.settings_doc.save)

	def test_the_expense_type_options_match_the_booked_flag_mapping(self):
		options = frappe.get_meta("ICD TZ Expense Detail").get_field("expense_type").options
		declared = {option for option in options.split("\n") if option}

		self.assertEqual(declared, set(EXPENSE_TYPES))

	def test_the_storage_bands_match_the_storage_expense_types(self):
		charges = frappe.get_meta("ICD TZ Port Storage Detail").get_field("charge").options
		declared = {option for option in charges.split("\n") if option}

		# Free is a band the container records but no expense type bills
		expected = {FREE_CHARGE} | set(STORAGE_EXPENSE_TYPES.values())
		self.assertEqual(declared, expected)

		# the ledger offers the same charges, or a band could not be stamped on a day
		ledger = frappe.get_meta("ICD Container Storage Date").get_field("charge").options
		self.assertEqual({option for option in ledger.split("\n") if option}, expected)

	def test_a_gap_between_bands_is_rejected(self):
		"""A day no band covers is never recorded, so the stay would lose it"""

		self.settings_doc.port_storage_days = []
		for charge, from_day, to_day in (("Free", 1, 5), ("Single", 8, 12), ("Double", 13, 999999)):
			self.settings_doc.append("port_storage_days", {"charge": charge, "from": from_day, "to": to_day})

		self.assertRaises(frappe.ValidationError, self.settings_doc.save)

	def test_bands_that_do_not_start_at_day_one_are_rejected(self):
		self.settings_doc.port_storage_days = []
		for charge, from_day, to_day in (("Free", 2, 5), ("Single", 6, 12), ("Double", 13, 999999)):
			self.settings_doc.append("port_storage_days", {"charge": charge, "from": from_day, "to": to_day})

		self.assertRaises(frappe.ValidationError, self.settings_doc.save)

	def test_a_seeded_row_does_not_block_saving_other_settings(self):
		"""The rows say which charges are expected; the days are confirmed later"""

		self.settings_doc.port_storage_days = []
		for charge in ("Free", "Single", "Double"):
			self.settings_doc.append("port_storage_days", {"charge": charge})

		self.settings_doc.save()

		self.assertEqual(len(self.settings_doc.port_storage_days), 3)


def add_bands(settings_doc):
	for charge, from_day, to_day in (("Free", 1, 5), ("Single", 6, 12), ("Double", 13, 999999)):
		settings_doc.append("port_storage_days", {"charge": charge, "from": from_day, "to": to_day})


def make_item(item_code):
	if frappe.db.exists("Item", item_code):
		return

	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
			"stock_uom": "Nos",
			"is_stock_item": 0,
		}
	).insert()
