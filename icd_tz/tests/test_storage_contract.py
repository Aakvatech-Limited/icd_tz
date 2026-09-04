# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from icd_tz.icd_tz.api.contract import (
	STORAGE_CHARGES,
	get_active_contract,
	get_selling_price_list,
	get_storage_day_counts,
)
from icd_tz.icd_tz.api.sales_order import get_container_days_to_be_billed
from icd_tz.icd_tz.api.utils import set_container_cf_company
from icd_tz.patches.tick_rate_based_on_priced_contracts import execute as tick_rate_based

DESTINATIONS = ["DRC", "Local", "Other"]
SETTINGS_DAYS = {"Free": (1, 7), "Single": (8, 14), "Double": (15, 999999)}
SETTINGS_COUNTS = {"Free": 7, "Single": 7, "Double": 999985}
CONTRACT_DAYS = {"Free": (1, 12), "Single": (13, 14), "Double": (15, 16)}
DEFAULT_PRICE_LIST = "_Test ICD Default Price List"


class TestStorageContract(FrappeTestCase):
	def setUp(self):
		set_settings_storage_days()
		self.company = create_cf_company()

	def tearDown(self):
		frappe.db.rollback()

	def test_submit_needs_a_billing_basis(self):
		contract = make_contract(self.company)
		contract.insert()

		self.assertRaises(frappe.ValidationError, contract.submit)

	def test_rate_based_contract_needs_a_price_list(self):
		contract = make_contract(self.company, is_rate_based=1)

		self.assertRaises(frappe.ValidationError, contract.insert)

	def test_storage_days_based_contract_needs_every_destination_and_charge(self):
		contract = make_contract(self.company, is_storage_days_based=1)
		contract.append("storage_days", {"destination": "Local", "charge": "Free", "from": 1, "to": 5})

		self.assertRaises(frappe.ValidationError, contract.insert)

	def test_storage_days_row_rejects_an_unknown_destination(self):
		contract = make_contract(self.company, is_storage_days_based=1)
		add_storage_days(contract, destinations=[*DESTINATIONS, "Mars"])

		self.assertRaises(frappe.ValidationError, contract.insert)

	def test_storage_days_row_rejects_an_inverted_day_range(self):
		contract = make_contract(self.company, is_storage_days_based=1)
		add_storage_days(contract)
		contract.storage_days[0].update({"from": 8, "to": 3})

		self.assertRaises(frappe.ValidationError, contract.insert)

	def test_storage_days_rejects_an_incomplete_row(self):
		contract = make_contract(self.company, is_storage_days_based=1)
		add_storage_days(contract)
		contract.storage_days[0].destination = None

		self.assertRaises(frappe.ValidationError, contract.insert)

	def test_storage_days_rejects_a_duplicate_destination_and_charge(self):
		contract = make_contract(self.company, is_storage_days_based=1)
		add_storage_days(contract)
		contract.append("storage_days", {"destination": "Local", "charge": "Free", "from": 1, "to": 5})

		self.assertRaises(frappe.ValidationError, contract.insert)

	def test_unticked_billing_basis_inputs_are_cleared(self):
		contract = make_contract(self.company, is_storage_days_based=1)
		add_storage_days(contract)
		contract.price_list = create_price_list("_Test ICD Contract Price List")
		contract.insert()

		self.assertIsNone(contract.price_list)
		self.assertEqual(len(contract.storage_days), 3 * len(DESTINATIONS))

		contract.is_storage_days_based = 0
		contract.is_rate_based = 1
		contract.price_list = create_price_list("_Test ICD Contract Price List")
		contract.save()

		self.assertEqual(len(contract.storage_days), 0)
		self.assertEqual(contract.price_list, "_Test ICD Contract Price List")

	def test_switching_party_type_away_from_cf_clears_the_billing_basis(self):
		contract = make_contract(self.company, is_storage_days_based=1, is_rate_based=1)
		add_storage_days(contract)
		contract.price_list = create_price_list("_Test ICD Contract Price List")
		contract.insert()

		contract.party_type = "Customer"
		contract.party_name = create_customer()
		contract.save()

		self.assertEqual(contract.is_rate_based, 0)
		self.assertEqual(contract.is_storage_days_based, 0)
		self.assertIsNone(contract.price_list)
		self.assertEqual(len(contract.storage_days), 0)

	def test_active_contract_carries_the_rate_based_price_list(self):
		price_list = create_price_list("_Test ICD Contract Price List")
		contract = make_contract(self.company, is_rate_based=1)
		contract.price_list = price_list
		contract.insert()
		contract.submit()

		active_contract = get_active_contract(self.company)
		self.assertEqual(active_contract["name"], contract.name)
		self.assertEqual(active_contract["is_rate_based"], 1)
		self.assertEqual(active_contract["price_list"], price_list)

	def test_expired_contract_is_not_active(self):
		contract = make_contract(self.company, is_rate_based=1)
		contract.price_list = create_price_list("_Test ICD Contract Price List")
		contract.start_date = add_days(nowdate(), -30)
		contract.end_date = add_days(nowdate(), -1)
		contract.insert()
		contract.submit()

		self.assertEqual(get_active_contract(self.company), {})

	def test_storage_day_counts_fall_back_to_settings(self):
		container = frappe._dict({"place_of_destination": "Local", "c_and_f_company": self.company})

		self.assertEqual(get_storage_day_counts(container), SETTINGS_COUNTS)

	def test_storage_day_counts_come_from_an_active_storage_days_contract(self):
		submit_storage_days_contract(self.company)
		container = frappe._dict({"place_of_destination": "Local", "c_and_f_company": self.company})

		self.assertEqual(get_storage_day_counts(container), {"Free": 12, "Single": 2, "Double": 2})

	def test_storage_day_counts_ignore_a_contract_of_another_company(self):
		submit_storage_days_contract(self.company)
		container = frappe._dict({"place_of_destination": "Local", "c_and_f_company": None})

		self.assertEqual(get_storage_day_counts(container), SETTINGS_COUNTS)

	def test_selling_price_list_comes_from_a_rate_based_contract(self):
		price_list = create_price_list("_Test ICD Contract Price List")
		contract = make_contract(self.company, is_rate_based=1)
		contract.price_list = price_list
		contract.insert()
		contract.submit()

		self.assertEqual(get_selling_price_list(self.company), price_list)

	def test_selling_price_list_ignores_a_storage_days_only_contract(self):
		submit_storage_days_contract(self.company)

		self.assertEqual(get_selling_price_list(self.company), DEFAULT_PRICE_LIST)

	def test_selling_price_list_falls_back_without_a_contract(self):
		self.assertEqual(get_selling_price_list(self.company), DEFAULT_PRICE_LIST)

	def test_free_window_marks_exactly_the_free_days(self):
		container = container_with_dates(14)

		container.update_billed_days()

		self.assertEqual(sum(1 for row in container.container_dates if row.is_free), 7)
		self.assertEqual(sum(1 for row in container.container_dates if row.is_billable), 7)

	def test_shrinking_free_window_reclaims_the_extra_days(self):
		container = container_with_dates(14)
		for row in container.container_dates[:12]:
			row.is_free = 1
			row.is_billable = 0

		container.update_billed_days()

		self.assertEqual(sum(1 for row in container.container_dates if row.is_free), 7)
		self.assertEqual(sum(1 for row in container.container_dates if row.is_billable), 7)
		self.assertEqual(container.has_single_charge, 1)
		self.assertEqual(container.has_double_charge, 0)

	def test_shrinking_free_window_keeps_write_offs_and_invoiced_days(self):
		container = container_with_dates(14)
		for row in container.container_dates[:12]:
			row.is_free = 1
			row.is_billable = 0

		written_off = container.container_dates[9]
		written_off.is_free = 0
		written_off.is_billable = 0

		invoiced = container.container_dates[10]
		invoiced.sales_invoice = "_TEST-SINV-0001"

		container.update_billed_days()

		self.assertEqual(written_off.is_free, 0)
		self.assertEqual(written_off.is_billable, 0)
		self.assertEqual(invoiced.is_free, 1)
		self.assertEqual(invoiced.is_billable, 0)

	def test_no_chargeable_day_clears_both_charge_flags(self):
		container = container_with_dates(7)

		container.update_billed_days()

		self.assertEqual(container.has_single_charge, 0)
		self.assertEqual(container.has_double_charge, 0)

	def test_chargeable_days_equal_to_the_single_window_stay_single_only(self):
		container = container_with_dates(14)

		container.update_billed_days()

		self.assertEqual(container.has_single_charge, 1)
		self.assertEqual(container.has_double_charge, 0)

	def test_one_chargeable_day_past_the_single_window_adds_double(self):
		container = container_with_dates(15)

		container.update_billed_days()

		self.assertEqual(container.has_single_charge, 1)
		self.assertEqual(container.has_double_charge, 1)

	def test_contract_windows_move_the_charge_flag_boundary(self):
		submit_storage_days_contract(self.company)

		single_only = container_with_dates(14, c_and_f_company=self.company)
		single_only.update_billed_days()
		self.assertEqual(sum(1 for row in single_only.container_dates if row.is_free), 12)
		self.assertEqual(single_only.has_single_charge, 1)
		self.assertEqual(single_only.has_double_charge, 0)

		with_double = container_with_dates(15, c_and_f_company=self.company)
		with_double.update_billed_days()
		self.assertEqual(with_double.has_single_charge, 1)
		self.assertEqual(with_double.has_double_charge, 1)

	def test_settings_windows_count_seven_free_and_seven_single_days(self):
		container = frappe._dict({"place_of_destination": "Local", "c_and_f_company": self.company})

		counts = get_storage_day_counts(container)

		self.assertEqual(counts["Free"], 7)
		self.assertEqual(counts["Single"], 7)

	def test_billable_days_stop_at_the_settings_single_window(self):
		container = billable_container(self.company, days=20)

		single_days, double_days = get_container_days_to_be_billed(container)

		self.assertEqual(len(single_days), 7)
		self.assertEqual(len(double_days), 13)

	def test_billable_days_stop_at_the_contract_single_and_double_windows(self):
		submit_storage_days_contract(self.company, days={"Free": (1, 2), "Single": (3, 4), "Double": (5, 6)})
		container = billable_container(self.company, days=10)

		single_days, double_days = get_container_days_to_be_billed(container)

		self.assertEqual(len(single_days), 2)
		self.assertEqual(len(double_days), 2)

	def test_patch_ticks_rate_based_on_a_contract_that_already_has_a_price_list(self):
		price_list = create_price_list("_Test ICD Contract Price List")
		contract = make_contract(self.company, is_rate_based=1)
		contract.price_list = price_list
		contract.insert()
		contract.submit()

		frappe.db.set_value("Contract", contract.name, "is_rate_based", 0, update_modified=False)
		frappe.clear_document_cache("Contract", contract.name)

		tick_rate_based()

		self.assertEqual(frappe.db.get_value("Contract", contract.name, "is_rate_based"), 1)
		self.assertEqual(get_selling_price_list(self.company), price_list)

	def test_container_takes_the_cf_company_of_the_first_document_that_carries_it(self):
		container = create_container()

		set_container_cf_company(frappe._dict({"container_id": container, "c_and_f_company": self.company}))
		self.assertEqual(frappe.db.get_value("Container", container, "c_and_f_company"), self.company)

		other_company = create_cf_company("_Test ICD C and F Company Two")
		set_container_cf_company(frappe._dict({"container_id": container, "c_and_f_company": other_company}))
		self.assertEqual(frappe.db.get_value("Container", container, "c_and_f_company"), self.company)

	def test_rate_based_contract_does_not_change_storage_days(self):
		contract = make_contract(self.company, is_rate_based=1)
		contract.price_list = create_price_list("_Test ICD Contract Price List")
		contract.insert()
		contract.submit()

		container = frappe._dict({"place_of_destination": "Local", "c_and_f_company": self.company})
		self.assertEqual(get_storage_day_counts(container), SETTINGS_COUNTS)


