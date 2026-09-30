# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from icd_tz.tests.test_port_expenses import (
	BOX_20,
	BOX_40,
	M_BL_NO,
	make_manifest,
	make_movement_order,
	set_discharge_date,
)

test_ignore = ["Company", "Cost Center"]

UNPAID = "icd_tz.icd_tz.doctype.container_movement_order.container_movement_order.get_unpaid_port_charges"


class TestBestPick(FrappeTestCase):
	"""A best pick order goes to the port with no container and gets it once the driver picks one"""

	def setUp(self):
		manifest = make_manifest()
		manifest.submit()
		self.manifest = manifest.name
		set_discharge_date(self.manifest, BOX_20, add_days(nowdate(), -4))

	def tearDown(self):
		frappe.db.rollback()

	def test_an_order_with_no_container_needs_best_pick(self):
		order = make_movement_order(self.manifest, None)

		self.assertRaises(frappe.ValidationError, order.validate_best_pick)

	def test_a_best_pick_order_cannot_name_its_container_on_submit(self):
		order = make_movement_order(self.manifest, BOX_20)
		order.best_pick = 1

		self.assertRaises(frappe.ValidationError, order.validate_best_pick)

	def test_a_best_pick_order_submits_without_discharge_date_or_port_charges(self):
		order = make_best_pick_order(self.manifest)

		with patch(UNPAID, return_value=["Shore"]):
			order.before_submit()

		self.assertEqual(order.status, "Pending")

	def test_a_plain_order_still_needs_its_discharge_date_on_submit(self):
		order = make_movement_order(self.manifest, BOX_20)
		order.ship_dc_date = None

		with patch(UNPAID, return_value=[]):
			self.assertRaises(frappe.ValidationError, order.before_submit)

	def test_the_picked_container_is_set_after_submit(self):
		order = make_submitted_best_pick_order(self.manifest)
		pick_container(order, BOX_20)

		with patch(UNPAID, return_value=[]):
			order.before_update_after_submit()
			order.on_update_after_submit()

		self.assertEqual(getdate(order.ship_dc_date), getdate(add_days(nowdate(), -4)))
		self.assertEqual(order.container_count, "1/2")
		self.assertEqual(get_has_order(self.manifest, BOX_20), 1)

	def test_the_picked_container_waits_for_the_port_charges(self):
		order = make_submitted_best_pick_order(self.manifest)
		pick_container(order, BOX_20)

		with patch(UNPAID, return_value=["Shore"]):
			self.assertRaises(frappe.ValidationError, order.before_update_after_submit)

	def test_the_picked_container_must_be_on_the_manifest(self):
		order = make_submitted_best_pick_order(self.manifest)
		pick_container(order, "NOSUCH0000000")

		with patch(UNPAID, return_value=[]):
			self.assertRaises(frappe.ValidationError, order.before_update_after_submit)

	def test_the_picked_container_cannot_be_changed(self):
		order = make_submitted_best_pick_order(self.manifest)
		pick_container(order, BOX_20)
		snapshot(order)
		pick_container(order, BOX_40)

		self.assertRaises(frappe.ValidationError, order.before_update_after_submit)

	def test_a_plain_order_cannot_change_its_container_after_submit(self):
		order = make_movement_order(self.manifest, BOX_20)
		order.docstatus = 1
		snapshot(order)
		pick_container(order, BOX_40)

		self.assertRaises(frappe.ValidationError, order.before_update_after_submit)

	def test_other_updates_after_submit_leave_the_container_alone(self):
		order = make_submitted_best_pick_order(self.manifest)
		order.status = "Received"

		# nothing to raise
		self.assertIsNone(order.before_update_after_submit())
		self.assertFalse(order.container_no)

	def test_a_reception_needs_the_container_of_its_order(self):
		reception = frappe.new_doc("Container Reception")
		reception.update({"manifest": self.manifest, "movement_order": "ICD-CMO-TEST-0001"})

		self.assertRaises(frappe.ValidationError, reception.validate_container_no)

		reception.container_no = BOX_20
		self.assertIsNone(reception.validate_container_no())


def make_best_pick_order(manifest):
	order = make_movement_order(manifest, None)
	order.update({"best_pick": 1, "m_bl_no": None, "ship_dc_date": None})

	return order


def make_submitted_best_pick_order(manifest):
	order = make_best_pick_order(manifest)
	order.docstatus = 1
	snapshot(order)

	return order


def snapshot(order):
	"""Take the order as it is now for the copy the database holds"""

	order._doc_before_save = frappe.get_doc(order.as_dict())


def pick_container(order, container_no):
	"""What the Select Container dialog sets"""

	order.update(
		{
			"container_no": container_no,
			"m_bl_no": M_BL_NO,
			"size": "20",
			"freight_indicator": "FCL",
			"cargo_type": "Local",
		}
	)


def get_has_order(manifest, container_no):
	return frappe.db.get_value(
		"Containers Detail", {"parent": manifest, "container_no": container_no}, "has_order"
	)
