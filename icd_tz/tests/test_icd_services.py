# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.doctype.gate_pass.test_gate_pass import make_container, make_gate_pass
from icd_tz.tests.test_container_income_refs import (
	RECEPTION,
	book,
	get_container,
	income_settings,
	insert,
	make_reception_containers,
	with_settings,
)
from icd_tz.tests.test_container_income_refs import submit_invoice as submit_invoice_with
from icd_tz.tests.test_lcl_gross_volume import make_service_order
from icd_tz.tests.test_service_criteria import criteria, settings

test_ignore = ["Company", "Cost Center"]


def services_settings(*extra_rows, loose_rows=()):
	"""Income settings with every Container service and the fields a Container save reads"""

	settings_doc = income_settings()
	settings_doc.service_types += [
		criteria("Removal", "_T Removal"),
		criteria("Levy", "_T Levy"),
		criteria("Storage-Single", "_T Storage"),
		*extra_rows,
	]
	settings_doc.loose_types += list(loose_rows)
	settings_doc.update(gatepass_cancellation_item="_T Cancellation", countries=[], storage_days=[])
	return settings_doc


def submit_invoice(item_code, container_id, settings_doc=None, **values):
	submit_invoice_with(item_code, container_id, settings_doc=settings_doc or services_settings(), **values)


class TestContainerInvoiceRefs(FrappeTestCase):
	"""Removal, levy and cancellation invoices stay on their own Container"""

	def tearDown(self):
		frappe.db.rollback()

	def test_each_container_service_sets_its_invoice_and_status(self):
		make_reception_containers()
		for item_code, field in (
			("_T Removal", "r_sales_invoice"),
			("_T Levy", "c_sales_invoice"),
			("_T Cancellation", "g_sales_invoice"),
		):
			container = make_container(container_reception=RECEPTION, status="At Payments").name

			submit_invoice(item_code, container)

			self.assertEqual(get_container(container)[field], "_T-SINV-1")
			self.assertEqual(get_container(container).status, "At Gatepass")

	def test_a_return_clears_the_container_invoice(self):
		container, _ = make_reception_containers()
		submit_invoice("_T Removal", container)

		submit_invoice("_T Removal", container, is_return=1, name="_T-RET-1", return_against="_T-SINV-1")

		self.assertIsNone(get_container(container).r_sales_invoice)

	def test_loose_cargo_items_are_recognised(self):
		container, _ = make_reception_containers()
		settings_doc = services_settings(loose_rows=[criteria("Levy", "_T Loose Levy")])

		submit_invoice("_T Loose Levy", container, settings_doc)

		self.assertEqual(get_container(container).c_sales_invoice, "_T-SINV-1")

	def test_an_item_set_on_two_services_goes_to_the_first(self):
		mbl, _ = make_reception_containers()
		settings_doc = services_settings(criteria("Removal", "_T Transport"))

		submit_invoice("_T Transport", mbl, settings_doc)

		self.assertEqual(get_container(mbl).t_sales_invoice, "_T-SINV-1")
		self.assertIsNone(get_container(mbl).r_sales_invoice)

	def test_storage_invoice_lands_on_its_days(self):
		container, _ = make_reception_containers()
		day = frappe.get_doc("Container", container).append("container_dates", {"date": "2026-01-01"})
		day.db_insert()

		submit_invoice("_T Storage", container, container_child_refs=day.name)

		self.assertEqual(
			frappe.db.get_value("Container Service Detail", day.name, "sales_invoice"), "_T-SINV-1"
		)

	def test_any_other_item_lands_on_the_inspection(self):
		container = make_container()
		inspection = insert("Container Inspection", container_id=container.name, docstatus=1)
		row = insert(
			"Container Inspection Detail",
			parent=inspection.name,
			parenttype="Container Inspection",
			parentfield="services",
			service="_T Status Check",
		)

		submit_invoice("_T Status Check", container.name)

		self.assertEqual(
			frappe.db.get_value("Container Inspection Detail", row.name, "sales_invoice"), "_T-SINV-1"
		)


class TestGatePassServiceCharges(FrappeTestCase):
	"""Gate Pass lists every unpaid service in one fixed order"""

	def tearDown(self):
		frappe.db.rollback()

	def test_unpaid_services_are_listed_in_order(self):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value(
			"Container",
			mbl,
			{
				"cargo_type": "Local",
				"has_removal_charges": 1,
				"has_corridor_levy_charges": 1,
				"has_cancellation_charge": 1,
				"has_stripping_charges": 1,
				"has_custom_verification_charges": 1,
				"has_transport_charges": 1,
				"has_shore_handling_charges": 1,
				"has_icd_handling_charge": 1,
			},
		)
		book(mbl)
		gate_pass = make_gate_pass(frappe.get_doc("Container", mbl))

		with self.assertRaises(frappe.ValidationError) as error:
			gate_pass.validate_pending_payments()

		message = str(error.exception)
		labels = [
			"Removal Charges",
			"Corridor Levy Charges",
			"Gate Pass Cancellation Charges",
			"Stripping Charges",
			"Custom Verification Charges",
			"Transport Charges",
			"Shore Handling Charges",
			"ICD Handling Charges",
		]
		self.assertEqual(sorted(labels, key=message.index), labels)

	def test_paid_container_services_return_their_invoices(self):
		container = make_container(
			has_removal_charges=1,
			r_sales_invoice="_T-R",
			has_corridor_levy_charges=1,
			c_sales_invoice="_T-C",
		)

		msg, invoices = make_gate_pass(container).validate_container_charges()

		self.assertEqual(msg, "")
		self.assertEqual([name for name in invoices if name], ["_T-R", "_T-C"])

	def test_cancelling_the_gate_pass_flags_the_charge(self):
		container = make_container()

		make_gate_pass(container).flag_gatepass_cancellation_charge()

		self.assertEqual(get_container(container.name).has_cancellation_charge, 1)


