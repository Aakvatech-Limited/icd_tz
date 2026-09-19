# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from datetime import datetime

from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.edi.syntax import (
	edifact_datetime,
	normalise_segment,
	segment,
	split_segments,
	text,
	whole_number,
)


class TestEDISyntax(FrappeTestCase):
	def test_lowercase_is_raised_to_the_level_a_repertoire(self):
		self.assertEqual(text("GTK Limited"), "GTK LIMITED")

	def test_characters_outside_level_a_are_dropped(self):
		self.assertEqual(text("KO@TA#NABIL_1"), "KOTANABIL1")

	def test_service_characters_are_released_so_they_cannot_break_the_segment(self):
		self.assertEqual(text("A&B+CO:LTD'X"), "A&B?+CO?:LTD?'X")

	def test_the_release_character_itself_is_released(self):
		self.assertEqual(text("WHY?"), "WHY??")

	def test_value_is_cut_to_the_element_length(self):
		self.assertEqual(text("ABCDEFGHIJ", 4), "ABCD")

	def test_empty_input_gives_an_empty_value(self):
		self.assertEqual(text(None), "")
		self.assertEqual(text(""), "")

	def test_segment_joins_elements_and_components(self):
		self.assertEqual(segment("EQD", "CN", "MSKU1", ["45G1", "102", "5"]), "EQD+CN+MSKU1+45G1:102:5'")

	def test_trailing_empty_elements_are_dropped_but_inner_ones_are_kept(self):
		self.assertEqual(segment("TDT", "20", "", "1", "", ""), "TDT+20++1'")

	def test_trailing_empty_components_are_dropped(self):
		self.assertEqual(segment("LOC", "165", ["TZDAR", "139", ""]), "LOC+165+TZDAR:139'")

	def test_datetime_formats(self):
		moment = datetime(2026, 3, 3, 22, 55, 8)

		self.assertEqual(edifact_datetime(moment, "102"), "20260303")
		self.assertEqual(edifact_datetime(moment, "203"), "202603032255")
		self.assertEqual(edifact_datetime(moment, "204"), "20260303225508")

	def test_datetime_accepts_a_string(self):
		self.assertEqual(edifact_datetime("2026-03-03 22:55:08", "203"), "202603032255")

	def test_missing_datetime_gives_an_empty_value(self):
		self.assertEqual(edifact_datetime(None), "")

	def test_weight_is_rounded_to_a_whole_number(self):
		self.assertEqual(whole_number(2200), "2200")
		self.assertEqual(whole_number("25129.4"), "25129")
		self.assertEqual(whole_number(25129.6), "25130")

	def test_missing_weight_gives_an_empty_value(self):
		self.assertEqual(whole_number(None), "")
		self.assertEqual(whole_number(""), "")

	# --- rendered templates -----------------------------------------------

	def test_a_rendered_template_becomes_one_segment_per_entry(self):
		rendered = "UNH+1+CODECO'\n\n  BGM+34+1+9'\nCNT+16:1'\n"

		self.assertEqual(split_segments(rendered), ["UNH+1+CODECO'", "BGM+34+1+9'", "CNT+16:1'"])

	def test_a_segment_spread_over_several_lines_becomes_one_line(self):
		rendered = "TDT+20+0403\n\t+1++CMA:172'"

		self.assertEqual(split_segments(rendered), ["TDT+20+0403+1++CMA:172'"])

	def test_a_spread_segment_carries_no_line_break_into_the_interchange(self):
		for segment_text in split_segments("EQD+CN\n  +UACU6042588'\nCNT+16:1'"):
			self.assertNotIn("\n", segment_text)

	def test_two_segments_on_one_line_are_still_two_segments(self):
		self.assertEqual(split_segments("NAD+CF+CMA'CNT+16:1'"), ["NAD+CF+CMA'", "CNT+16:1'"])

	def test_a_released_terminator_does_not_end_a_segment(self):
		self.assertEqual(split_segments("NAD+CF+A?'B'"), ["NAD+CF+A?'B'"])

	def test_a_released_release_character_still_ends_the_segment(self):
		self.assertEqual(split_segments("NAD+CF+A??'"), ["NAD+CF+A??'"])

	def test_empty_trailing_elements_are_dropped(self):
		self.assertEqual(normalise_segment("TDT+1++3++GT:172+++"), "TDT+1++3++GT:172'")

	def test_empty_trailing_components_are_dropped(self):
		self.assertEqual(normalise_segment("TDT+20+0403+1++CMA:172:::"), "TDT+20+0403+1++CMA:172'")

	def test_empty_elements_in_the_middle_are_kept_because_they_are_positional(self):
		self.assertEqual(normalise_segment("TDT+1++3++GT:172::GTK+++T676"), "TDT+1++3++GT:172::GTK+++T676'")

	def test_a_released_separator_is_not_read_as_structure(self):
		self.assertEqual(normalise_segment("TDT+1++3++GT:172::A?+B?:CO"), "TDT+1++3++GT:172::A?+B?:CO'")

	def test_a_segment_of_only_a_tag_survives(self):
		self.assertEqual(normalise_segment("UNS+++"), "UNS'")
