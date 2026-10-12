# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from icd_tz.icd_tz.api import tanesw
from icd_tz.tests.test_tanesw_discharge import M_BL_NO, FakeTracking

MANIFEST = "MTEST-2026-00099"


class TestICDContainer(FrappeTestCase):
	"""The Fetch Ship D/C Date button on one container"""

	def tearDown(self):
		frappe.db.rollback()

	def make_container(self, container_no, m_bl_no=M_BL_NO, ship_dc_date=None):
		container = frappe.new_doc("ICD Container")
		container.update(
			{
				"container_no": container_no,
				"manifest": MANIFEST,
				"m_bl_no": m_bl_no,
				"ship_dc_date": ship_dc_date,
			}
		)
		container.flags.ignore_mandatory = True
		container.flags.ignore_links = True
		container.insert(ignore_permissions=True)

		return container

	def test_the_discharge_date_is_fetched_and_saved(self):
		container = self.make_container("BEAU5429741")

		with patch.object(tanesw, "call_tracking_api", FakeTracking()):
			ship_dc_date = container.fetch_ship_dc_date()

		self.assertEqual(ship_dc_date, getdate("2025-03-09"))
		self.assertEqual(frappe.db.get_value("ICD Container", container.name, "ship_dc_date"), ship_dc_date)

	def test_a_container_without_an_approved_discharge_stays_empty(self):
		container = self.make_container("FDCU0533798")

		with patch.object(tanesw, "call_tracking_api", FakeTracking()):
			self.assertIsNone(container.fetch_ship_dc_date())

	def test_a_set_date_is_not_looked_up_again(self):
		container = self.make_container("BEAU5429741", ship_dc_date="2025-01-01")
		fake = FakeTracking()

		with patch.object(tanesw, "call_tracking_api", fake):
			self.assertRaises(frappe.ValidationError, container.fetch_ship_dc_date)

		self.assertEqual(fake.calls, [])

	def test_a_container_without_a_bill_is_refused(self):
		container = self.make_container("BEAU5429741", m_bl_no=None)

		self.assertRaises(frappe.ValidationError, container.fetch_ship_dc_date)
