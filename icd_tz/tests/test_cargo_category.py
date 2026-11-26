# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.contract import get_storage_day_counts
from icd_tz.icd_tz.api.icd_services import ICD_HANDLING
from icd_tz.icd_tz.api.utils import get_service_key
from icd_tz.icd_tz.doctype.container.container import get_cargo_category
from icd_tz.patches import set_container_cargo_category, set_pricing_rows_cargo_category
from icd_tz.tests.test_container_income_refs import (
	get_container,
	insert,
	make_reception_containers,
	with_settings,
)
from icd_tz.tests.test_icd_services import services_settings
from icd_tz.tests.test_lcl_gross_volume import make_service_order
from icd_tz.tests.test_service_criteria import criteria, settings
from icd_tz.tests.utils import get_test_company

test_ignore = ["Company", "Cost Center"]

MANIFEST = "_T-MAN-CC"


def container(**values):
	return frappe._dict({"manifest": MANIFEST, "m_bl_no": "_T-MBL-CC", "h_bl_no": None, **values})


def bill(doctype, imdg_code, **values):
	insert(doctype, parent=MANIFEST, parenttype="Manifest", imdg_code=imdg_code, **values)


class TestCargoCategory(FrappeTestCase):
	"""Dangerous by its IMDG Code, Reefer by its plug, otherwise Normal"""

	def tearDown(self):
		frappe.db.rollback()

	def test_a_plain_container_is_normal(self):
		self.assertEqual(get_cargo_category(container(plug_type_of_reefer="N", imdg_code=" ")), "Normal")

	def test_an_imdg_code_is_dangerous(self):
		self.assertEqual(get_cargo_category(container(imdg_code="C8")), "Dangerous")

	def test_a_plugged_container_is_reefer(self):
		self.assertEqual(get_cargo_category(container(plug_type_of_reefer="Y")), "Reefer")

	def test_dangerous_wins_over_reefer(self):
		self.assertEqual(
			get_cargo_category(container(plug_type_of_reefer="Y", imdg_code="C2.2")), "Dangerous"
		)

	def manifest_container(self, **values):
		mbl, hbl = make_reception_containers(cargo_type="Local")
		insert("Manifest", name=MANIFEST)
		name = hbl if values.get("has_hbl") else mbl
		frappe.db.set_value("Container", name, {"manifest": MANIFEST, "m_bl_no": "_T-MBL-CC", **values})
		container_doc = frappe.get_doc("Container", name)
		container_doc.reset_container_dates()
		return container_doc

	def test_an_mbl_container_takes_its_imdg_code_plug_and_temperatures_from_the_manifest(self):
		container_doc = self.manifest_container()
		bill("Master BL", "C8", m_bl_no="_T-MBL-CC")
		insert(
			"Containers Detail",
			parent=MANIFEST,
			container_no=container_doc.container_no,
			plug_type_of_reefer="Y",
			minimum_temperature="-18",
			maximum_temperature="-16",
		)

		container_doc.update_m_bl_based_container_details()
		with with_settings(services_settings()):
			container_doc.save(ignore_permissions=True)

		saved = get_container(container_doc.name)
		self.assertEqual(
			(
				saved.imdg_code,
				saved.plug_type_of_reefer,
				saved.minimum_temperature,
				saved.maximum_temperature,
			),
			("C8", "Y", "-18", "-16"),
		)
		self.assertEqual(saved.cargo_category, "Dangerous")

	def test_an_hbl_container_takes_the_house_bl_code_else_the_master_bl_code(self):
		bill("Master BL", "C3", m_bl_no="_T-MBL-CC")
		for house_code, expected in (("", "C3"), ("C8", "C8")):
			container_doc = self.manifest_container(has_hbl=1, h_bl_no="_T-HBL-CC")
			frappe.db.delete("House BL", {"parent": MANIFEST})
			bill("House BL", house_code, h_bl_no="_T-HBL-CC", place_of_destination="TZDAR")

			container_doc.update_m_bl_based_container_details()
			container_doc.update_hbl_based_container_details()

			self.assertEqual(container_doc.imdg_code, expected, house_code)
			frappe.db.rollback()