class TestServiceOrderServiceLines(FrappeTestCase):
	"""Service Order adds the flagged services that are not invoiced yet"""

	def tearDown(self):
		frappe.db.rollback()

	def charged_container(self, **values):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value("Container", mbl, {"cargo_type": "Local", **values})
		return mbl

	def get_services(self, container_id, settings_doc=None, **order_values):
		order_values = {"container_status": "FCL", "container_size": "22G1", "port": "TEAGTL", **order_values}
		service_order = make_service_order(container_id=container_id, gross_volume=5, **order_values)
		with with_settings(settings_doc or services_settings()):
			service_order.get_services()
		return [(row.service, row.qty) for row in service_order.services]

	def test_every_unpaid_service_is_added_in_order(self):
		mbl = self.charged_container(
			has_transport_charges=1,
			has_shore_handling_charges=1,
			has_icd_handling_charge=1,
			has_stripping_charges=1,
			has_custom_verification_charges=1,
			has_corridor_levy_charges=1,
			has_removal_charges=1,
			has_cancellation_charge=1,
		)
		book(mbl)

		services = [service for service, _ in self.get_services(mbl)]

		self.assertEqual(
			services,
			["_T Transport", "_T Shore", "_T ICD Handling", "_T Stripping", "_T Verification", "_T Levy"],
		)

	def test_invoiced_services_are_not_charged_again_on_loose_cargo(self):
		mbl = self.charged_container(
			has_transport_charges=1,
			t_sales_invoice="_T-T",
			has_shore_handling_charges=1,
			sh_sales_invoice="_T-SH",
			has_corridor_levy_charges=1,
			c_sales_invoice="_T-C",
		)
		loose_settings = services_settings(
			loose_rows=[criteria("Transport", "_T Loose Transport"), criteria("Levy", "_T Loose Levy")]
		)

		services = self.get_services(mbl, loose_settings, container_status="LCL")

		self.assertEqual(services, [])

	def test_each_house_bl_record_pays_its_own_reception_services(self):
		mbl, hbl = make_reception_containers(cargo_type="Local")
		for name in (mbl, hbl):
			frappe.db.set_value("Container", name, {"cargo_type": "Local", "has_transport_charges": 1})
		frappe.db.set_value("Container", mbl, "t_sales_invoice", "_T-T")

		self.assertEqual(self.get_services(mbl), [])
		self.assertEqual(self.get_services(hbl), [("_T Transport", 1)])

	def test_a_container_without_reception_is_charged_reception_services(self):
		container = make_container(cargo_type="Local", has_transport_charges=1)

		self.assertEqual(self.get_services(container.name), [("_T Transport", 1)])

	def test_shore_handling_line_carries_its_criteria(self):
		mbl = self.charged_container(has_shore_handling_charges=1)
		service_order = make_service_order(
			container_id=mbl, container_status="FCL", container_size="22G1", port="TEAGTL"
		)

		with with_settings(services_settings()):
			service_order.get_services()

		self.assertIn("Size: <b>22G1</b>", service_order.services[0].remarks)

	def test_reception_services_are_priced_on_the_container_cargo_type(self):
		mbl, _ = make_reception_containers(cargo_type="Transit")
		frappe.db.set_value(
			"Container",
			mbl,
			{"cargo_type": "Local", "has_transport_charges": 1, "has_shore_handling_charges": 1},
		)
		settings_doc = services_settings()
		settings_doc.service_types = [
			criteria("Transport", "_T Transit Transport", cargo_type="Transit"),
			criteria("Transport", "_T Local Transport", cargo_type="Local"),
			criteria("Shore", "_T Shore"),
		]
		service_order = make_service_order(
			container_id=mbl, container_status="FCL", container_size="22G1", port="TEAGTL"
		)

		with with_settings(settings_doc):
			service_order.get_services()

		self.assertEqual([row.service for row in service_order.services], ["_T Local Transport", "_T Shore"])
		self.assertIn("Cargo Type: <b>Local</b>", service_order.services[1].remarks)

	def test_missing_criteria_stops_an_uninvoiced_service(self):
		mbl = self.charged_container(has_corridor_levy_charges=1)
		settings_doc = frappe._dict(settings(), gatepass_cancellation_item=None)

		with self.assertRaises(frappe.ValidationError) as error:
			self.get_services(mbl, settings_doc)

		self.assertIn("Corridor Levy", str(error.exception))

	def test_an_invoiced_service_needs_no_criteria(self):
		mbl = self.charged_container(has_transport_charges=1, t_sales_invoice="_T-T")

		self.assertEqual(self.get_services(mbl, container_status="LCL"), [])


class TestServiceFlags(FrappeTestCase):
	"""Documents that create a charge set its flag on the Container"""

	def tearDown(self):
		frappe.db.rollback()

	def test_a_submitted_booking_owes_booking_services(self):
		container = make_container()
		booking = frappe.get_doc({"doctype": "In Yard Container Booking", "container_id": container.name})

		with patch(
			"icd_tz.icd_tz.doctype.in_yard_container_booking.in_yard_container_booking.set_container_cf_company"
		):
			booking.on_submit()

		self.assertEqual(get_container(container.name).has_stripping_charges, 1)
		self.assertEqual(get_container(container.name).has_custom_verification_charges, 1)
