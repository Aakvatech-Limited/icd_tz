# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.utils import get_container_service_item, get_service_items

SETTINGS = frappe._dict(
	service_types=[
		frappe._dict(service_type="Storage-Single", size="20ft", service_name="Storage Single 20"),
		frappe._dict(service_type="Storage-Single", size="40ft", service_name="Storage Single 40"),
		frappe._dict(service_type="Storage-Double", size="20ft", service_name="Storage Double 20"),
		frappe._dict(service_type="Removal", size="40ft", service_name="Removal 40"),
	]
)


class TestContainerServiceItem(FrappeTestCase):
	"""Picking the criteria row that prices a container"""

	def setUp(self):
		self.service_items = get_service_items(SETTINGS)

	def test_a_container_takes_the_row_for_its_service_type_and_size(self):
		self.assertEqual(
			get_container_service_item(self.service_items, "Storage-Single", "22G1"),
			"Storage Single 20",
		)
		self.assertEqual(
			get_container_service_item(self.service_items, "Storage-Single", "45G1"),
			"Storage Single 40",
		)
		self.assertEqual(
			get_container_service_item(self.service_items, "Storage-Double", "22G1"),
			"Storage Double 20",
		)

	def test_a_size_with_no_criteria_row_matches_nothing(self):
		self.assertIsNone(get_container_service_item(self.service_items, "Removal", "22G1"))
		self.assertIsNone(get_container_service_item(self.service_items, "Storage-Double", "45G1"))

	def test_a_container_with_no_readable_size_matches_nothing(self):
		for size in ("", None, "TWENTY"):
			self.assertIsNone(get_container_service_item(self.service_items, "Storage-Single", size))

	def test_the_first_row_for_a_size_wins_over_a_later_duplicate(self):
		settings = frappe._dict(
			service_types=[
				frappe._dict(service_type="Removal", size="20ft", service_name="Removal 20"),
				frappe._dict(service_type="Removal", size="20ft", service_name="Removal 20 again"),
			]
		)

		self.assertEqual(
			get_container_service_item(get_service_items(settings), "Removal", "22G1"), "Removal 20"
		)
