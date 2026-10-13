# Copyright (c) 2026, elius mgani and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.doctype.edi_partner.edi_partner import (
	DEFAULT_FILE_NAME_FORMAT,
	get_default_file_name_format,
	get_partner,
)
from icd_tz.tests.utils import get_test_company, set_test_icd_setting

test_ignore = ["Company", "Cost Center"]


class TestEDIPartner(FrappeTestCase):
	def setUp(self):
		self.company = get_test_company()
		self.abbr = frappe.get_cached_value("Company", self.company, "abbr")
		set_test_icd_setting({"enable_edi": 1, "default_sender_id": "TZDARDSEL"})
		self.partner = make_partner("TCM", enable_edi=1)

	def tearDown(self):
		frappe.db.rollback()

	def test_code_is_uppercased_and_the_record_is_named_by_code_and_abbreviation(self):
		partner = make_partner(" tlo ")

		self.assertEqual(partner.shipping_line_code, "TLO")
		self.assertEqual(partner.abbr, self.abbr)
		self.assertEqual(partner.name, f"TLO-{self.abbr}")

	def test_duplicate_code_in_one_company_is_rejected(self):
		with self.assertRaises(frappe.DuplicateEntryError):
			make_partner("TCM")

	def test_the_same_line_can_have_a_partner_in_another_company(self):
		other_company = frappe.db.get_value("Company", {"name": ("!=", self.company)}, "name")
		if not other_company:
			self.skipTest("this test needs a second company")
		partner = make_partner("TCM", company=other_company)

		self.assertEqual(partner.name, f"TCM-{frappe.get_cached_value('Company', other_company, 'abbr')}")

	def test_sender_falls_back_to_the_default_of_the_company(self):
		self.assertEqual(self.partner.sender, "TZDARDSEL")

		self.partner.sender_id = "OWNCODE"
		self.assertEqual(self.partner.sender, "OWNCODE")

	def test_partner_is_found_for_its_code_and_company(self):
		self.assertEqual(get_partner("TCM", self.company).name, self.partner.name)

	def test_lookup_ignores_case_and_padding(self):
		self.assertEqual(get_partner("  tcm ", self.company).name, self.partner.name)

	def test_no_partner_when_code_or_company_is_missing(self):
		self.assertIsNone(get_partner(None, self.company))
		self.assertIsNone(get_partner("", self.company))
		self.assertIsNone(get_partner("TCM", None))

	def test_no_partner_when_the_line_is_not_configured(self):
		self.assertIsNone(get_partner("NOSUCH", self.company))

	def test_no_partner_of_another_company(self):
		other_company = frappe.db.get_value("Company", {"name": ("!=", self.company)}, "name")
		if not other_company:
			self.skipTest("this test needs a second company")

		self.assertIsNone(get_partner("TCM", other_company))

	def test_no_partner_when_the_line_is_disabled(self):
		self.partner.db_set("enable_edi", 0)

		self.assertIsNone(get_partner("TCM", self.company))

	def test_no_partner_when_edi_is_off_for_the_company(self):
		set_test_icd_setting({"enable_edi": 0})

		self.assertIsNone(get_partner("TCM", self.company))

	def test_new_partner_gets_the_default_file_name_format(self):
		self.assertEqual(self.partner.file_name_format, DEFAULT_FILE_NAME_FORMAT)
		self.assertEqual(self.partner.file_extension, "edi")

	def test_the_form_offers_the_default_file_name_format(self):
		# the form fills it in when EDI is ticked, and asks for it only then
		field = frappe.get_meta("EDI Partner").get_field("file_name_format")

		self.assertEqual(get_default_file_name_format(), DEFAULT_FILE_NAME_FORMAT)
		self.assertFalse(field.reqd)
		self.assertEqual(field.mandatory_depends_on, "eval:doc.enable_edi==1")

	def test_a_cleared_file_name_format_falls_back_to_the_default(self):
		self.partner.file_name_format = "  "
		self.partner.save()

		self.assertEqual(self.partner.file_name_format, DEFAULT_FILE_NAME_FORMAT)

	def test_own_file_name_format_is_kept(self):
		partner = make_partner("TOW", file_name_format="<receiver ID>_<message type>_<control #>")

		self.assertEqual(partner.file_name_format, "<receiver ID>_<message type>_<control #>")

	def test_default_file_name_ends_with_the_message_number(self):
		self.assertEqual(
			self.partner.get_file_name("CODECO", "26091815435311", "0001", {}),
			"TZDARDSEL_TCM_CODECO_0001.edi",
		)

	def test_file_name_fills_every_placeholder(self):
		self.partner.file_name_format = "<sender ID>_<receiver ID>_<message type>_<control #>_<message #>"

		self.assertEqual(
			self.partner.get_file_name("CODECO", "26091815435311", "0001", {}),
			"TZDARDSEL_TCM_CODECO_26091815435311_0001.edi",
		)

	def test_file_name_uses_the_partner_extension(self):
		self.partner.file_extension = "txt"

		self.assertTrue(self.partner.get_file_name("CODECO", "1", "1", {}).endswith(".txt"))

	def test_file_name_takes_the_message_template_values(self):
		self.partner.file_name_format = "<container_no>_<vessel_name>_<reference>"
		values = {"container_no": "APHU7175408", "vessel_name": "YOKOHAMA STAR", "reference": "0001"}

		self.assertEqual(
			self.partner.get_file_name("CODECO", "1", "1", values), "APHU7175408_YOKOHAMA_STAR_0001.edi"
		)

	def test_released_characters_are_unwrapped_in_the_file_name(self):
		self.partner.file_name_format = "<transporter>_<message #>"

		self.assertEqual(
			self.partner.get_file_name("CODECO", "1", "7", {"transporter": "A?+B CO."}), "A_B_CO._7.edi"
		)

	def test_message_template_placeholder_is_accepted(self):
		self.partner.file_name_format = "<sender ID>_<container_no>_<reference>"
		self.partner.save()

		self.assertEqual(self.partner.file_name_format, "<sender ID>_<container_no>_<reference>")

	def test_rejected_placeholders_are_shown_escaped(self):
		self.partner.file_name_format = "<sender ID>_<vessel>_<control #>"

		with self.assertRaises(frappe.ValidationError) as context:
			self.partner.save()

		self.assertIn("<code>&lt;vessel&gt;</code>", str(context.exception))
		self.assertIn("<code>&lt;container_no&gt;</code>", str(context.exception))

	def test_unsafe_text_around_the_placeholders_is_rejected(self):
		for file_name_format in ("../<message #>", "EDI <message #>", "EDI/<message #>"):
			self.partner.file_name_format = file_name_format

			with self.assertRaises(frappe.ValidationError, msg=file_name_format):
				self.partner.save()

	def test_format_without_a_unique_reference_is_rejected(self):
		self.partner.file_name_format = "<sender ID>_<receiver ID>_<message type>"

		with self.assertRaises(frappe.ValidationError):
			self.partner.save()


def make_partner(shipping_line_code, **values):
	partner = frappe.get_doc(
		{
			"doctype": "EDI Partner",
			"shipping_line_code": shipping_line_code,
			"shipping_line_name": f"{shipping_line_code} LIMITED",
			"company": get_test_company(),
			"connection_type": "SMTP",
			"receiver_email": "edi@example.com",
			**values,
		}
	)
	partner.insert(ignore_permissions=True)

	return partner
