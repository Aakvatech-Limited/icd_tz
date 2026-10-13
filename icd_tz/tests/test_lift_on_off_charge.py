# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.tests.test_container_income_refs import (
	get_container,
	make_reception_containers,
	with_settings,
)
from icd_tz.tests.test_icd_services import services_settings
from icd_tz.tests.test_lcl_gross_volume import make_service_order

test_ignore = ["Company", "Cost Center"]

LIFT_ITEM = "_T Lift On/Off"


class TestLiftOnOffFlag(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def save(self, container_id):
		with with_settings(services_settings()):
			frappe.get_doc("Container", container_id).save(ignore_permissions=True)

		return get_container(container_id).has_lift_on_off_charge

	def test_an_hbl_container_owes_the_charge_on_save(self):
		_, hbl = make_reception_containers()
		for cargo_type in ("Local", "Transit"):
			frappe.db.set_value("Container", hbl, {"cargo_type": cargo_type, "has_lift_on_off_charge": 0})

			self.assertEqual(self.save(hbl), 1, cargo_type)

	def test_an_mbl_container_does_not_owe_the_charge(self):
		mbl, _ = make_reception_containers()

		self.assertEqual(self.save(mbl), 0)


class TestLiftOnOffBilling(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def charged_container(self, **values):
		_, hbl = make_reception_containers(cargo_type="Local")
		frappe.db.set_value("Container", hbl, {"has_lift_on_off_charge": 1, **values})
		return hbl

	def get_order_services(self, container_id, **order_values):
		order_values = {"container_status": "FCL", "container_size": "22G1", "port": "TEAGTL", **order_values}
		service_order = make_service_order(container_id=container_id, **order_values)
		settings_doc = services_settings()
		with with_settings(settings_doc):
			service_order.add_container_services(settings_doc)

		return [row.service for row in service_order.services]

	def test_the_service_order_adds_the_charge_from_the_criteria(self):
		self.assertIn(LIFT_ITEM, self.get_order_services(self.charged_container()))

	def test_an_invoiced_charge_is_not_ordered_again(self):
		self.assertNotIn(LIFT_ITEM, self.get_order_services(self.charged_container(lo_sales_invoice="_T-LO")))
