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
	"""A Service Order warns on save and refuses to submit LCL cargo with no gross volume"""

	def tearDown(self):
		frappe.db.rollback()

	def test_saving_warns_that_the_gross_volume_is_missing(self):
		frappe.clear_messages()

		make_service_order().before_save()

		self.assertIn("Gross Volume", str(frappe.get_message_log()))

	def test_submitting_is_refused_without_a_gross_volume(self):
		self.assertRaises(frappe.ValidationError, make_service_order().before_submit)

	def test_a_gross_volume_clears_the_check(self):
		self.assertFalse(make_service_order(gross_volume=3.5).is_missing_gross_volume)

	def test_an_fcl_container_needs_no_gross_volume(self):
		self.assertFalse(make_service_order(container_status="FCL").is_missing_gross_volume)
