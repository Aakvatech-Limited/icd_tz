# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.tests.test_edi_movement import CONTAINER_NO, M_BL_NO, make_manifest, make_reception

test_ignore = ["Company", "Cost Center"]

H_BL_NOS = ("HBL-0001", "HBL-0002")


class TestEmptyContainerFlag(FrappeTestCase):
	"""A box is empty only once its luggage has been taken out of it"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		self.manifest = make_manifest()

	def tearDown(self):
		frappe.db.rollback()

	def test_a_full_container_is_never_marked_empty(self):
		containers = self.receive(freight_indicator="FCL")

		self.assertEqual(len(containers), 1)
		self.assertEqual(containers[0].is_empty_container, 0)

	def test_a_box_whose_luggage_became_its_own_records_is_marked_empty(self):
		self.add_house_bills()

		containers = self.receive(freight_indicator="LCL")
		box, luggage = containers[0], containers[1:]

		self.assertEqual(len(luggage), len(H_BL_NOS))
		self.assertEqual([row.has_hbl for row in luggage], [1] * len(H_BL_NOS))
		self.assertEqual(box.is_empty_container, 1)
		self.assertEqual([row.is_empty_container for row in luggage], [0] * len(H_BL_NOS))

	def test_a_single_consignee_box_records_its_cargo_and_the_empty_box_apart(self):
		# no house bill to split the cargo onto, so the cargo becomes its own record
		# billed to the consignee and the box stays on the shipping line account
		containers = self.receive(freight_indicator="LCL")
		box, cargo = containers

		self.assertEqual(len(containers), 2)
		self.assertEqual(box.is_empty_container, 1)
		self.assertEqual(cargo.is_empty_container, 0)
		self.assertEqual([box.has_hbl, cargo.has_hbl], [0, 0])
		self.assertFalse(cargo.h_bl_no)
		self.assertEqual({row.m_bl_no for row in containers}, {M_BL_NO})

	def test_the_cargo_record_of_a_single_consignee_box_is_billable(self):
		from icd_tz.icd_tz.api.utils import get_cargo_container_ids

		containers = self.receive(freight_indicator="LCL")
		cargo = containers[1]

		self.assertEqual(get_cargo_container_ids(M_BL_NO), [cargo.name])

	def add_house_bills(self):
		for h_bl_no in H_BL_NOS:
			self.manifest.append(
				"hbl_containers",
				{
					"m_bl_no": M_BL_NO,
					"h_bl_no": h_bl_no,
					"container_no": CONTAINER_NO,
					"container_size": "45G1",
					"freight_indicator": "LCL",
				},
			)

		self.manifest.save(ignore_permissions=True)

	def receive(self, **values):
		reception = make_reception(**values)
		reception.create_hbl_container(reception.create_mbl_container())

		return [
			frappe.get_doc("Container", name)
			for name in frappe.get_all(
				"Container", {"container_reception": reception.name}, pluck="name", order_by="creation"
			)
		]
