# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.sales_order import get_charged_item
from icd_tz.icd_tz.api.utils import get_service_item, get_service_key


def criteria(service_type, service_name, **fields):
	return frappe._dict(service_type=service_type, service_name=service_name, **fields)


def settings(service_types=(), loose_types=()):
	return frappe._dict(service_types=list(service_types), loose_types=list(loose_types))


class TestServiceCriteria(FrappeTestCase):
	"""Pricing a service on whatever criteria its row carries"""

	def test_a_row_is_matched_on_the_criteria_it_fills_in(self):
		# Levy is priced by size alone today, so it applies to every cargo type and port
		settings_doc = settings([criteria("Levy", "Levy 20", size="20ft")])
		key = get_service_key(size="22G1", cargo_type="Transit", port="DP WORLD")

		self.assertEqual(get_service_item(settings_doc, "Levy", key), "Levy 20")

	def test_adding_a_criterion_narrows_the_row_without_a_code_change(self):
		# the same Levy row, once someone gives it a cargo type in ICD TZ Settings
		settings_doc = settings([criteria("Levy", "Levy 20 Local", size="20ft", cargo_type="Local")])

		local = get_service_key(size="22G1", cargo_type="Local", port="TEAGTL")
		transit = get_service_key(size="22G1", cargo_type="Transit", port="TEAGTL")

		self.assertEqual(get_service_item(settings_doc, "Levy", local), "Levy 20 Local")
		self.assertIsNone(get_service_item(settings_doc, "Levy", transit))

	def test_the_most_specific_matching_row_wins(self):
		settings_doc = settings(
			[
				criteria("Levy", "Levy any", size="20ft"),
				criteria("Levy", "Levy transit", size="20ft", cargo_type="Transit"),
				criteria(
					"Levy", "Levy transit at DP World", size="20ft", cargo_type="Transit", port="DP WORLD"
				),
			]
		)

		self.assertEqual(
			get_service_item(settings_doc, "Levy", get_service_key("22G1", "Transit", "DP WORLD")),
			"Levy transit at DP World",
		)
		self.assertEqual(
			get_service_item(settings_doc, "Levy", get_service_key("22G1", "Transit", "TEAGTL")),
			"Levy transit",
		)
		self.assertEqual(
			get_service_item(settings_doc, "Levy", get_service_key("22G1", "Local", "TEAGTL")),
			"Levy any",
		)

	def test_a_row_with_no_criteria_prices_every_container(self):
		settings_doc = settings([criteria("Removal", "Removal flat")])

		self.assertEqual(
			get_service_item(settings_doc, "Removal", get_service_key("45G1", "Local", "TEAGTL")),
			"Removal flat",
		)

	def test_a_service_only_takes_a_row_of_its_own_type(self):
		settings_doc = settings([criteria("Levy", "Levy 20", size="20ft")])

		self.assertIsNone(
			get_service_item(settings_doc, "Removal", get_service_key("22G1", "Local", "TEAGTL"))
		)

	def test_loose_cargo_is_priced_on_its_own_table(self):
		settings_doc = settings(
			service_types=[criteria("Shore", "Shore 20 Local", size="20ft", cargo_type="Local")],
			loose_types=[criteria("Shore", "LCL Shore Local", cargo_type="Local")],
		)
		key = get_service_key(size="22G1", cargo_type="Local", port="TEAGTL")

		self.assertEqual(get_service_item(settings_doc, "Shore", key, is_loose_cargo=True), "LCL Shore Local")
		self.assertEqual(get_service_item(settings_doc, "Shore", key), "Shore 20 Local")

	def test_a_container_with_no_readable_size_takes_a_row_that_ignores_size(self):
		settings_doc = settings(
			[
				criteria("Transport", "Transport Local", cargo_type="Local"),
				criteria("Transport", "Transport 20", size="20ft"),
			]
		)

		self.assertEqual(
			get_service_item(settings_doc, "Transport", get_service_key(cargo_type="Local")),
			"Transport Local",
		)


class TestChargedItem(FrappeTestCase):
	"""What a Container is charged, through the caller the sales order uses"""

	def test_a_container_with_no_matching_row_is_reported(self):
		settings_doc = settings([criteria("Removal", "Removal 20", size="20ft")])
		container = frappe._dict(size="45G1", cargo_type="Local", port_of_destination="TEAGTL")

		self.assertRaises(frappe.ValidationError, get_charged_item, container, settings_doc, "Removal")

	def test_loose_cargo_is_charged_from_the_loose_table(self):
		settings_doc = settings(
			service_types=[criteria("Removal", "Removal 40", size="40ft")],
			loose_types=[criteria("Removal", "LCL Removal")],
		)
		container = frappe._dict(
			size="45G1", cargo_type="Local", port_of_destination="TEAGTL", freight_indicator="LCL"
		)

		self.assertEqual(get_charged_item(container, settings_doc, "Removal"), "LCL Removal")
