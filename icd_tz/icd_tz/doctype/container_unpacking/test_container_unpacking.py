# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from icd_tz.tests.test_edi_movement import (
	CONTAINER_NO,
	M_BL_NO,
	make_gate_pass,
	make_manifest,
	make_reception,
)
from icd_tz.tests.test_storage_contract import set_settings_storage_days

test_ignore = ["Company", "Cost Center"]

H_BL_NOS = ("HBL-0001", "HBL-0002")

# an empty container is billed for storage only
CARGO_CHARGE_FLAGS = (
	"has_transport_charges",
	"has_shore_handling_charges",
	"has_stripping_charges",
	"has_custom_verification_charges",
	"has_removal_charges",
	"has_corridor_levy_charges",
)


def make_lcl_manifest(h_bl_nos=H_BL_NOS, gross_volume=4.5):
	"""An LCL box under M_BL_NO, its luggage listed under each house bill"""

	manifest = make_manifest()
	manifest.containers[0].freight_indicator = "LCL"
	for h_bl_no in h_bl_nos:
		manifest.append(
			"hbl_containers",
			{
				"m_bl_no": M_BL_NO,
				"h_bl_no": h_bl_no,
				"container_no": CONTAINER_NO,
				"container_size": "45G1",
				"freight_indicator": "LCL",
				"no_of_packages": "5",
			},
		)
		manifest.append(
			"house_bl",
			{
				"m_bl_no": M_BL_NO,
				"h_bl_no": h_bl_no,
				"number_of_package": 10,
				"gross_volume": gross_volume,
				"gross_volume_unit": "CBM",
			},
		)

	manifest.save(ignore_permissions=True)

	return manifest


def receive_lcl_box(**values) -> str:
	return make_reception(freight_indicator="LCL", **values).create_mbl_container()


def make_unpacking(container_id: str, consolidator_gross_volume: float = 2.5):
	"""Draft unpacking, the consolidator's CBM filled in where the manifest gives none"""

	unpacking = frappe.new_doc("Container Unpacking")
	unpacking.container_id = container_id
	unpacking.set_hbls()
	for row in unpacking.hbls:
		if not row.manifest_gross_volume:
			row.consolidator_gross_volume = consolidator_gross_volume

	# the clerk is an Employee, which this bench cannot make in a test
	unpacking.flags.ignore_mandatory = True
	unpacking.insert(ignore_permissions=True)

	return unpacking


def unpack_container(container_id: str, **values):
	unpacking = make_unpacking(container_id, **values)
	unpacking.submit()

	return unpacking


def get_hbl_containers(unpacking) -> list:
	return [frappe.get_doc("Container", row.container_id) for row in unpacking.hbls]


