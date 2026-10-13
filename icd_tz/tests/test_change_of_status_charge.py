# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.tests.test_container_income_refs import (
	make_reception_containers,
	with_settings,
)
from icd_tz.tests.test_icd_services import services_settings
from icd_tz.tests.test_lcl_gross_volume import make_service_order
from icd_tz.tests.test_service_criteria import criteria

test_ignore = ["Company", "Cost Center"]

LOOSE_ITEM = "_T Loose Change of Status"


class TestChangeOfStatusOrder(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def get_order_services(self, **values):
		_, hbl = make_reception_containers(cargo_type="Local")
		frappe.db.set_value("Container", hbl, {"has_change_of_status_charge": 1, **values})
		service_order = make_service_order(
			container_id=hbl, container_status="LCL", container_size="22G1", port="TEAGTL", gross_volume=5
		)
		settings_doc = services_settings(loose_rows=[criteria("Change of Status", LOOSE_ITEM)])
		with with_settings(settings_doc):
			service_order.add_container_services(settings_doc)

		return [(row.service, row.qty) for row in service_order.services]

	def test_the_lcl_order_charges_the_change_per_cbm(self):
		self.assertIn((LOOSE_ITEM, 5), self.get_order_services())

	def test_an_invoiced_change_is_not_ordered_again(self):
		services = [service for service, _ in self.get_order_services(cs_sales_invoice="_T-CS")]

		self.assertNotIn(LOOSE_ITEM, services)
