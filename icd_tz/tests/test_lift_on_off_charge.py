# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.tests.test_container_income_refs import (
	bill,
	get_container,
	insert,
	make_reception_containers,
	with_settings,
)
from icd_tz.tests.test_icd_services import services_settings, submit_invoice
from icd_tz.tests.test_lcl_gross_volume import make_service_order
from icd_tz.tests.test_service_criteria import criteria

test_ignore = ["Company", "Cost Center"]

LIFT_ITEM = "_T Lift On/Off"
LOOSE_LIFT_ITEM = "_T Loose Lift On/Off"
LIFT_ITEMS = (LIFT_ITEM, LOOSE_LIFT_ITEM)


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
	"""An HBL container is lifted at least once, and once for each of its inspections"""

	def tearDown(self):
		frappe.db.rollback()

	def charged_container(self, inspections: tuple = (), **values):
		_, hbl = make_reception_containers(cargo_type="Local")
		frappe.db.set_value("Container", hbl, {"has_lift_on_off_charge": 1, "h_bl_no": "HBL-1", **values})
		for docstatus in inspections:
			insert("Container Inspection", container_id=hbl, h_bl_no="HBL-1", docstatus=docstatus)

		return hbl

	def get_lift_qty(self, container_id, **order_values):
		order_values = {"container_status": "FCL", "container_size": "22G1", "port": "TEAGTL", **order_values}
		service_order = make_service_order(container_id=container_id, **order_values)
		settings_doc = services_settings(loose_rows=[criteria("Lift On/Off", LOOSE_LIFT_ITEM)])
		with with_settings(settings_doc):
			service_order.add_container_services(settings_doc)

		return next((row.qty for row in service_order.services if row.service in LIFT_ITEMS), 0)

	def test_a_container_without_inspections_is_lifted_once(self):
		self.assertEqual(self.get_lift_qty(self.charged_container()), 1)

	def test_each_draft_or_submitted_inspection_is_one_lift(self):
		self.assertEqual(self.get_lift_qty(self.charged_container(inspections=(0, 1, 1, 2))), 3)

	def test_an_lcl_lift_is_charged_per_cbm(self):
		container_id = self.charged_container(inspections=(1, 1))

		qty = self.get_lift_qty(container_id, container_status="LCL", gross_volume=5)

		self.assertEqual(qty, 10)

	def test_only_the_unbilled_lifts_are_ordered(self):
		container_id = self.charged_container(inspections=(1, 1, 1), lo_sales_invoice="_T-LO")
		bill("_T-LO", container_id, LIFT_ITEM, qty=2)

		self.assertEqual(self.get_lift_qty(container_id), 1)

	def test_every_lift_invoice_is_kept_and_a_return_drops_its_invoice(self):
		container_id = self.charged_container()

		submit_invoice(LIFT_ITEM, container_id, name="_T-LO-1")
		submit_invoice(LIFT_ITEM, container_id, name="_T-LO-2")
		self.assertEqual(get_container(container_id).lo_sales_invoice, "_T-LO-1,_T-LO-2")

		submit_invoice(LIFT_ITEM, container_id, is_return=1, name="_T-RET-1", return_against="_T-LO-1")
		self.assertEqual(get_container(container_id).lo_sales_invoice, "_T-LO-2")