class TestCargoCategoryPricing(FrappeTestCase):
	"""A cargo category is priced only on its own rows"""

	def tearDown(self):
		frappe.db.rollback()

	def find_item(self, cargo_category, *rows):
		key = get_service_key(size="22G1", cargo_category=cargo_category)
		return ICD_HANDLING.find_item(settings(rows), key, is_loose_cargo=False)

	def test_each_category_gets_its_own_item(self):
		rows = (
			criteria("ICD Handling", "Handling Normal", cargo_category="Normal"),
			criteria("ICD Handling", "Handling Reefer", cargo_category="Reefer"),
		)

		self.assertEqual(self.find_item("Normal", *rows), "Handling Normal")
		self.assertEqual(self.find_item("Reefer", *rows), "Handling Reefer")

	def test_a_category_without_rows_asks_for_them(self):
		with self.assertRaises(frappe.ValidationError) as error:
			self.find_item("Reefer", criteria("ICD Handling", "Handling Normal", cargo_category="Normal"))

		self.assertIn("Cargo Category: Reefer", str(error.exception))

	def test_a_service_order_uses_the_container_category(self):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value(
			"Container",
			mbl,
			{"cargo_type": "Local", "has_icd_handling_charge": 1, "cargo_category": "Reefer"},
		)
		settings_doc = services_settings(
			criteria("ICD Handling", "_T Reefer Handling", cargo_category="Reefer")
		)
		service_order = make_service_order(
			container_id=mbl, container_status="FCL", container_size="22G1", port="TEAGTL"
		)

		with with_settings(settings_doc):
			service_order.add_container_services(settings_doc)

		self.assertIn("_T Reefer Handling", [row.service for row in service_order.services])


class TestCargoCategoryStorageDays(FrappeTestCase):
	"""Storage days of a destination are read for the container cargo category"""

	def counts(self, cargo_category, rows):
		settings_doc = frappe._dict(storage_days=[frappe._dict(destination="Local", **row) for row in rows])
		container_doc = frappe._dict(
			company=get_test_company(), place_of_destination="Local", cargo_category=cargo_category
		)
		with with_settings(settings_doc):
			return get_storage_day_counts(container_doc)

	def test_the_rows_of_the_container_category_are_used(self):
		rows = [
			{"cargo_category": "Normal", "charge": "Free", "from": 1, "to": 7},
			{"cargo_category": "Dangerous", "charge": "Free", "from": 1, "to": 2},
			{"cargo_category": "Dangerous", "charge": "Single", "from": 3, "to": 10},
		]

		self.assertEqual(self.counts("Dangerous", rows), {"Free": 2, "Single": 8, "Double": 0})

	def test_a_destination_without_rows_for_the_category_is_refused(self):
		rows = [{"cargo_category": "Normal", "charge": "Free", "from": 1, "to": 7}]

		with self.assertRaises(frappe.ValidationError):
			self.counts("Reefer", rows)

	def test_the_same_charge_may_repeat_for_another_category(self):
		setting = frappe.new_doc("ICD Setting")
		for category in ("Normal", "Reefer"):
			setting.append(
				"storage_days", {"destination": "Local", "cargo_category": category, "charge": "Free"}
			)
		setting.validate_storage_days()

		setting.append("storage_days", {"destination": "Local", "cargo_category": "Reefer", "charge": "Free"})
		self.assertRaises(frappe.ValidationError, setting.validate_storage_days)


class TestCargoCategoryPatches(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_existing_setting_rows_become_normal(self):
		row = insert(
			"ICD TZ Service Detail",
			parenttype="ICD Setting",
			parent="_T-ICD-CC",
			parentfield="service_types",
			service_type="Levy",
			service_name="_T Levy",
		)

		set_pricing_rows_cargo_category.execute()

		self.assertEqual(frappe.db.get_value("ICD TZ Service Detail", row.name, "cargo_category"), "Normal")

	def test_existing_contract_storage_rows_become_normal(self):
		row = insert(
			"Storage Contract Detail",
			parenttype="Contract",
			parent="_T-CONTRACT-CC",
			parentfield="storage_days",
			destination="Local",
			charge="Free",
		)

		set_pricing_rows_cargo_category.execute()

		self.assertEqual(frappe.db.get_value("Storage Contract Detail", row.name, "cargo_category"), "Normal")

	def test_existing_containers_get_their_imdg_code_plug_and_category(self):
		mbl, hbl = make_reception_containers(cargo_type="Local")
		values = {"manifest": MANIFEST, "m_bl_no": "_T-MBL-CC", "plug_type_of_reefer": None}
		frappe.db.set_value("Container", mbl, {**values, "status": "At Gate Confirmation"})
		frappe.db.set_value("Container", hbl, {**values, "status": "Delivered"})
		container_no = frappe.db.get_value("Container", mbl, "container_no")
		insert("Containers Detail", parent=MANIFEST, container_no=container_no, plug_type_of_reefer="Y")
		bill("Master BL", "C9", m_bl_no="_T-MBL-CC")

		set_container_cargo_category.execute()

		self.assertEqual(
			(
				get_container(mbl).imdg_code,
				get_container(mbl).plug_type_of_reefer,
				get_container(mbl).cargo_category,
			),
			("C9", "Y", "Dangerous"),
		)
		self.assertIsNone(get_container(hbl).imdg_code, "a delivered container is left as it is")
