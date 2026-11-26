# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.sales_order import get_gatepass_cancellation_service
from icd_tz.icd_tz.doctype.gate_pass.test_gate_pass import make_gate_pass
from icd_tz.tests.test_container_income_refs import (
	bill,
	get_container,
	insert,
	make_reception_containers,
	with_settings,
)
from icd_tz.tests.test_icd_services import services_settings, submit_invoice

test_ignore = ["Company", "Cost Center"]

CANCELLATION_ITEM = "_T Cancellation"


class TestGatePassCancellationCharge(FrappeTestCase):
	"""Each cancelled Gate Pass of a container is charged once"""

	def tearDown(self):
		frappe.db.rollback()

	def cancelled_container(self, cancellations: int, **values):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value("Container", mbl, {"has_cancellation_charge": 1, **values})
		for _ in range(cancellations):
			insert("Gate Pass", container_id=mbl, docstatus=2)

		return mbl

	def get_cancellation_qty(self, container_id):
		row = get_gatepass_cancellation_service(
			frappe.get_doc("Container", container_id), services_settings(), {"container_id": container_id}
		)
		return row.get("qty", 0)

	def test_each_cancelled_gate_pass_is_charged(self):
		self.assertEqual(self.get_cancellation_qty(self.cancelled_container(2)), 2)

	def test_a_submitted_gate_pass_is_not_charged(self):
		container_id = self.cancelled_container(1)
		insert("Gate Pass", container_id=container_id, docstatus=1)

		self.assertEqual(self.get_cancellation_qty(container_id), 1)

	def test_a_second_cancellation_is_charged_after_the_first_is_invoiced(self):
		container_id = self.cancelled_container(2, g_sales_invoice="_T-G-1")
		bill("_T-G-1", container_id, CANCELLATION_ITEM)

		self.assertEqual(self.get_cancellation_qty(container_id), 1)

	def test_nothing_is_charged_once_every_cancellation_is_invoiced(self):
		container_id = self.cancelled_container(2, g_sales_invoice="_T-G-1")
		bill("_T-G-1", container_id, CANCELLATION_ITEM, qty=2)

		self.assertEqual(self.get_cancellation_qty(container_id), 0)

	def test_every_cancellation_invoice_is_kept(self):
		container_id = self.cancelled_container(2)

		submit_invoice(CANCELLATION_ITEM, container_id, name="_T-G-1")
		submit_invoice(CANCELLATION_ITEM, container_id, name="_T-G-2")

		self.assertEqual(get_container(container_id).g_sales_invoice, "_T-G-1,_T-G-2")


class TestGatePassCancellationCheck(FrappeTestCase):
	"""A Gate Pass waits for every cancellation charge to be invoiced"""

	def tearDown(self):
		frappe.db.rollback()

	def pending_message(self, cancellations: int, billed_qty: int = 0) -> str:
		container_id = TestGatePassCancellationCharge.cancelled_container(self, cancellations)
		if billed_qty:
			frappe.db.set_value("Container", container_id, "g_sales_invoice", "_T-G-1")
			bill("_T-G-1", container_id, CANCELLATION_ITEM, qty=billed_qty)

		gate_pass = make_gate_pass(frappe.get_doc("Container", container_id))
		with with_settings(services_settings()):
			msg, _ = gate_pass.validate_container_charges()
		return msg

	def test_an_uninvoiced_cancellation_holds_the_gate_pass(self):
		self.assertIn("Gate Pass Cancellation Charges", self.pending_message(1))

	def test_a_second_cancellation_is_owed_after_the_first_is_invoiced(self):
		self.assertIn("Gate Pass Cancellation Charges", self.pending_message(2, billed_qty=1))

	def test_every_cancellation_invoiced_lets_the_gate_pass_through(self):
		self.assertNotIn("Gate Pass Cancellation Charges", self.pending_message(2, billed_qty=2))
