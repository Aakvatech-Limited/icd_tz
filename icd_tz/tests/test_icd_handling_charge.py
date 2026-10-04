# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.icd_services import RECEPTION, get_scope_services
from icd_tz.icd_tz.api.utils import DELIVERED_CONTAINER_STATUSES
from icd_tz.icd_tz.doctype.container.container import daily_update_date_container_stay
from icd_tz.icd_tz.doctype.gate_pass.test_gate_pass import make_gate_pass
from icd_tz.tests.test_container_income_refs import get_container, make_reception_containers, with_settings
from icd_tz.tests.test_edi_movement import make_manifest, make_reception
from icd_tz.tests.test_icd_services import services_settings, submit_invoice
from icd_tz.tests.test_lcl_gross_volume import make_service_order
from icd_tz.tests.test_service_criteria import criteria, settings
from icd_tz.tests.test_storage_contract import set_settings_storage_days

test_ignore = ["Company", "Cost Center"]

RECEPTION_FLAGS = [service.flag_field for service in get_scope_services(RECEPTION)]


def clear_reception_flags(container_id, **values):
	frappe.db.set_value("Container", container_id, {**dict.fromkeys(RECEPTION_FLAGS, 0), **values})


def get_reception_flags(container_id):
	return [get_container(container_id)[field] for field in RECEPTION_FLAGS]


class TestICDHandlingFlag(FrappeTestCase):
	"""Every loaded container in the yard owes ICD Handling, set again on each save"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		set_settings_storage_days()
		make_manifest()
		self.container_id = make_reception().create_mbl_container()

	def tearDown(self):
		frappe.db.rollback()

	def test_a_received_container_owes_icd_handling(self):
		self.assertIn("has_icd_handling_charge", RECEPTION_FLAGS)
		self.assertEqual(get_reception_flags(self.container_id), [1] * len(RECEPTION_FLAGS))

	def test_the_daily_save_flags_an_in_yard_container_without_charges(self):
		clear_reception_flags(self.container_id)

		with (
			patch("icd_tz.icd_tz.doctype.container.container.sleep"),
			patch("frappe.db.commit"),
		):
			daily_update_date_container_stay(self.container_id)

		self.assertEqual(get_reception_flags(self.container_id), [1] * len(RECEPTION_FLAGS))

	def test_a_container_past_its_gate_pass_is_not_flagged(self):
		for status in DELIVERED_CONTAINER_STATUSES:
			clear_reception_flags(self.container_id, status=status)

			frappe.get_doc("Container", self.container_id).save(ignore_permissions=True)

			self.assertEqual(get_reception_flags(self.container_id), [0] * len(RECEPTION_FLAGS), status)

	def test_an_empty_container_is_not_flagged(self):
		clear_reception_flags(self.container_id, is_empty_container=1)

		frappe.get_doc("Container", self.container_id).save(ignore_permissions=True)

		self.assertEqual(get_reception_flags(self.container_id), [0] * len(RECEPTION_FLAGS))


class TestICDHandlingBilling(FrappeTestCase):
	"""ICD Handling is ordered, invoiced and checked at the Gate Pass like Shore Handling"""

	def tearDown(self):
		frappe.db.rollback()

	def charged_container(self, **values):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value("Container", mbl, {"cargo_type": "Local", "has_icd_handling_charge": 1, **values})
		return mbl

	def get_order_services(self, container_id, settings_doc=None, **order_values):
		order_values = {"container_status": "FCL", "container_size": "22G1", "port": "TEAGTL", **order_values}
		service_order = make_service_order(container_id=container_id, **order_values)
		with with_settings(settings_doc or services_settings()):
			service_order.add_container_services(frappe.get_cached_doc("ICD TZ Settings"))
		return service_order.services

	def test_an_fcl_order_charges_one_icd_handling_with_its_criteria(self):
		services = self.get_order_services(self.charged_container())

		self.assertEqual([(row.service, row.qty) for row in services], [("_T ICD Handling", 1)])
		self.assertIn("Size: <b>22G1</b>", services[0].remarks)

	def test_an_lcl_order_charges_icd_handling_per_cbm(self):
		loose_settings = services_settings(loose_rows=[criteria("ICD Handling", "_T Loose ICD Handling")])

		services = self.get_order_services(
			self.charged_container(), loose_settings, container_status="LCL", gross_volume=5
		)

		self.assertEqual([(row.service, row.qty) for row in services], [("_T Loose ICD Handling", 5)])

	def test_an_invoiced_icd_handling_is_not_ordered_again(self):
		self.assertEqual(self.get_order_services(self.charged_container(ih_sales_invoice="_T-IH")), [])

	def test_missing_criteria_stops_the_order(self):
		settings_doc = frappe._dict(settings(), gatepass_cancellation_item=None)

		with self.assertRaises(frappe.ValidationError) as error:
			self.get_order_services(self.charged_container(), settings_doc)

		self.assertIn("ICD Handling", str(error.exception))

	def test_the_invoice_is_kept_on_the_container_and_a_return_clears_it(self):
		mbl = self.charged_container()

		submit_invoice("_T ICD Handling", mbl)
		self.assertEqual(get_container(mbl).ih_sales_invoice, "_T-SINV-1")

		submit_invoice("_T ICD Handling", mbl, is_return=1, name="_T-RET-1", return_against="_T-SINV-1")
		self.assertIsNone(get_container(mbl).ih_sales_invoice)

	def test_an_unpaid_icd_handling_stops_the_gate_pass_even_for_transit(self):
		mbl = self.charged_container()
		for cargo_type in ("Local", "Transit"):
			frappe.db.set_value("Container", mbl, "cargo_type", cargo_type)

			msg, _ = make_gate_pass(frappe.get_doc("Container", mbl)).validate_reception_charges()

			self.assertIn("ICD Handling Charges", msg, cargo_type)

	def test_a_paid_icd_handling_returns_its_invoice(self):
		mbl = self.charged_container(ih_sales_invoice="_T-IH")

		msg, invoices = make_gate_pass(frappe.get_doc("Container", mbl)).validate_reception_charges()

		self.assertEqual(msg, "")
		self.assertIn("_T-IH", invoices)