def set_settings_storage_days():
	settings_doc = frappe.get_doc("ICD TZ Settings")
	settings_doc.icd_code = settings_doc.icd_code or "_TEST"
	settings_doc.default_price_list = create_price_list(DEFAULT_PRICE_LIST)
	settings_doc.storage_days = []
	for destination in DESTINATIONS:
		for charge, (day_from, day_to) in SETTINGS_DAYS.items():
			settings_doc.append(
				"storage_days",
				{"destination": destination, "charge": charge, "from": day_from, "to": day_to},
			)

	settings_doc.save(ignore_permissions=True)
	frappe.clear_document_cache("ICD TZ Settings", "ICD TZ Settings")


def create_cf_company(company_name="_Test ICD C and F Company"):
	if frappe.db.exists("Clearing and Forwarding Company", company_name):
		return company_name

	return (
		frappe.get_doc(
			{
				"doctype": "Clearing and Forwarding Company",
				"company_name": company_name,
				"phone": "0700000000",
				"email": "cf@example.com",
				"physical_address": "Dar es Salaam",
				"person_name": "Test Person",
				"license_no": "LIC-0001",
			}
		)
		.insert()
		.name
	)


def container_with_dates(days, c_and_f_company=None, place_of_destination="Local"):
	"""Unsaved Container carrying `days` billable date rows, for update_billed_days()"""

	container = frappe.new_doc("Container")
	container.place_of_destination = place_of_destination
	container.c_and_f_company = c_and_f_company
	for _ in range(days):
		container.append("container_dates", {"is_billable": 1, "is_free": 0})

	return container


