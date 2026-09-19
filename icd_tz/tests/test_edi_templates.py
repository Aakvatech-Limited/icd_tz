# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.edi.codeco import CODECOGenerator
from icd_tz.icd_tz.api.edi.movement import ContainerMovement
from icd_tz.icd_tz.api.edi.templates import (
	CODECO_VARIABLES,
	get_default_template,
	get_shipped_template,
	validate_template,
)
from icd_tz.tests.test_edi_codeco import GATE_IN_DEFAULTS, make_partner

test_ignore = ["Company", "Cost Center"]

MINIMAL_TEMPLATE = (
	"UNH+{{ reference }}+CODECO:D:95B:UN:ITG14'\n"
	"BGM+{{ message_code }}+{{ reference }}+{{ message_function }}'\n"
	"NAD+CF+{{ shipping_line_code }}'\n"
	"EQD+CN+{{ container_no }}'\n"
	"CNT+16:1'\n"
)


class TestEDIPartnerTemplates(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "enable_edi", 1)
		frappe.db.set_single_value("ICD TZ Settings", "icd_un_locode", "TZDAR")
		frappe.db.set_single_value("ICD TZ Settings", "default_sender_id", "TZDARDSEL")
		self.partner = make_partner()

	def tearDown(self):
		frappe.db.rollback()

	# --- seeding ----------------------------------------------------------

	def test_a_new_partner_starts_with_the_shipped_codeco_template(self):
		self.assertEqual([row.edi_type for row in self.partner.templates], ["CODECO"])
		self.assertEqual(self.partner.templates[0].template, get_default_template("CODECO"))

	def test_a_tuned_template_survives_a_re_save(self):
		self.partner.templates[0].template = MINIMAL_TEMPLATE
		self.partner.save()
		self.partner.reload()

		self.assertEqual(self.partner.templates[0].template, MINIMAL_TEMPLATE)

	def test_a_partner_created_with_its_own_template_is_not_overwritten(self):
		frappe.db.delete("EDI Partner", {"shipping_line_code": "MSK"})
		partner = frappe.get_doc(
			{
				"doctype": "EDI Partner",
				"shipping_line_code": "MSK",
				"enable_edi": 1,
				"templates": [{"edi_type": "CODECO", "template": MINIMAL_TEMPLATE}],
			}
		).insert(ignore_permissions=True)

		self.assertEqual(len(partner.templates), 1)
		self.assertEqual(partner.templates[0].template, MINIMAL_TEMPLATE)

	def test_the_reset_button_reads_the_template_shipped_with_the_app(self):
		self.assertEqual(get_shipped_template("CODECO"), get_default_template("CODECO"))

	def test_an_unknown_edi_type_cannot_reach_the_file_system(self):
		self.assertRaises(frappe.ValidationError, get_default_template, "../../hooks")

	# --- validation on save -----------------------------------------------

	def test_a_template_that_reaches_for_the_document_is_refused(self):
		self.assertRefused(MINIMAL_TEMPLATE.replace("{{ container_no }}", "{{ doc.container_no }}"), "doc")

	def test_a_template_cannot_reach_the_frappe_namespace_the_sandbox_injects(self):
		# frappe.render_template hands every template a restricted `frappe`, which
		# would read any table. Only the listed values are allowed through.
		self.assertRefused(
			MINIMAL_TEMPLATE.replace("{{ container_no }}", "{{ frappe.db.get_value('User', 'x', 'y') }}"),
			"frappe",
		)

	def test_a_template_that_names_an_unavailable_value_is_refused(self):
		self.assertRefused(
			MINIMAL_TEMPLATE.replace("{{ container_no }}", "{{ container_no }}+{{ container_number }}"),
			"container_number",
		)

	def test_a_template_that_drops_a_mandatory_segment_is_refused(self):
		self.assertRefused(MINIMAL_TEMPLATE.replace("NAD+CF+{{ shipping_line_code }}'\n", ""), "NAD")

	def test_a_template_that_drops_a_mandatory_value_is_refused(self):
		self.assertRefused(MINIMAL_TEMPLATE.replace("{{ container_no }}", "TBA"), "container_no")

	def test_a_template_that_writes_the_envelope_is_refused(self):
		self.assertRefused(MINIMAL_TEMPLATE + "UNZ+1+{{ reference }}'\n", "UNZ")

	def test_an_empty_template_is_refused_before_it_reaches_the_parser(self):
		self.assertRefused("", "is empty")

	def test_an_edi_type_the_icd_does_not_send_yet_says_so(self):
		self.partner.templates[0].edi_type = "COREOR"

		with self.assertRaises(frappe.ValidationError) as caught:
			self.partner.save()

		self.assertIn("does not send COREOR messages yet", str(caught.exception))

	def test_an_envelope_segment_spelled_by_jinja_is_still_caught(self):
		self.assertRefused(MINIMAL_TEMPLATE + "UN{{ 'Z' }}+1+{{ reference }}'\n", "UNZ")

	def test_a_flag_prints_a_transmittable_value_and_never_a_python_boolean(self):
		generator = CODECOGenerator(ContainerMovement(**GATE_IN_DEFAULTS), self.partner)
		context = generator.get_context("9")

		self.assertEqual(context["is_gate_in"], "1")
		self.assertEqual(context["is_empty"], "")

	def test_a_segment_the_template_spreads_over_lines_arrives_as_one(self):
		self.partner.templates[0].template = MINIMAL_TEMPLATE.replace(
			"EQD+CN+{{ container_no }}'",
			"EQD+CN\n\t+{{ container_no }}'",
		)
		self.partner.save()

		self.assertIn("EQD+CN+UACU6042588'", self.build().split("\n"))

	def test_the_shipped_template_passes_the_rules_it_sets(self):
		# nothing else validates the file, so a bad edit to it would only show at the gate
		validate_template("CODECO", get_default_template("CODECO"))

	def test_a_template_that_drops_a_mandatory_segment_only_when_a_value_is_missing_is_refused(self):
		self.assertRefused(
			MINIMAL_TEMPLATE.replace(
				"EQD+CN+{{ container_no }}'",
				"{% if m_bl_no %}EQD+CN+{{ container_no }}'{% endif %}",
			),
			"drops these mandatory segments when a value is missing: EQD",
		)

	def test_a_template_that_cannot_render_is_refused(self):
		self.assertRefused(
			MINIMAL_TEMPLATE.replace(
				"{{ container_no }}", "{{ container_no | length | float | round(2, 'bad') }}"
			),
			"could not be rendered",
		)

	def test_a_template_that_does_not_compile_is_refused(self):
		self.assertRefused(MINIMAL_TEMPLATE + "{% if seal_no %}SEL+{{ seal_no }}+CA'\n", "syntax")

	def test_two_templates_of_one_edi_type_are_refused(self):
		self.partner.append("templates", {"edi_type": "CODECO", "template": MINIMAL_TEMPLATE})

		with self.assertRaises(frappe.ValidationError) as caught:
			self.partner.save()

		self.assertIn("already a CODECO template", str(caught.exception))

	# --- rendering --------------------------------------------------------

	def test_the_template_owns_the_body_and_the_envelope_still_agrees(self):
		self.partner.templates[0].template = MINIMAL_TEMPLATE
		self.partner.save()
		lines = self.build().split("\n")
		reference = lines[0].split("+")[-1].rstrip("'")

		self.assertEqual(
			lines[1:6],
			[
				f"UNH+{reference}+CODECO:D:95B:UN:ITG14'",
				f"BGM+34+{reference}+9'",
				"NAD+CF+CMA'",
				"EQD+CN+UACU6042588'",
				"CNT+16:1'",
			],
		)
		# UNH through UNT inclusive, which the template no longer counts for itself
		self.assertEqual(lines[-2], f"UNT+6+{reference}'")

	def test_one_partner_can_diverge_without_touching_another(self):
		self.partner.templates[0].template = MINIMAL_TEMPLATE
		self.partner.save()

		self.assertFalse([line for line in self.build().split("\n") if line.startswith("SEL+")])
		self.assertIn("SEL+TW1234567+CA'", self.build(make_partner()).split("\n"))

	def test_a_partner_without_a_template_row_falls_back_to_the_shipped_one(self):
		self.partner.templates = []
		self.partner.save()

		self.assertIn("SEL+TW1234567+CA'", self.build().split("\n"))

	def test_a_service_character_in_a_value_cannot_break_a_templated_segment(self):
		self.partner.templates[0].template = MINIMAL_TEMPLATE
		self.partner.save()
		lines = self.build(seal_no="A'B").split("\n")

		# the seal is not in this partner's template at all, so nothing carries it
		self.assertEqual(len(lines), 8, lines)

	def test_the_help_on_the_form_lists_every_value_the_template_may_use(self):
		# the help is the only place a user configuring a partner reads the vocabulary
		help_text = frappe.get_meta("EDI Partner Template").get_field("template_help").options

		for name in CODECO_VARIABLES:
			self.assertIn(f"{{{{ {name} }}}}", help_text, name)

	def test_every_documented_value_is_handed_to_the_template(self):
		generator = CODECOGenerator(ContainerMovement(**GATE_IN_DEFAULTS), self.partner)

		self.assertEqual(sorted(generator.get_context("9")), sorted(CODECO_VARIABLES))

	# --- helpers ----------------------------------------------------------

	def assertRefused(self, template: str, expected: str):
		self.partner.templates[0].template = template

		with self.assertRaises(frappe.ValidationError) as caught:
			self.partner.save()

		self.assertIn(expected, str(caught.exception))

	def build(self, partner=None, **overrides) -> str:
		movement = ContainerMovement(**{**GATE_IN_DEFAULTS, **overrides})

		return CODECOGenerator(movement, partner or self.partner).generate()
