# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.sales_invoice import update_sales_references
from icd_tz.icd_tz.doctype.gate_pass.test_gate_pass import make_container, make_gate_pass
from icd_tz.patches.move_income_refs_to_container import move_booking_refs, move_reception_refs
from icd_tz.tests.test_lcl_gross_volume import make_service_order
from icd_tz.tests.test_service_criteria import criteria, settings

test_ignore = ["Company", "Cost Center"]

RECEPTION = "_T-INCOME-REC"


def insert(doctype, **values):
	doc = frappe.get_doc({"doctype": doctype, **values})
	doc.flags.ignore_mandatory = True
	if not doc.name:
		doc.set_new_name()
	doc.db_insert()
	return doc


def make_reception_containers(**reception_values):
	"""An MBL container and its HBL container, both created from one reception"""

	insert("Container Reception", name=RECEPTION, docstatus=1, **reception_values)
	mbl = make_container(container_reception=RECEPTION)
	hbl = make_container(container_reception=RECEPTION, has_hbl=1)
	return mbl.name, hbl.name


def income_settings():
	service_rows = [
		criteria("Transport", "_T Transport"),
		criteria("Shore", "_T Shore"),
		criteria("Stripping", "_T Stripping"),
		criteria("Verification", "_T Verification"),
	]
	return frappe._dict(settings(service_rows), gatepass_cancellation_item=None)


def submit_invoice(item_code, container_id, is_return=0):
	invoice = SimpleNamespace(
		name="_T-SINV-1",
		m_bl_no="MBL-1",
		h_bl_no=None,
		is_return=is_return,
		items=[frappe._dict(item_code=item_code, container_id=container_id, sales_order=None)],
	)
	with patch("frappe.get_cached_doc", return_value=income_settings()):
		update_sales_references(invoice)


def get_container(name):
	return frappe.db.get_value("Container", name, "*", as_dict=True)


class TestSalesInvoiceRefs(FrappeTestCase):
	"""A submitted Sales Invoice stamps its income service on the Container"""

	def tearDown(self):
		frappe.db.rollback()

	def test_transport_invoice_reaches_every_container_of_the_reception(self):
		mbl, hbl = make_reception_containers()

		submit_invoice("_T Transport", mbl)

		self.assertEqual(get_container(mbl).t_sales_invoice, "_T-SINV-1")
		self.assertEqual(get_container(hbl).t_sales_invoice, "_T-SINV-1")
		self.assertIsNone(frappe.db.get_value("Container Reception", RECEPTION, "t_sales_invoice"))

	def test_shore_handling_invoice_reaches_every_container_of_the_reception(self):
		mbl, hbl = make_reception_containers()

		submit_invoice("_T Shore", hbl)

		self.assertEqual(get_container(mbl).sh_sales_invoice, "_T-SINV-1")
		self.assertEqual(get_container(hbl).sh_sales_invoice, "_T-SINV-1")

	def test_booking_invoices_stay_on_their_own_container(self):
		mbl, hbl = make_reception_containers()

		submit_invoice("_T Stripping", mbl)
		submit_invoice("_T Verification", mbl)

		self.assertEqual(get_container(mbl).st_sales_invoice, "_T-SINV-1")
		self.assertEqual(get_container(mbl).cv_sales_invoice, "_T-SINV-1")
		self.assertIsNone(get_container(hbl).st_sales_invoice)
		self.assertIsNone(get_container(hbl).cv_sales_invoice)

	def test_a_return_invoice_clears_the_reference(self):
		mbl, _ = make_reception_containers()
		submit_invoice("_T Stripping", mbl)

		submit_invoice("_T Stripping", mbl, is_return=1)

		self.assertIsNone(get_container(mbl).st_sales_invoice)


