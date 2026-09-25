# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from icd_tz.tests.test_port_expenses import BOX_20, make_manifest, make_movement_order, set_discharge_date

test_ignore = ["Company", "Cost Center"]

TANESW = "icd_tz.icd_tz.doctype.container_movement_order.container_movement_order.get_discharge_date"


class TestMovementOrderShipDCDate(FrappeTestCase):
	"""A movement order takes the discharge date the ICD Container already holds"""

	def setUp(self):
		manifest = make_manifest()
		manifest.submit()
		self.manifest = manifest.name
		self.order = make_movement_order(self.manifest, BOX_20)
		self.order.ship_dc_date = None

	def tearDown(self):
		frappe.db.rollback()

	def test_a_date_on_the_icd_container_skips_tanesw(self):
		set_discharge_date(self.manifest, BOX_20, add_days(nowdate(), -3))

		with patch(TANESW) as tanesw:
			self.order.set_ship_dc_date()

		tanesw.assert_not_called()
		self.assertEqual(getdate(self.order.ship_dc_date), getdate(add_days(nowdate(), -3)))

	def test_tanesw_is_asked_when_the_icd_container_has_no_date(self):
		with patch(TANESW, return_value=getdate(add_days(nowdate(), -5))) as tanesw:
			self.order.set_ship_dc_date()

		tanesw.assert_called_once()
		self.assertEqual(getdate(self.order.ship_dc_date), getdate(add_days(nowdate(), -5)))

	def test_a_date_already_on_the_order_is_kept(self):
		set_discharge_date(self.manifest, BOX_20, add_days(nowdate(), -3))
		self.order.ship_dc_date = add_days(nowdate(), -1)

		self.order.set_ship_dc_date()

		self.assertEqual(getdate(self.order.ship_dc_date), getdate(add_days(nowdate(), -1)))
