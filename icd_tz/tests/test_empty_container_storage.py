# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from icd_tz.icd_tz.api.contract import get_settings_storage_keys, get_storage_day_counts
from icd_tz.icd_tz.api.sales_order import get_empty_container_services
from icd_tz.icd_tz.doctype.container.container import get_cargo_category
from icd_tz.patches import set_container_cargo_category
from icd_tz.tests.test_container_income_refs import get_container, make_reception_containers, with_settings
from icd_tz.tests.test_icd_services import services_settings
from icd_tz.tests.test_service_criteria import criteria
from icd_tz.tests.utils import get_test_company

test_ignore = ["Company", "Cost Center"]

EMPTY_STORAGE_ITEM = "_T Empty Storage 20ft"
STORAGE_DAYS = [
	{"cargo_category": "Normal", "charge": "Free", "from": 1, "to": 7},
	{"cargo_category": "Normal", "charge": "Single", "from": 8, "to": 14},
	{"cargo_category": "Normal", "charge": "Double", "from": 15, "to": 9999999},
	{"cargo_category": "Empty", "charge": "Free", "from": 1, "to": 2},
	{"cargo_category": "Empty", "charge": "Single", "from": 3, "to": 9999999},
]


def empty_settings():
	settings_doc = services_settings(
		criteria("Storage-Single", EMPTY_STORAGE_ITEM, cargo_category="Empty", size="20ft")
	)
	settings_doc.storage_days = [frappe._dict(destination="Local", **row) for row in STORAGE_DAYS]
	return settings_doc


class TestEmptyContainerCategory(FrappeTestCase):
	def test_an_empty_box_is_empty_whatever_its_bill_of_lading_carried(self):
		container = frappe._dict(is_empty_container=1, imdg_code="C8", plug_type_of_reefer="Y")

		self.assertEqual(get_cargo_category(container), "Empty")

	def test_the_patch_marks_empty_boxes_not_delivered(self):
		mbl, hbl = make_reception_containers(cargo_type="Local")
		frappe.db.set_value("Container", mbl, {"is_empty_container": 1, "status": "At Gate Confirmation"})
		frappe.db.set_value("Container", hbl, {"is_empty_container": 1, "status": "Delivered"})

		set_container_cargo_category.execute()

		self.assertEqual(get_container(mbl).cargo_category, "Empty")
		self.assertNotEqual(get_container(hbl).cargo_category, "Empty")
		frappe.db.rollback()


class TestEmptyContainerStorageDays(FrappeTestCase):
	"""An empty box is free for 2 days after unpacking, then charged one daily rate"""

	def tearDown(self):
		frappe.db.rollback()

	def test_an_empty_box_ignores_the_contract_of_its_c_and_f_company(self):
		container = frappe._dict(
			company=get_test_company(),
			place_of_destination="Local",
			cargo_category="Empty",
			is_empty_container=1,
			c_and_f_company="_Test C and F",
		)

		with (
			with_settings(empty_settings()),
			patch("icd_tz.icd_tz.api.contract.get_active_contract") as get_active_contract,
		):
			counts = get_storage_day_counts(container)

		get_active_contract.assert_not_called()
		self.assertEqual(counts, {"Free": 2, "Single": 9999997, "Double": 0})

	def test_every_chargeable_day_of_an_empty_box_is_single(self):
		container = frappe.new_doc("Container")
		container.update(
			{"company": get_test_company(), "place_of_destination": "Local", "cargo_category": "Empty"}
		)
		container.is_empty_container = 1
		for _ in range(30):
			container.append("container_dates", {"is_billable": 1, "is_free": 0})

		with with_settings(empty_settings()):
			container.update_billed_days()

		self.assertEqual(sum(row.is_free for row in container.container_dates), 2)
		self.assertEqual((container.has_single_charge, container.has_double_charge), (1, 0))

	def test_the_empty_box_is_billed_on_its_own_storage_item(self):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value(
			"Container", mbl, {"m_bl_no": "_T-MBL-EMPTY", "size": "22G1", "place_of_destination": "Local"}
		)
		container = frappe.get_doc("Container", mbl)
		container.update({"is_empty_container": 1, "unpack_date": add_days(nowdate(), -9)})
		container.reset_container_dates()

		with with_settings(empty_settings()):
			container.update_container_stay()
			services = get_empty_container_services("_T-MBL-EMPTY")

		self.assertEqual(get_container(mbl).cargo_category, "Empty")
		self.assertEqual([(row["item_code"], row["qty"]) for row in services], [(EMPTY_STORAGE_ITEM, 8)])


class TestEmptyStorageSettings(FrappeTestCase):
	def test_empty_storage_has_no_double_row(self):
		setting = frappe.new_doc("ICD Setting")
		setting.append(
			"storage_days", {"destination": "Local", "cargo_category": "Empty", "charge": "Double"}
		)

		self.assertRaises(frappe.ValidationError, setting.validate_storage_days)

	def test_a_contract_is_not_asked_for_empty_storage_rows(self):
		with with_settings(empty_settings()):
			keys = get_settings_storage_keys(get_test_company())

		self.assertEqual(keys, {("Local", "Normal")})
