# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

test_ignore = ["Company", "Cost Center"]


class TestInspectionVerification(FrappeTestCase):
	"""Custom verification is charged from the booking, never added to the inspection"""

	def tearDown(self):
		frappe.db.rollback()

	def test_a_verification_booking_adds_no_service_to_the_inspection(self):
		booking = frappe.new_doc("In Yard Container Booking")
		booking.update(
			{"container_no": "VERU1234567", "has_custom_verification_charges": "Yes", "docstatus": 1}
		)
		booking.flags.ignore_mandatory = True
		booking.db_insert()

		inspection = frappe.new_doc("Container Inspection")
		inspection.update({"in_yard_container_booking": booking.name, "container_no": "VERU1234567"})
		inspection.flags.ignore_mandatory = True
		inspection.insert(ignore_permissions=True)

		self.assertEqual(inspection.services, [])
