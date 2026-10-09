# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.sales_invoice import update_sales_references
from icd_tz.icd_tz.doctype.gate_pass.test_gate_pass import make_container, make_gate_pass
from icd_tz.tests.test_lcl_gross_volume import make_service_order
from icd_tz.tests.test_service_criteria import criteria, settings

test_ignore = ["Company", "Cost Center"]

RECEPTION = "_T-INCOME-REC"

GET_CACHED_DOC = frappe.get_cached_doc


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
		criteria("ICD Handling", "_T ICD Handling"),
		criteria("Stripping", "_T Stripping"),
		criteria("Verification", "_T Verification"),
	]
	return frappe._dict(settings(service_rows), gatepass_cancellation_item=None)


def with_settings(settings_doc):
	"""Serve the test ICD TZ Settings, every other cached doc stays real"""

	def get_cached_doc(doctype, *args, **kwargs):
		if doctype == "ICD TZ Settings":
			return settings_doc
		return GET_CACHED_DOC(doctype, *args, **kwargs)

	return patch("frappe.get_cached_doc", side_effect=get_cached_doc)


def submit_invoice(
	item_code, container_id, is_return=0, name="_T-SINV-1", return_against=None, settings_doc=None, **item
):
	invoice = SimpleNamespace(
		name=name,
		m_bl_no="MBL-1",
		h_bl_no=None,
		is_return=is_return,
		return_against=return_against,
		items=[frappe._dict(item_code=item_code, container_id=container_id, sales_order=None, **item)],
	)
	with with_settings(settings_doc or income_settings()):
		update_sales_references(invoice)


def get_container(name):
	return frappe.db.get_value("Container", name, "*", as_dict=True)


def book(container_id, count=1):
	"""Submitted bookings for the container_no and bill of lading of a container"""

	container = frappe.db.get_value(
		"Container", container_id, ["container_no", "m_bl_no", "h_bl_no"], as_dict=True
	)
	for _ in range(count):
		insert("In Yard Container Booking", docstatus=1, container_id=container_id, **container)


def bill(invoice, container_id, item_code, qty=1):
	"""A submitted invoice that billed an item of a container"""

	insert("Sales Invoice", name=invoice, docstatus=1)
	insert(
		"Sales Invoice Item",
		parent=invoice,
		parenttype="Sales Invoice",
		parentfield="items",
		docstatus=1,
		item_code=item_code,
		qty=qty,
		container_id=container_id,
	)


