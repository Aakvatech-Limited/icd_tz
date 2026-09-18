# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import re
from datetime import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.edi.codeco import CODECOGenerator
from icd_tz.icd_tz.api.edi.movement import ContainerMovement

test_ignore = ["Company", "Cost Center"]

GATE_IN_DEFAULTS = {
	"document": "CR-2026-00001",
	"is_gate_in": True,
	"shipping_line_code": "CMA",
	"container_no": "UACU6042588",
	"iso_size_type": "45G1",
	"is_empty": False,
	"m_bl_no": "HLCUTYO250101920",
	"weight": 25129,
	"weight_unit": "KG",
	"seal_no": "TW1234567",
	"event_datetime": datetime(2026, 3, 3, 22, 55),
	"transporter": "GTK Limited",
	"truck": "T676 EFG",
	"voyage_no": "0403",
	"vessel_name": "Kota Nabil",
	"call_sign": "9V2131",
}


class TestCODECO(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "enable_edi", 1)
		frappe.db.set_single_value("ICD TZ Settings", "icd_un_locode", "TZDAR")
		frappe.db.set_single_value("ICD TZ Settings", "default_sender_id", "TZDARDSEL")
		self.partner = make_partner()

	def tearDown(self):
		frappe.db.rollback()

	# --- envelope ---------------------------------------------------------

	def test_syntax_version_is_two(self):
		self.assertTrue(self.build().startswith("UNB+UNOA:2+TZDARDSEL+CMA+"))

	def test_interchange_reference_is_shared_by_unb_unh_unt_and_unz(self):
		lines = self.lines()
		reference = lines[0].split("+")[-1].rstrip("'")

		self.assertEqual(lines[1].split("+")[1], reference)
		self.assertTrue(lines[-2].endswith(f"+{reference}'"))
		self.assertEqual(lines[-1], f"UNZ+1+{reference}'")

	def test_segment_count_matches_the_body(self):
		lines = self.lines()
		counted = int(lines[-2].split("+")[1])

		# UNH through UNT inclusive, which is everything but UNB and UNZ
		self.assertEqual(counted, len(lines) - 2)

	# --- message body -----------------------------------------------------

	def test_bgm_carries_the_numeric_interchange_reference(self):
		# The numeric reference is the interchange reference, taken from UNB
		lines = self.lines()
		reference = lines[0].split("+")[-1].rstrip("'")

		self.assertIn(f"BGM+34+{reference}+9'", lines)
		self.assertTrue(reference.isdigit(), reference)

	def test_gate_out_uses_its_own_message_code(self):
		lines = self.lines(is_gate_in=False)
		reference = lines[0].split("+")[-1].rstrip("'")

		self.assertIn(f"BGM+36+{reference}+9'", lines)

	def test_main_carriage_carries_voyage_carrier_call_sign_and_vessel(self):
		self.assertIn("TDT+20+0403+1++CMA:172+++9V2131:103::KOTA NABIL'", self.lines())

	def test_container_operator_is_the_shipping_line(self):
		# no code list is claimed, the code comes from TANeSW and not from BIC or a carrier list
		self.assertIn("NAD+CF+CMA'", self.lines())

	def test_iso_size_type_is_passed_through_from_the_manifest(self):
		self.assertIn("EQD+CN+UACU6042588+45G1:102:5++3+5'", self.lines())

	def test_reefer_iso_type_is_not_flattened_to_a_dry_box(self):
		self.assertIn("EQD+CN+UACU6042588+45R1:102:5++3+5'", self.lines(iso_size_type="45R1"))

	def test_empty_box_is_reported_empty(self):
		self.assertIn("EQD+CN+UACU6042588+45G1:102:5++3+4'", self.lines(is_empty=True))

	def test_empty_box_leaving_the_yard_is_an_export_movement(self):
		self.assertIn("EQD+CN+UACU6042588+45G1:102:5++2+4'", self.lines(is_gate_in=False, is_empty=True))

	def test_bill_of_lading_uses_the_bm_qualifier(self):
		self.assertIn("RFF+BM:HLCUTYO250101920'", self.lines())

	def test_no_reference_segment_when_there_is_no_bill_of_lading(self):
		self.assertFalse([line for line in self.lines(m_bl_no="") if line.startswith("RFF+")])

	def test_event_datetime(self):
		self.assertIn("DTM+7:202603032255:203'", self.lines())

	def test_activity_location_is_this_icd(self):
		self.assertIn("LOC+165+TZDAR:139:6+TZDARDSEL:TER:ZZZ'", self.lines())

	def test_the_gate_location_carries_the_code_this_line_knows_us_by(self):
		# our own code means nothing to a line that addresses us by another one
		self.partner.db_set("sender_id", "TZDAR51")
		lines = self.lines()

		self.assertTrue(lines[0].startswith("UNB+UNOA:2+TZDAR51+CMA+"))
		self.assertIn("LOC+165+TZDAR:139:6+TZDAR51:TER:ZZZ'", lines)

	def test_the_gate_location_falls_back_to_our_own_code(self):
		self.assertFalse(self.partner.sender_id)

		self.assertIn("LOC+165+TZDAR:139:6+TZDARDSEL:TER:ZZZ'", self.lines())

	def test_gross_weight_is_reported(self):
		self.assertIn("MEA+AAE+G+KGM:25129'", self.lines())

	def test_weight_in_an_unknown_unit_is_left_out(self):
		self.assertFalse([line for line in self.lines(weight_unit="LBS") if line.startswith("MEA+")])

	def test_seal_number_is_reported(self):
		self.assertIn("SEL+TW1234567+CA'", self.lines())

	def test_no_seal_segment_when_the_box_has_no_seal(self):
		self.assertFalse([line for line in self.lines(seal_no="") if line.startswith("SEL+")])

	def test_inland_leg_carries_the_haulier_and_the_truck(self):
		self.assertIn("TDT+1++3++GT:172::GTK LIMITED+++T676 EFG'", self.lines())

	def test_control_total(self):
		self.assertIn("CNT+16:1'", self.lines())

	def test_interchange_references_do_not_repeat_inside_one_second(self):
		references = {self.lines()[0].split("+")[-1].rstrip("'") for _ in range(5)}

		self.assertEqual(len(references), 5)

	def test_the_interchange_reference_is_fourteen_characters(self):
		self.assertEqual(len(self.lines()[0].split("+")[-1].rstrip("'")), 14)

	# --- safety -----------------------------------------------------------

	def test_a_service_character_in_a_name_cannot_break_the_segment(self):
		line = next(line for line in self.lines(transporter="A+B:CO") if line.startswith("TDT+1"))
		elements = split_elements(line)

		# the separators inside the name are released, so they stay in one element
		self.assertIn("A?+B?:CO", elements[5])
		self.assertEqual(len(elements), 9)

	def test_the_haulier_code_is_taken_before_the_name_is_released(self):
		line = next(line for line in self.lines(transporter="A+B:CO") if line.startswith("TDT+1"))

		self.assertEqual(split_elements(line)[5].split(":")[0], "A?+")

	def test_every_segment_ends_with_the_terminator(self):
		for line in self.lines():
			self.assertTrue(line.endswith("'"), line)

	def test_message_holds_no_lowercase_characters(self):
		message = self.build()

		self.assertEqual(message, message.upper())

	# --- helpers ----------------------------------------------------------

	def build(self, **overrides) -> str:
		movement = ContainerMovement(**{**GATE_IN_DEFAULTS, **overrides})

		return CODECOGenerator(movement, self.partner).generate()

	def lines(self, **overrides) -> list[str]:
		return self.build(**overrides).split("\n")


def split_elements(segment_text: str) -> list[str]:
	"""Split on the separators that are not released"""

	return re.split(r"(?<!\?)\+", segment_text)


def make_partner():
	# the site may already carry this shipping line, the rollback puts it back
	frappe.db.delete("EDI Partner", {"shipping_line_code": "CMA"})

	partner = frappe.get_doc(
		{
			"doctype": "EDI Partner",
			"shipping_line_code": "CMA",
			"shipping_line_name": "CMA CGM TANZANIA LIMITED",
			"enable_edi": 1,
			"connection_type": "SMTP",
			"receiver_email": "edi@example.com",
		}
	)
	partner.insert(ignore_permissions=True)

	return partner
