# Copyright (c) 2025, Administrator and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestEDISettings(FrappeTestCase):
	def test_edi_settings_single_is_loadable(self):
		settings = frappe.get_single("EDI Settings")
		self.assertEqual(settings.doctype, "EDI Settings")

	def test_connection_type_options_are_supported(self):
		options = frappe.get_meta("EDI Settings").get_field("connection_type").options
		self.assertTrue(options)
