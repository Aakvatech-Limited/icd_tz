# Copyright (c) 2024, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

test_ignore = ["Company", "Cost Center"]


class TestGatePass(FrappeTestCase):
	"""An empty container is held back only by its unpaid storage days"""

	def tearDown(self):
		frappe.db.rollback()

	def test_empty_container_ignores_other_charges(self):
		container = make_container(days_to_be_billed=0, has_removal_charges="Yes", has_cancellation_charge=1)
		gate_pass = make_gate_pass(container, is_empty_container=1)

		gate_pass.validate_pending_payments()

	def test_empty_container_with_storage_days_is_blocked(self):
		container = make_container(days_to_be_billed=3, has_removal_charges="Yes")
		gate_pass = make_gate_pass(container, is_empty_container=1)

		with self.assertRaises(frappe.ValidationError) as error:
			gate_pass.validate_pending_payments()

		self.assertIn("Storage Charges", str(error.exception))
		self.assertNotIn("Removal Charges", str(error.exception))

	def test_full_container_still_checks_other_charges(self):
		container = make_container(days_to_be_billed=0, has_removal_charges="Yes")
		gate_pass = make_gate_pass(container, is_empty_container=0, action_for_missing_booking="Continue")

		with self.assertRaises(frappe.ValidationError) as error:
			gate_pass.validate_pending_payments()

		self.assertIn("Removal Charges", str(error.exception))


def make_container(**values):
	container = frappe.get_doc({"doctype": "Container", "container_no": "GPTU1234567", **values})
	container.set_new_name()
	container.db_insert()
	return container


def make_gate_pass(container, **values):
	return frappe.get_doc(
		{
			"doctype": "Gate Pass",
			"container_id": container.name,
			"container_no": container.container_no,
			**values,
		}
	)
