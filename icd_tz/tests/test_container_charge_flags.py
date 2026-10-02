# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.sales_order import get_storage_services
from icd_tz.icd_tz.doctype.gate_pass.test_gate_pass import make_container
from icd_tz.tests.test_container_income_refs import RECEPTION, get_container, make_reception_containers
from icd_tz.tests.test_lcl_gross_volume import make_service_order
from icd_tz.tests.test_service_criteria import criteria, settings

test_ignore = ["Company", "Cost Center"]


def levy_settings(*countries):
	return frappe._dict(countries=[frappe._dict(country=country) for country in countries])


def new_container(**values):
	return frappe.get_doc({"doctype": "Container", "days_to_be_billed": 0, **values})


class TestCreationAndInspectionFlags(FrappeTestCase):
	"""Reception charges are set on creation, booking charges on booking submit"""

	def tearDown(self):
		frappe.db.rollback()

	def test_a_received_container_has_transport_and_shore_handling_charges(self):
		make_reception_containers()
		container = new_container(
			container_no="RECU1234567",
			container_reception=RECEPTION,
			container_dates=[{"date": frappe.utils.nowdate()}],
		)

		container.run_method("before_insert")

		self.assertEqual(container.has_transport_charges, 1)
		self.assertEqual(container.has_shore_handling_charges, 1)

	def test_a_submitted_booking_charges_stripping_and_verification(self):
		mbl, _ = make_reception_containers()
		booking = frappe.get_doc({"doctype": "In Yard Container Booking", "container_id": mbl})

		booking.on_submit()

		container = get_container(mbl)
		self.assertEqual(container.has_stripping_charges, 1)
		self.assertEqual(container.has_custom_verification_charges, 1)

	def test_a_submitted_inspection_leaves_the_booking_charges(self):
		mbl, _ = make_reception_containers()
		inspection = frappe.get_doc({"doctype": "Container Inspection", "container_id": mbl})

		inspection.update_container_doc()

		container = get_container(mbl)
		self.assertEqual(container.has_stripping_charges, 0)
		self.assertEqual(container.has_custom_verification_charges, 0)


class TestRemovalAndLevyFlags(FrappeTestCase):
	"""An invoiced removal or levy stays charged, so the flag never hides the invoice"""

	def test_removal_follows_storage_charges(self):
		with_storage = new_container(has_single_charge=1)
		without_storage = new_container()

		with_storage.check_removal_charges_elibility()
		without_storage.check_removal_charges_elibility()

		self.assertEqual(with_storage.has_removal_charges, 1)
		self.assertEqual(without_storage.has_removal_charges, 0)

	def test_invoiced_removal_stays_charged(self):
		container = new_container(has_single_charge=1, r_sales_invoice="_T-SINV-R")

		container.check_removal_charges_elibility()

		self.assertEqual(container.has_removal_charges, 1)

	def test_levy_follows_the_destination_country(self):
		levy_country = new_container(country_of_destination="Zambia")
		other_country = new_container(country_of_destination="Kenya")
		no_country = new_container()

		with patch("frappe.get_cached_doc", return_value=levy_settings("Zambia")):
			for container in (levy_country, other_country, no_country):
				container.check_corridor_levy_eligibility()

		self.assertEqual(levy_country.has_corridor_levy_charges, 1)
		self.assertEqual(other_country.has_corridor_levy_charges, 0)
		self.assertEqual(no_country.has_corridor_levy_charges, 0)

	def test_invoiced_levy_stays_charged(self):
		container = new_container(country_of_destination="Zambia", c_sales_invoice="_T-SINV-C")

		with patch("frappe.get_cached_doc", return_value=levy_settings("Zambia")):
			container.check_corridor_levy_eligibility()

		self.assertEqual(container.has_corridor_levy_charges, 1)

	def test_an_empty_container_owes_no_removal_or_levy(self):
		container = new_container(is_empty_container=1, has_single_charge=1, country_of_destination="Zambia")

		with patch("frappe.get_cached_doc", return_value=levy_settings("Zambia")):
			container.check_corridor_levy_eligibility()
		container.check_removal_charges_elibility()

		self.assertEqual(container.has_removal_charges, 0)
		self.assertEqual(container.has_corridor_levy_charges, 0)

	def test_an_empty_container_keeps_an_invoiced_removal_and_levy(self):
		container = new_container(
			is_empty_container=1,
			country_of_destination="Zambia",
			r_sales_invoice="_T-SINV-R",
			c_sales_invoice="_T-SINV-C",
		)

		with patch("frappe.get_cached_doc", return_value=levy_settings("Zambia")):
			container.check_corridor_levy_eligibility()
		container.check_removal_charges_elibility()

		self.assertEqual(container.has_removal_charges, 1)
		self.assertEqual(container.has_corridor_levy_charges, 1)


class TestRemovalAndLevyBilling(FrappeTestCase):
	"""Orders bill a pending removal or levy once, whatever the storage days owe"""

	def tearDown(self):
		frappe.db.rollback()

	def get_removal_rows(self, **container_values):
		make_container(m_bl_no="_T-RM-MBL", has_single_charge=1, has_removal_charges=1, **container_values)
		removal_settings = frappe._dict(
			settings([criteria("Removal", "_T Removal")]), gatepass_cancellation_item=None
		)

		with patch("frappe.get_cached_doc", return_value=removal_settings):
			return [row["item_code"] for row in get_storage_services(m_bl_no="_T-RM-MBL")]

	def test_removal_is_billed_after_the_storage_days_are_invoiced(self):
		self.assertEqual(self.get_removal_rows(days_to_be_billed=0), ["_T Removal"])

	def test_invoiced_removal_is_not_billed_again(self):
		self.assertEqual(self.get_removal_rows(days_to_be_billed=0, r_sales_invoice="_T-SINV-R"), [])

	def get_levy_services(self, **container_values):
		mbl, _ = make_reception_containers(cargo_type="Local")
		frappe.db.set_value("Container", mbl, {"has_corridor_levy_charges": 1, **container_values})
		service_order = make_service_order(
			container_id=mbl, container_status="FCL", container_size="22G1", port="TEAGTL"
		)

		service_order.add_container_services(settings([criteria("Levy", "_T Levy")]))
		return [row.service for row in service_order.services]

	def test_pending_levy_is_added_to_the_service_order(self):
		self.assertEqual(self.get_levy_services(), ["_T Levy"])

	def test_invoiced_levy_is_not_added_again(self):
		self.assertEqual(self.get_levy_services(c_sales_invoice="_T-SINV-C"), [])