def billable_container(c_and_f_company, days):
	"""Container stub with `days` billable dates, enough for the day split helpers"""

	return frappe._dict(
		{
			"place_of_destination": "Local",
			"c_and_f_company": c_and_f_company,
			"has_single_charge": 1,
			"has_double_charge": 1,
			"container_dates": [
				frappe._dict({"name": f"row-{index}", "is_billable": 1, "sales_invoice": None})
				for index in range(days)
			],
		}
	)


def create_customer(customer_name="_Test ICD Contract Customer"):
	if frappe.db.exists("Customer", customer_name):
		return customer_name

	return (
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": customer_name,
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			}
		)
		.insert()
		.name
	)


def create_container(place_of_destination="Local"):
	"""A bare Container row, a full one needs a Container Reception and a Manifest"""

	container = frappe.get_doc(
		{
			"doctype": "Container",
			"container_no": "_TESTCONT0001",
			"place_of_destination": place_of_destination,
		}
	)
	container.name = "_TESTCONT0001"
	container.db_insert()

	return container.name


def create_price_list(price_list_name):
	if frappe.db.exists("Price List", price_list_name):
		return price_list_name

	return (
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": price_list_name,
				"selling": 1,
				"currency": "TZS",
			}
		)
		.insert()
		.name
	)


def make_contract(c_and_f_company, **kwargs):
	contract = frappe.get_doc(
		{
			"doctype": "Contract",
			"party_type": "Clearing and Forwarding Company",
			"party_name": c_and_f_company,
			"start_date": nowdate(),
			"end_date": add_days(nowdate(), 365),
			"contract_terms": "Storage and rates",
		}
	)
	contract.update(kwargs)

	return contract


def add_storage_days(contract, destinations=None, days=None):
	for destination in destinations or DESTINATIONS:
		for charge in STORAGE_CHARGES:
			day_from, day_to = (days or CONTRACT_DAYS)[charge]
			contract.append(
				"storage_days",
				{"destination": destination, "charge": charge, "from": day_from, "to": day_to},
			)


def submit_storage_days_contract(c_and_f_company, days=None):
	contract = make_contract(c_and_f_company, is_storage_days_based=1)
	add_storage_days(contract, days=days)
	contract.insert()
	contract.submit()
	frappe.clear_document_cache("Contract", contract.name)

	return contract