class TestGatePassIncomeCharges(FrappeTestCase):
	"""Gate Pass reads the income service payments from the Container"""

	def tearDown(self):
		frappe.db.rollback()

	def test_unpaid_transport_and_shore_handling_are_pending(self):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value("Container", mbl, {"has_transport_charges": 1, "has_shore_handling_charges": 1})

		msg, _ = make_gate_pass(frappe.get_doc("Container", mbl)).validate_reception_charges()

		self.assertIn("Transport Charges", msg)
		self.assertIn("Shore Handling Charges", msg)

	def test_paid_charges_return_their_invoices(self):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value(
			"Container",
			mbl,
			{
				"has_transport_charges": 1,
				"t_sales_invoice": "_T-SINV-T",
				"has_shore_handling_charges": 1,
				"sh_sales_invoice": "_T-SINV-S",
			},
		)

		msg, invoices = make_gate_pass(frappe.get_doc("Container", mbl)).validate_reception_charges()

		self.assertEqual(msg, "")
		self.assertEqual(invoices, ["_T-SINV-T", "_T-SINV-S"])

	def test_transit_reception_skips_transport(self):
		mbl, _ = make_reception_containers(cargo_type="Transit")
		frappe.db.set_value("Container", mbl, {"has_transport_charges": 1, "cargo_type": "Local"})

		msg, _ = make_gate_pass(frappe.get_doc("Container", mbl)).validate_reception_charges()

		self.assertNotIn("Transport Charges", msg)

	def test_unpaid_stripping_and_verification_are_pending(self):
		mbl, _ = make_reception_containers()
		frappe.db.set_value(
			"Container",
			mbl,
			{"has_stripping_charges": 1, "has_custom_verification_charges": 1, "cv_sales_invoice": "_T-CV"},
		)
		insert("In Yard Container Booking", container_id=mbl, docstatus=1)

		msg, invoices = make_gate_pass(frappe.get_doc("Container", mbl)).validate_in_yard_booking()

		self.assertIn("Stripping Charges", msg)
		self.assertNotIn("Custom Verification Charges", msg)
		self.assertEqual(invoices, [None, "_T-CV"])

	def test_a_missing_booking_still_stops_the_gate_pass(self):
		mbl, _ = make_reception_containers()
		frappe.db.set_value("Container", mbl, "cargo_type", "Local")
		gate_pass = make_gate_pass(frappe.get_doc("Container", mbl), action_for_missing_booking="Stop")

		with self.assertRaises(frappe.ValidationError) as error:
			gate_pass.validate_in_yard_booking()

		self.assertIn("No Booking found", str(error.exception))


class TestServiceOrderIncomeServices(FrappeTestCase):
	"""Service Order bills the income services the Container still owes"""

	def tearDown(self):
		frappe.db.rollback()

	def test_unpaid_services_are_added_and_paid_ones_skipped(self):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value(
			"Container",
			mbl,
			{
				"cargo_type": "Local",
				"has_transport_charges": 1,
				"has_shore_handling_charges": 1,
				"sh_sales_invoice": "_T-SH",
				"has_stripping_charges": 1,
				"has_custom_verification_charges": 1,
				"cv_sales_invoice": "_T-CV",
			},
		)
		service_order = make_service_order(
			container_id=mbl, container_status="FCL", container_size="22G1", port="TEAGTL"
		)

		service_order.get_reception_services(income_settings())
		service_order.get_booking_services(income_settings())

		self.assertEqual([row.service for row in service_order.services], ["_T Transport", "_T Stripping"])

	def test_nothing_is_added_without_charges(self):
		mbl, _ = make_reception_containers(cargo_type="Local")
		service_order = make_service_order(
			container_id=mbl, container_status="FCL", container_size="22G1", port="TEAGTL"
		)

		service_order.get_reception_services(income_settings())
		service_order.get_booking_services(income_settings())

		self.assertEqual(service_order.services, [])


class TestMoveIncomeRefsPatch(FrappeTestCase):
	"""The patch copies the reception and booking values to Container"""

	def tearDown(self):
		frappe.db.rollback()

	def test_reception_values_reach_every_container_of_the_reception(self):
		mbl, hbl = make_reception_containers(
			has_transport_charges="Yes",
			t_sales_invoice="_T-T",
			has_shore_handling_charges="No",
			s_sales_invoice="_T-S",
		)

		move_reception_refs()

		for name in (mbl, hbl):
			container = get_container(name)
			self.assertEqual(container.has_transport_charges, 1)
			self.assertEqual(container.t_sales_invoice, "_T-T")
			self.assertEqual(container.has_shore_handling_charges, 0)
			self.assertEqual(container.sh_sales_invoice, "_T-S")

	def test_active_bookings_are_merged_and_cancelled_ones_ignored(self):
		mbl, hbl = make_reception_containers()
		insert("In Yard Container Booking", container_id=mbl, docstatus=1, has_stripping_charges="Yes")
		insert(
			"In Yard Container Booking",
			container_id=mbl,
			docstatus=1,
			has_stripping_charges="No",
			s_sales_invoice="_T-ST",
			has_custom_verification_charges="No",
		)
		insert(
			"In Yard Container Booking",
			container_id=hbl,
			docstatus=2,
			has_stripping_charges="Yes",
			has_custom_verification_charges="Yes",
			cv_sales_invoice="_T-CV",
		)

		move_booking_refs()

		mbl_container, hbl_container = get_container(mbl), get_container(hbl)
		self.assertEqual(mbl_container.has_stripping_charges, 1)
		self.assertEqual(mbl_container.st_sales_invoice, "_T-ST")
		self.assertEqual(mbl_container.has_custom_verification_charges, 0)
		self.assertEqual(hbl_container.has_stripping_charges, 0)
		self.assertIsNone(hbl_container.cv_sales_invoice)
