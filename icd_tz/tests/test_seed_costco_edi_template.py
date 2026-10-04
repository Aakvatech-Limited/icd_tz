# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.edi.templates import get_default_template
from icd_tz.patches.seed_costco_edi_template import execute
from icd_tz.tests.test_edi_codeco import make_partner

test_ignore = ["Company", "Cost Center"]


class TestSeedCOSTCOTemplate(FrappeTestCase):
	"""A partner made before COSTCO existed gets its template on migrate"""

	def setUp(self):
		self.partner = make_partner()
		frappe.db.delete("EDI Partner Template", {"parent": self.partner.name, "edi_type": "COSTCO"})

	def tearDown(self):
		frappe.db.rollback()

	def test_an_existing_partner_gets_the_shipped_costco_template(self):
		execute()

		partner = frappe.get_doc("EDI Partner", self.partner.name)
		self.assertEqual(partner.get_template_row("COSTCO").template, get_default_template("COSTCO"))

	def test_its_own_codeco_template_is_left_alone(self):
		frappe.db.set_value(
			"EDI Partner Template", {"parent": self.partner.name, "edi_type": "CODECO"}, "template", "TUNED"
		)

		execute()
		execute()

		partner = frappe.get_doc("EDI Partner", self.partner.name)
		self.assertEqual(partner.get_template_row("CODECO").template, "TUNED")
		self.assertEqual(len(partner.templates), 2)
