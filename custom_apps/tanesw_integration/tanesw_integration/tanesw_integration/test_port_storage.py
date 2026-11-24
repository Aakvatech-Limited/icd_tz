"""Port storage rule (port_storage.py): Local Free 1-5 / Single 6-12 / Double 13+, Transit Free 1-15 / Single 16-22 /
Double 23+, day 1 = discharge day, counting stops at the terminal Gate Out."""

from datetime import date, datetime

from frappe.tests.utils import FrappeTestCase

from tanesw_integration import port_storage as ps


class TestPortStorage(FrappeTestCase):
	def test_classification(self):
		self.assertEqual(ps.classify("IM"), ps.LOCAL)
		self.assertEqual(ps.classify(" tr "), ps.TRANSIT)
		self.assertEqual(ps.classify(None), ps.UNKNOWN)

	def test_local_last_free_day_is_day_5(self):
		# discharged 1 Nov, gated out 5 Nov = day 5: still free
		st = ps.storage(datetime(2026, 11, 1, 23, 0), datetime(2026, 11, 5, 8, 0), ps.LOCAL)
		self.assertEqual((st.port_days, st.days_over, st.free_until), (5, 0, date(2026, 11, 5)))
		self.assertEqual(st.storage_status, ps.LEFT_FREE)

	def test_local_single_then_double(self):
		# day 13 is the first Double day for Local: 7 Single (6-12) + 1 Double
		st = ps.storage(date(2026, 11, 1), date(2026, 11, 13), ps.LOCAL)
		self.assertEqual((st.port_days, st.days_over, st.single_days, st.double_days), (13, 8, 7, 1))
		self.assertEqual(st.storage_status, ps.LEFT_CHARGED)

	def test_transit_bands(self):
		st = ps.storage(date(2026, 11, 1), date(2026, 11, 15), ps.TRANSIT)
		self.assertEqual((st.days_over, st.free_until), (0, date(2026, 11, 15)))
		st = ps.storage(date(2026, 11, 1), date(2026, 11, 23), ps.TRANSIT)
		self.assertEqual((st.single_days, st.double_days), (7, 1))

	def test_still_at_port_counts_to_today(self):
		st = ps.storage(date(2026, 11, 14), None, ps.LOCAL, today=date(2026, 11, 17))
		self.assertEqual((st.port_days, st.free_days_left, st.storage_status), (4, 1, ps.ENDING))
		st = ps.storage(date(2026, 11, 5), None, ps.LOCAL, today=date(2026, 11, 17))
		self.assertEqual((st.days_over, st.storage_status), (8, ps.CHARGED))
		st = ps.storage(date(2026, 11, 14), None, ps.TRANSIT, today=date(2026, 11, 17))
		self.assertEqual(st.storage_status, ps.WITHIN)

	def test_unknown_is_held_to_local_and_not_discharged_is_none(self):
		self.assertEqual(
			ps.storage(date(2026, 11, 1), None, ps.UNKNOWN, today=date(2026, 11, 1)).free_days, 5
		)
		self.assertIsNone(ps.storage(None, None, ps.LOCAL))