class TestContainerUnpacking(FrappeTestCase):
	"""HBL records exist only once the luggage is counted out of the LCL box"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		set_settings_storage_days()
		self.manifest = make_lcl_manifest()

	def tearDown(self):
		frappe.db.rollback()

	def test_receiving_an_lcl_box_creates_no_hbl_records(self):
		box = receive_lcl_box()

		self.assertEqual(frappe.get_all("Container", {"has_hbl": 1}, pluck="name"), [])
		self.assertEqual(frappe.db.get_value("Container", box, "is_empty_container"), 0)

	def test_the_rows_come_from_the_house_bills_of_the_manifest(self):
		unpacking = make_unpacking(receive_lcl_box())

		self.assertEqual([row.h_bl_no for row in unpacking.hbls], list(H_BL_NOS))
		self.assertEqual({row.manifest_packages for row in unpacking.hbls}, {10})
		self.assertEqual({row.manifest_gross_volume for row in unpacking.hbls}, {4.5})
		self.assertEqual({row.is_internal_hbl for row in unpacking.hbls}, {0})

	def test_the_shipping_line_code_comes_from_the_container(self):
		box = receive_lcl_box()

		unpacking = make_unpacking(box)

		self.assertEqual(unpacking.sline_code, frappe.db.get_value("Container", box, "sline_code"))
		self.assertEqual(unpacking.sline_code, "CMA")

	def test_submit_creates_one_hbl_record_per_house_bill(self):
		unpacking = unpack_container(receive_lcl_box())
		hbl_containers = get_hbl_containers(unpacking)

		self.assertEqual([row.h_bl_no for row in hbl_containers], list(H_BL_NOS))
		self.assertEqual({row.has_hbl for row in hbl_containers}, {1})
		self.assertEqual({row.is_empty_container for row in hbl_containers}, {0})
		self.assertEqual({row.gross_volume for row in hbl_containers}, {4.5})

	def test_the_box_is_left_empty_and_owes_storage_only(self):
		box = receive_lcl_box()
		frappe.db.set_value("Container", box, dict.fromkeys(CARGO_CHARGE_FLAGS, 1))

		unpack_container(box)

		container = frappe.get_doc("Container", box)
		self.assertEqual(container.is_empty_container, 1)
		self.assertEqual({container.get(flag) for flag in CARGO_CHARGE_FLAGS}, {0})

	def test_the_box_counts_storage_from_the_unpack_date(self):
		received_date = add_days(nowdate(), -5)
		box = receive_lcl_box(posting_date=received_date, ship_dc_date=received_date)

		unpacking = unpack_container(box)

		container = frappe.get_doc("Container", box)
		self.assertEqual(getdate(unpacking.posting_date), getdate(nowdate()))
		self.assertEqual(getdate(container.unpack_date), getdate(nowdate()))
		self.assertEqual(getdate(container.received_date), getdate(received_date))
		self.assertEqual([getdate(row.date) for row in container.container_dates], [getdate(nowdate())])

	def test_a_ship_dc_date_correction_keeps_the_unpack_date_as_storage_start(self):
		box = receive_lcl_box(posting_date=add_days(nowdate(), -5), ship_dc_date=add_days(nowdate(), -5))
		unpack_container(box)
		reception = frappe.get_doc(
			"Container Reception", frappe.db.get_value("Container", box, "container_reception")
		)

		reception.update_containers_received_date(add_days(nowdate(), -6), add_days(nowdate(), -6))

		container = frappe.get_doc("Container", box)
		self.assertEqual([getdate(row.date) for row in container.container_dates], [getdate(nowdate())])

	def test_a_bill_with_no_manifest_cbm_takes_the_consolidators(self):
		frappe.db.set_value("House BL", {"parent": self.manifest.name}, "gross_volume", 0)

		unpacking = unpack_container(receive_lcl_box(), consolidator_gross_volume=7.25)

		self.assertEqual({row.gross_volume for row in get_hbl_containers(unpacking)}, {7.25})

	def test_a_bill_with_no_cbm_at_all_is_saved_but_not_submitted(self):
		frappe.db.set_value("House BL", {"parent": self.manifest.name}, "gross_volume", 0)

		unpacking = make_unpacking(receive_lcl_box(), consolidator_gross_volume=0)

		self.assertRaises(frappe.ValidationError, unpacking.submit)

	def test_booking_an_lcl_box_before_unpacking_is_refused(self):
		booking = frappe.get_doc({"doctype": "In Yard Container Booking", "container_id": receive_lcl_box()})

		self.assertRaises(frappe.ValidationError, booking.validate_container_is_unpacked)

	def test_the_unpacked_cargo_and_its_empty_box_can_be_booked(self):
		box = receive_lcl_box()
		unpacking = unpack_container(box)

		for container_id in (box, unpacking.hbls[0].container_id):
			booking = frappe.get_doc({"doctype": "In Yard Container Booking", "container_id": container_id})
			booking.validate_container_is_unpacked()

	def test_the_count_records_a_shortage(self):
		unpacking = make_unpacking(receive_lcl_box())
		unpacking.hbls[0].counted_packages = 7
		unpacking.save(ignore_permissions=True)

		self.assertEqual([row.package_difference for row in unpacking.hbls], [-3, 0])

	def test_the_counted_cargo_goes_to_its_warehouse_location(self):
		location = frappe.get_doc({"doctype": "Container Location", "location_name": "_T Shed A"})
		location.insert(ignore_if_duplicate=True, ignore_permissions=True)
		unpacking = make_unpacking(receive_lcl_box())
		unpacking.hbls[0].location = location.name
		unpacking.save(ignore_permissions=True)
		unpacking.submit()

		self.assertEqual(get_hbl_containers(unpacking)[0].current_location, location.name)

	def test_an_fcl_container_is_refused(self):
		self.manifest.containers[0].freight_indicator = "FCL"
		self.manifest.save(ignore_permissions=True)

		self.assertRaises(frappe.ValidationError, make_unpacking, receive_lcl_box())

	def test_a_box_is_unpacked_once(self):
		box = receive_lcl_box()
		make_unpacking(box)

		self.assertRaises(frappe.ValidationError, make_unpacking, box)

	def test_a_box_with_a_linked_document_is_refused(self):
		box = receive_lcl_box()
		unpacking = make_unpacking(box)
		make_gate_pass(frappe.get_doc("Container", box))

		self.assertRaises(frappe.ValidationError, unpacking.submit)

	def test_cancel_removes_the_hbl_records_and_restores_the_box(self):
		box = receive_lcl_box()
		received_date = frappe.db.get_value("Container", box, "received_date")
		unpacking = unpack_container(box)
		hbl_containers = [row.container_id for row in unpacking.hbls]

		unpacking.cancel()

		container = frappe.get_doc("Container", box)
		self.assertFalse(frappe.get_all("Container", {"name": ["in", hbl_containers]}))
		self.assertEqual(container.is_empty_container, 0)
		self.assertIsNone(container.unpack_date)
		self.assertEqual(container.has_transport_charges, 1)
		self.assertEqual(container.has_shore_handling_charges, 1)
		self.assertEqual([row.date for row in container.container_dates], [received_date])

	def test_cancel_is_refused_while_an_hbl_record_has_a_linked_document(self):
		unpacking = unpack_container(receive_lcl_box())
		make_gate_pass(get_hbl_containers(unpacking)[0])

		self.assertRaises(frappe.ValidationError, unpacking.cancel)


class TestInternalHBLUnpacking(FrappeTestCase):
	"""A box the manifest gives no house bills is unpacked under ICD house bills"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		set_settings_storage_days()
		manifest = make_manifest()
		manifest.containers[0].freight_indicator = "LCL"
		manifest.save(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def test_the_bill_is_a_row_with_no_house_bill_until_submit(self):
		unpacking = make_unpacking(receive_lcl_box())

		self.assertEqual([(row.m_bl_no, row.is_internal_hbl) for row in unpacking.hbls], [(M_BL_NO, 1)])
		self.assertIsNone(unpacking.hbls[0].h_bl_no)

	def test_submit_gives_the_cargo_an_icd_house_bill(self):
		unpacking = unpack_container(receive_lcl_box())
		cargo = get_hbl_containers(unpacking)[0]

		self.assertTrue(unpacking.hbls[0].h_bl_no.startswith("ICD-HBL-"))
		self.assertEqual(cargo.h_bl_no, unpacking.hbls[0].h_bl_no)
		self.assertEqual((cargo.has_hbl, cargo.m_bl_no), (1, M_BL_NO))
		self.assertEqual(frappe.db.get_value("Container", {"has_hbl": 0}, "is_empty_container"), 1)
