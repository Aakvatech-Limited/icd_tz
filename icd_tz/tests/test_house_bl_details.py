# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from icd_tz.tests.test_edi_movement import CONTAINER_NO, M_BL_NO, make_manifest, make_reception
from icd_tz.tests.test_storage_contract import set_settings_storage_days

test_ignore = ["Company", "Cost Center"]

H_BL_NO = "HBL-DETAILS-1"
CONSOLIDATOR = "_Test Groupage Consolidator"
HOUSE_CONSIGNEE = "_Test House Consignee"


class TestHouseBLDetails(FrappeTestCase):
	"""A house bill record takes its details from its own House BL row"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		set_settings_storage_days()
		for name in (CONSOLIDATOR, HOUSE_CONSIGNEE):
			if not frappe.db.exists("Consignee", name):
				frappe.get_doc({"doctype": "Consignee", "consignee_name": name}).insert(
					ignore_permissions=True
				)

		manifest = make_manifest()
		manifest.master_bl[0].consignee_name = CONSOLIDATOR
		manifest.master_bl[0].gross_volume = 38.816
		manifest.master_bl[0].cargo_classification = "IM"
		manifest.append(
			"hbl_containers",
			{"m_bl_no": M_BL_NO, "h_bl_no": H_BL_NO, "container_no": CONTAINER_NO, "container_size": "45G1"},
		)
		manifest.append(
			"house_bl",
			{
				"m_bl_no": M_BL_NO,
				"h_bl_no": H_BL_NO,
				"consignee_name": HOUSE_CONSIGNEE,
				"gross_volume": 3.0,
				"cargo_classification": "TR",
				"place_of_destination": "CDFBM",
			},
		)
		manifest.save(ignore_permissions=True)
		self.reception = make_reception(freight_indicator="LCL")

	def tearDown(self):
		frappe.db.rollback()

	def make_house_bill_record(self):
		container = frappe.new_doc("Container")
		container.update(
			{
				"container_reception": self.reception.name,
				"container_no": CONTAINER_NO,
				"manifest": self.reception.manifest,
				"m_bl_no": M_BL_NO,
				"h_bl_no": H_BL_NO,
				"has_hbl": 1,
			}
		)
		container.append("container_dates", {"date": nowdate()})
		container.flags.ignore_mandatory = True
		container.insert(ignore_permissions=True)

		return container

	def test_the_volume_is_the_house_bills_not_the_whole_box(self):
		# storage is billed by volume, so the box's figure charged every consignee for all of it
		self.assertEqual(self.make_house_bill_record().gross_volume, 3.0)

	def test_the_cargo_type_is_the_house_bills(self):
		self.assertEqual(self.make_house_bill_record().cargo_type, "Transit")

	def test_the_destination_is_the_house_bills(self):
		self.assertEqual(self.make_house_bill_record().place_of_destination, "DRC")

	def test_the_consignee_is_the_house_bills(self):
		self.assertEqual(self.make_house_bill_record().consignee, HOUSE_CONSIGNEE)
