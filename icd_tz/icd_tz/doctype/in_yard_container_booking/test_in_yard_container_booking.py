# Copyright (c) 2024, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.utils import get_no_containers_message
from icd_tz.icd_tz.doctype.gate_pass.test_gate_pass import make_container

test_ignore = ["Company", "Cost Center"]


class TestBulkBookingMessage(FrappeTestCase):
	"""A bulk action that finds no container says why"""

	def tearDown(self):
		frappe.db.rollback()

	def test_an_m_bl_of_house_bill_containers_points_to_the_h_bl(self):
		make_container(m_bl_no="_T-MBL-HBL", h_bl_no="_T-HBL-1", has_hbl=1, status="In Yard")

		message = get_no_containers_message("_T-MBL-HBL", None)

		self.assertIn("H BL No instead", message)

	def test_an_m_bl_of_delivered_house_bills_is_not_found(self):
		make_container(m_bl_no="_T-MBL-OUT", h_bl_no="_T-HBL-2", has_hbl=1, status="Delivered")

		message = get_no_containers_message("_T-MBL-OUT", None)

		self.assertIn("No Containers found", message)

	def test_an_unknown_h_bl_is_not_found(self):
		self.assertIn("No Containers found", get_no_containers_message(None, "_T-HBL-NONE"))