class TestSalesInvoiceRefs(FrappeTestCase):
	"""A submitted Sales Invoice stamps its income service on the Container"""

	def tearDown(self):
		frappe.db.rollback()

	def test_transport_invoice_stays_on_its_own_container(self):
		mbl, hbl = make_reception_containers()

		submit_invoice("_T Transport", mbl)

		self.assertEqual(get_container(mbl).t_sales_invoice, "_T-SINV-1")
		self.assertIsNone(get_container(hbl).t_sales_invoice)
		self.assertIsNone(frappe.db.get_value("Container Reception", RECEPTION, "t_sales_invoice"))

	def test_shore_handling_invoice_stays_on_its_own_container(self):
		mbl, hbl = make_reception_containers()

		submit_invoice("_T Shore", hbl)

		self.assertIsNone(get_container(mbl).sh_sales_invoice)
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

		submit_invoice("_T Stripping", mbl, is_return=1, name="_T-RET-1", return_against="_T-SINV-1")

		self.assertIsNone(get_container(mbl).st_sales_invoice)

	def test_invoices_of_repeated_bookings_are_all_kept(self):
		mbl, _ = make_reception_containers()

		submit_invoice("_T Stripping", mbl)
		submit_invoice("_T Stripping", mbl)
		submit_invoice("_T Stripping", mbl, name="_T-SINV-2")

		self.assertEqual(get_container(mbl).st_sales_invoice, "_T-SINV-1,_T-SINV-2")

	def test_a_return_drops_only_the_invoice_it_reverses(self):
		mbl, _ = make_reception_containers()
		submit_invoice("_T Verification", mbl)
		submit_invoice("_T Verification", mbl, name="_T-SINV-2")

		submit_invoice("_T Verification", mbl, is_return=1, name="_T-RET-1", return_against="_T-SINV-1")

		self.assertEqual(get_container(mbl).cv_sales_invoice, "_T-SINV-2")


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

	def test_transit_container_skips_transport(self):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value("Container", mbl, {"has_transport_charges": 1, "cargo_type": "Transit"})

		msg, _ = make_gate_pass(frappe.get_doc("Container", mbl)).validate_reception_charges()

		self.assertNotIn("Transport Charges", msg)

	def test_the_container_cargo_type_decides_the_transit_exemption(self):
		mbl, _ = make_reception_containers(cargo_type="Transit")
		frappe.db.set_value("Container", mbl, {"has_transport_charges": 1, "cargo_type": "Local"})

		msg, _ = make_gate_pass(frappe.get_doc("Container", mbl)).validate_reception_charges()

		self.assertIn("Transport Charges", msg)

	def test_a_sibling_invoice_does_not_pay_for_the_container(self):
		mbl, hbl = make_reception_containers(cargo_type="Local")
		for name in (mbl, hbl):
			frappe.db.set_value("Container", name, {"cargo_type": "Local", "has_transport_charges": 1})
		frappe.db.set_value("Container", mbl, "t_sales_invoice", "_T-SINV-T")

		msg, _ = make_gate_pass(frappe.get_doc("Container", hbl)).validate_reception_charges()

		self.assertIn("Transport Charges", msg)

	def test_a_container_without_reception_is_still_checked(self):
		container = make_container(cargo_type="Local", has_shore_handling_charges=1)

		msg, _ = make_gate_pass(container).validate_reception_charges()

		self.assertIn("Shore Handling Charges", msg)

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
		self.assertEqual(invoices, ["_T-CV"])

	def test_every_booking_invoice_is_checked_for_payment(self):
		mbl, _ = make_reception_containers()
		frappe.db.set_value(
			"Container",
			mbl,
			{
				"has_stripping_charges": 1,
				"st_sales_invoice": "_T-ST-1,_T-ST-2",
				"has_custom_verification_charges": 0,
			},
		)
		insert("In Yard Container Booking", container_id=mbl, docstatus=1)

		_, invoices = make_gate_pass(frappe.get_doc("Container", mbl)).validate_in_yard_booking()

		self.assertEqual(invoices, ["_T-ST-1", "_T-ST-2"])

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
		book(mbl)
		bill("_T-CV", mbl, "_T Verification")
		service_order = make_service_order(
			container_id=mbl, container_status="FCL", container_size="22G1", port="TEAGTL"
		)

		service_order.add_container_services(income_settings())

		self.assertEqual([row.service for row in service_order.services], ["_T Transport", "_T Stripping"])

	def test_nothing_is_added_without_charges(self):
		mbl, _ = make_reception_containers(cargo_type="Local")
		service_order = make_service_order(
			container_id=mbl, container_status="FCL", container_size="22G1", port="TEAGTL"
		)

		service_order.add_container_services(income_settings())

		self.assertEqual(service_order.services, [])

	def get_booking_services(self, container_id, **values):
		service_order = make_service_order(
			container_id=container_id, container_status="FCL", container_size="22G1", port="TEAGTL", **values
		)
		service_order.add_container_services(income_settings())
		return [(row.service, row.qty) for row in service_order.services]

	def charged_container(self, **values):
		mbl, hbl = make_reception_containers(cargo_type="Local")
		frappe.db.set_value(
			"Container",
			mbl,
			{"m_bl_no": "MBL-1", "has_stripping_charges": 1, "has_custom_verification_charges": 1, **values},
		)
		return mbl, hbl

	def test_every_booking_is_stripped_and_verified(self):
		mbl, _ = self.charged_container()
		book(mbl, count=2)

		services = self.get_booking_services(mbl)

		self.assertEqual(services, [("_T Stripping", 2), ("_T Verification", 2)])

	def test_only_the_unbilled_bookings_are_charged(self):
		mbl, _ = self.charged_container(st_sales_invoice="_T-ST", cv_sales_invoice="_T-CV")
		book(mbl, count=3)
		bill("_T-ST", mbl, "_T Stripping", qty=2)
		bill("_T-CV", mbl, "_T Verification", qty=3)

		services = self.get_booking_services(mbl)

		self.assertEqual(services, [("_T Stripping", 1)])

	def test_a_cancelled_invoice_is_charged_again(self):
		mbl, _ = self.charged_container(st_sales_invoice="_T-ST")
		book(mbl)
		bill("_T-ST", mbl, "_T Stripping")
		frappe.db.set_value("Sales Invoice Item", {"parent": "_T-ST"}, "docstatus", 2)

		services = self.get_booking_services(mbl)

		self.assertEqual(services, [("_T Stripping", 1), ("_T Verification", 1)])

	def test_house_bl_bookings_do_not_count_for_the_master_bl_container(self):
		mbl, hbl = self.charged_container()
		frappe.db.set_value("Container", hbl, {"m_bl_no": "MBL-1", "h_bl_no": "HBL-1"})
		book(mbl)
		book(hbl, count=2)

		services = self.get_booking_services(mbl)

		self.assertEqual(services, [("_T Stripping", 1), ("_T Verification", 1)])
