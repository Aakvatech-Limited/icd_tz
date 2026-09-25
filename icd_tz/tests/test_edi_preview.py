# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.edi.codeco import preview
from icd_tz.icd_tz.api.edi.movement import ContainerMovement
from icd_tz.tests.test_edi_codeco import GATE_IN_DEFAULTS, make_partner

test_ignore = ["Company", "Cost Center"]


class TestEDIPreview(FrappeTestCase):
	"""The EDI Partner form previews a movement with that partner"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "enable_edi", 1)
		self.partner = make_partner()
		self.partner.db_set({"enable_edi": 0, "file_extension": "txt"})
		self.movement = ContainerMovement(**GATE_IN_DEFAULTS)

	def tearDown(self):
		frappe.db.rollback()

	def test_a_named_partner_is_previewed_while_its_edi_is_off(self):
		message = preview(self.movement, "original", edi_partner=self.partner.name)

		self.assertTrue(message["edi_content"].startswith("UNB+"))

	def test_the_file_takes_the_partner_name_format_and_extension(self):
		message = preview(self.movement, "original", edi_partner=self.partner.name)

		self.assertTrue(message["filename"].endswith(".txt"))
		self.assertIn("CODECO", message["filename"])

	def test_without_a_named_partner_only_an_enabled_one_is_used(self):
		self.assertIsNone(preview(self.movement, "original"))

	def test_a_unit_owing_no_message_previews_nothing(self):
		self.assertIsNone(preview(None, "original", edi_partner=self.partner.name))
