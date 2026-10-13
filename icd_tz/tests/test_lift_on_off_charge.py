# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.patches import set_lift_on_off_charge
from icd_tz.tests.test_container_income_refs import (
	get_container,
	insert,
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


class TestLiftOnOffPatch(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def add_inspection(self, container_id: str, service: str, docstatus=1, sales_invoice=None):
		inspection = insert("Container Inspection", container_id=container_id, docstatus=docstatus)
		insert(
			"Container Inspection Detail",
			parent=inspection.name,
			parenttype="Container Inspection",
			parentfield="services",
			service=service,
			sales_invoice=sales_invoice,
		)

	def get_charge(self, container_id):
		container = get_container(container_id)
		return container.has_lift_on_off_charge, container.lo_sales_invoice

	def test_a_lift_service_flags_the_container_and_copies_its_invoice(self):
		paid, unpaid = make_reception_containers()
		insert("Sales Invoice", name="_T-SINV-LIFT", docstatus=1)
		self.add_inspection(paid, "Lift Off 20ft", sales_invoice="_T-SINV-LIFT")
		self.add_inspection(unpaid, "LIFT ON")

		set_lift_on_off_charge.execute()

		self.assertEqual(self.get_charge(paid), (1, "_T-SINV-LIFT"))
		self.assertEqual(self.get_charge(unpaid), (1, None))

	def test_a_cancelled_invoice_is_not_copied(self):
		mbl, _ = make_reception_containers()
		insert("Sales Invoice", name="_T-SINV-LIFT", docstatus=2)
		self.add_inspection(mbl, "Lift Off", sales_invoice="_T-SINV-LIFT")

		set_lift_on_off_charge.execute()

		self.assertEqual(self.get_charge(mbl), (1, None))

	def test_other_services_and_draft_inspections_change_nothing(self):
		mbl, hbl = make_reception_containers()
		self.add_inspection(mbl, "Status Change")
		self.add_inspection(hbl, "Lift Off", docstatus=0)

		set_lift_on_off_charge.execute()

		self.assertEqual(self.get_charge(mbl), (0, None))
		self.assertEqual(self.get_charge(hbl), (0, None))
