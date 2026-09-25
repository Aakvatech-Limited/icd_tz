# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.sales_order import validate_lcl_gross_volume
from icd_tz.tests.test_edi_movement import make_manifest, make_reception
from icd_tz.tests.test_empty_container_billing import make_order_for
from icd_tz.tests.test_storage_contract import set_settings_storage_days

test_ignore = ["Company", "Cost Center"]


def make_service_order(**values):
	order = frappe.new_doc("Service Order")
	order.update(
		{
			"container_no": "LCLU1234567",
			"container_status": "LCL",
			"c_and_f_company": "_Test C and F",
			"clearing_agent": "_Test Agent",
			"consignee": "_Test Consignee",
			**values,
		}
	)

	return order


class TestSalesOrderGrossVolume(FrappeTestCase):
	"""A Sales Order cannot bill LCL cargo that has no gross volume"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		set_settings_storage_days()
		self.manifest = make_manifest()

	def tearDown(self):
		frappe.db.rollback()

	def receive(self, freight_indicator):
		self.manifest.containers[0].freight_indicator = freight_indicator
		self.manifest.save(ignore_permissions=True)
		reception = make_reception(freight_indicator=freight_indicator)
		reception.create_hbl_container(reception.create_mbl_container())

		return frappe.get_all(
			"Container", {"container_reception": reception.name}, pluck="name", order_by="creation"
		)

	def test_lcl_cargo_with_no_gross_volume_is_refused(self):
		cargo = self.receive("LCL")[1]

		self.assertRaises(frappe.ValidationError, validate_lcl_gross_volume, make_order_for(cargo))

	def test_lcl_cargo_with_a_gross_volume_is_billed(self):
		cargo = self.receive("LCL")[1]
		frappe.db.set_value("Container", cargo, "gross_volume", 3.5)

		validate_lcl_gross_volume(make_order_for(cargo))

	def test_an_empty_box_is_billed_without_a_gross_volume(self):
		box = self.receive("LCL")[0]

		validate_lcl_gross_volume(make_order_for(box))

	def test_an_fcl_container_is_billed_without_a_gross_volume(self):
		container = self.receive("FCL")[0]

		validate_lcl_gross_volume(make_order_for(container))


class TestServiceOrderGrossVolume(FrappeTestCase):
	"""A Service Order takes a missing gross volume from the Container, or refuses to go on"""

	def tearDown(self):
		frappe.db.rollback()

	def make_container(self, gross_volume):
		container = frappe.new_doc("Container")
		container.update(
			{"container_no": "LCLU1234567", "freight_indicator": "LCL", "gross_volume": gross_volume}
		)
		container.db_insert()

		return container.name

	def test_a_missing_volume_is_taken_from_the_container(self):
		order = make_service_order(container_id=self.make_container(4.2))

		order.set_gross_volume()

		self.assertEqual(order.gross_volume, 4.2)

	def test_saving_is_refused_when_the_container_has_no_volume(self):
		order = make_service_order(container_id=self.make_container(0))

		self.assertRaises(frappe.ValidationError, order.before_save)

	def test_submitting_is_refused_when_the_container_has_no_volume(self):
		order = make_service_order(container_id=self.make_container(0))

		self.assertRaises(frappe.ValidationError, order.before_submit)

	def test_a_volume_on_the_order_is_kept(self):
		order = make_service_order(container_id=self.make_container(0), gross_volume=3.5)

		order.set_gross_volume()

		self.assertEqual(order.gross_volume, 3.5)

	def test_an_fcl_container_needs_no_gross_volume(self):
		make_service_order(container_status="FCL").set_gross_volume()
