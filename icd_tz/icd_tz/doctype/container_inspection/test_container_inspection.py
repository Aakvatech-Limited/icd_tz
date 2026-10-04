# Copyright (c) 2024, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from icd_tz.icd_tz.doctype.container_unpacking.test_container_unpacking import (
	CARGO_CHARGE_FLAGS,
	make_unpacking,
)
from icd_tz.tests.test_container_income_refs import insert
from icd_tz.tests.test_edi_codeco import make_partner
from icd_tz.tests.test_edi_movement import CONTAINER_NO, M_BL_NO, make_manifest, make_reception
from icd_tz.tests.test_port_expense_settings import make_item
from icd_tz.tests.test_storage_contract import set_settings_storage_days

test_ignore = ["Company", "Cost Center"]

SERVICE = "_T Stripping"


def inspect_container(container_id: str, is_additional_booking: int = 0, **service):
	"""Submitted inspection, its one service row changing the box to LCL unless told otherwise"""

	inspection = frappe.new_doc("Container Inspection")
	inspection.in_yard_container_booking = insert(
		"In Yard Container Booking",
		container_id=container_id,
		is_additional_booking=is_additional_booking,
		docstatus=1,
	).name
	inspection.append(
		"services",
		{"service": SERVICE, "status_changed_to": "LCL", "volume": "12.5", "counted_packages": 40, **service},
	)
	inspection.insert(ignore_permissions=True)
	inspection.submit()

	return inspection


def get_unpacking(inspection):
	return frappe.get_doc("Container Unpacking", {"container_inspection": inspection.name})


class TestInspectionLCLChange(FrappeTestCase):
	"""An FCL box changed to LCL at its inspection becomes the cargo's HBL record and a new empty box"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		set_settings_storage_days()
		make_item(SERVICE)
		make_manifest()
		self.received_date = add_days(nowdate(), -5)
		self.box = make_reception(
			posting_date=self.received_date, ship_dc_date=self.received_date
		).create_mbl_container()

	def tearDown(self):
		frappe.db.rollback()

	def test_submit_unpacks_the_box_on_a_submitted_unpacking(self):
		unpacking = get_unpacking(inspect_container(self.box))

		self.assertEqual(unpacking.docstatus, 1)
		self.assertEqual(unpacking.container_id, self.box)
		self.assertEqual(len(unpacking.hbls), 1)
		self.assertEqual(unpacking.hbls[0].container_id, self.box)
		self.assertEqual(unpacking.hbls[0].counted_packages, 40)

	def test_the_unpacking_is_timed_so_its_costco_goes_out(self):
		frappe.db.set_single_value("ICD TZ Settings", "enable_edi", 1)
		make_partner()

		unpacking = get_unpacking(inspect_container(self.box))

		self.assertTrue(unpacking.end_time)
		self.assertTrue(unpacking.edi_file)

	def test_the_box_becomes_the_cargo_record_under_an_icd_house_bill(self):
		inspect_container(self.box)

		cargo = frappe.get_doc("Container", self.box)
		self.assertEqual((cargo.has_hbl, cargo.is_empty_container), (1, 0))
		self.assertTrue(cargo.h_bl_no.startswith("ICD-HBL-"))
		self.assertEqual((cargo.freight_indicator, cargo.gross_volume), ("LCL", 12.5))

	def test_the_cargo_keeps_its_storage_days(self):
		dates = frappe.get_doc("Container", self.box).container_dates

		inspect_container(self.box)

		cargo = frappe.get_doc("Container", self.box)
		self.assertIsNone(cargo.unpack_date)
		self.assertEqual(getdate(cargo.container_dates[0].date), getdate(self.received_date))
		self.assertEqual([row.date for row in cargo.container_dates], [row.date for row in dates])

	def test_the_booking_and_inspection_take_the_house_bill(self):
		inspection = inspect_container(self.box)

		h_bl_no = frappe.db.get_value("Container", self.box, "h_bl_no")
		self.assertEqual(
			frappe.db.get_value("In Yard Container Booking", inspection.in_yard_container_booking, "h_bl_no"),
			h_bl_no,
		)
		self.assertEqual(frappe.db.get_value("Container Inspection", inspection.name, "h_bl_no"), h_bl_no)

	def test_a_new_empty_box_counts_storage_from_the_unpacking(self):
		unpacking = get_unpacking(inspect_container(self.box))

		empty = frappe.get_doc("Container", unpacking.empty_container_id)
		self.assertNotEqual(empty.name, self.box)
		self.assertEqual((empty.container_no, empty.m_bl_no), (CONTAINER_NO, M_BL_NO))
		self.assertEqual((empty.is_empty_container, empty.has_hbl, empty.h_bl_no), (1, 0, None))
		self.assertEqual(getdate(empty.unpack_date), getdate(nowdate()))
		self.assertEqual([getdate(row.date) for row in empty.container_dates], [getdate(nowdate())])
		self.assertEqual({empty.get(flag) for flag in CARGO_CHARGE_FLAGS}, {0})

	def test_an_inspection_with_no_status_change_unpacks_nothing(self):
		inspection = inspect_container(self.box, status_changed_to="", volume="", counted_packages=0)

		self.assertFalse(frappe.db.exists("Container Unpacking", {"container_inspection": inspection.name}))
		self.assertEqual(frappe.db.get_value("Container", self.box, "has_hbl"), 0)

	def test_an_additional_inspection_cannot_split_the_box_again(self):
		inspect_container(self.box)

		self.assertRaises(frappe.ValidationError, inspect_container, self.box, is_additional_booking=1)
		self.assertEqual(frappe.db.count("Container Unpacking", {"container_id": self.box}), 1)

	def test_the_manifest_unpacking_refuses_the_cargo_record(self):
		inspect_container(self.box)

		self.assertRaises(frappe.ValidationError, make_unpacking, self.box)

	def test_the_unpacking_cannot_be_cancelled(self):
		unpacking = get_unpacking(inspect_container(self.box))

		self.assertRaises(frappe.ValidationError, unpacking.cancel)

	def test_the_inspection_cannot_be_cancelled_once_unpacked(self):
		inspection = inspect_container(self.box)

		self.assertRaises(frappe.LinkExistsError, inspection.cancel)

	def test_an_unpacking_must_be_for_the_inspected_container(self):
		inspection = inspect_container(self.box)
		other_box = make_reception(container_no="MSCU7654321").create_mbl_container()

		self.assertRaises(
			frappe.ValidationError, make_unpacking, other_box, container_inspection=inspection.name
		)

	def test_an_unpacking_needs_an_inspection_that_changes_to_lcl(self):
		inspection = inspect_container(self.box, status_changed_to="", volume="", counted_packages=0)

		self.assertRaises(
			frappe.ValidationError, make_unpacking, self.box, container_inspection=inspection.name
		)
