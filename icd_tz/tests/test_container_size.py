# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.utils import get_container_length, get_size_bucket


class TestContainerSize(FrappeTestCase):
	"""Reading a container size and charging it at a pricing size"""

	def test_an_iso_code_gives_its_length_in_feet(self):
		for size, feet in (("22G1", 20), ("42G1", 40), ("45G1", 40), ("L5G1", 45), ("M2G1", 48)):
			self.assertEqual(get_container_length(size), feet)

	def test_a_container_is_charged_at_the_largest_pricing_size_it_reaches(self):
		for size, bucket in (("22G1", "20ft"), ("42G1", "40ft"), ("45R1", "40ft")):
			self.assertEqual(get_size_bucket(size), bucket)

	def test_a_size_between_two_pricing_sizes_rounds_down(self):
		# 24ft and 30ft are charged as 20ft, 45ft through 53ft as 40ft
		for size, bucket in (
			("B2G1", "20ft"),
			("32G1", "20ft"),
			("L5G1", "40ft"),
			("95G1", "40ft"),
			("N0G1", "40ft"),
			("P2G1", "40ft"),
		):
			self.assertEqual(get_size_bucket(size), bucket)

	def test_a_letter_length_code_is_not_read_off_free_text(self):
		# Size is a free text field, so HC20 is a 20ft box written with a prefix, not a
		# 43ft one. Only a full ISO code lets the first letter mean a length.
		for size in ("HC20", "GP20", "HQ20", "TEU20"):
			self.assertEqual(get_size_bucket(size), "20ft")

		self.assertEqual(get_size_bucket("FT40"), "40ft")

	def test_a_plain_or_padded_size_is_read_as_written(self):
		for size, bucket in (("20", "20ft"), ("40", "40ft"), ("20ft", "20ft"), ("40HC", "40ft")):
			self.assertEqual(get_size_bucket(size), bucket)

		self.assertEqual(get_size_bucket(" 22G1"), "20ft")

	def test_a_container_below_the_smallest_pricing_size_has_none(self):
		# the caller reports this as missing criteria rather than charging it at 20ft
		self.assertIsNone(get_size_bucket("12G1"))

	def test_a_size_that_reads_as_nothing_has_none(self):
		for size in ("", None, "TWENTY", "-", "   "):
			self.assertIsNone(get_size_bucket(size))
