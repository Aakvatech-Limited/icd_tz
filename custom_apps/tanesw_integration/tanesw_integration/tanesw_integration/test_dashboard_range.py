"""TANeSW Dashboard page API (dashboard.get_dashboard): targets pro-rated by days, splits that add up."""

from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import dashboard


class TestTargets(FrappeTestCase):
	def run_target(self, start, end, values):
		def get_value(doctype, filters, field):
			return values.get(filters["month"])

		real_exists = frappe.db.exists
		with (
			patch.object(
				frappe.db,
				"exists",
				side_effect=lambda dt, *a, **k: True
				if dt == "DocType" and a and a[0] == "KPI Target"
				else real_exists(dt, *a, **k),
			),
			patch.object(frappe.db, "get_value", side_effect=get_value),
		):
			return dashboard.target_for("receiving", "Silver Entertrade Limited", start, end)

	def test_full_month_is_the_month_target(self):
		self.assertEqual(self.run_target(date(2026, 11, 1), date(2026, 11, 30), {"11": 3500}), 3500)

	def test_part_month_is_pro_rated_by_days(self):
		# 1-18 Nov of a 30-day month: 3500 x 18 / 30 = 2100
		self.assertEqual(self.run_target(date(2026, 11, 1), date(2026, 11, 18), {"11": 3500}), 2100)

	def test_range_across_months_adds_each_month(self):
		# 16-31 Oct (16 of 31 days of 2500) + 1-15 Nov (15 of 30 days of 3500) = 1290 + 1750
		self.assertEqual(
			self.run_target(date(2026, 10, 16), date(2026, 11, 15), {"10": 2500, "11": 3500}), 3040
		)

	def test_no_target_is_none(self):
		self.assertIsNone(self.run_target(date(2026, 8, 1), date(2026, 8, 31), {}))


class TestDashboard(FrappeTestCase):
	def test_splits_add_up_and_sections_present(self):
		d = dashboard.get_dashboard("2026-11-01", "2026-11-18")
		for sec in ("movement", "port_now", "port_range", "attention", "chart_received"):
			self.assertIn(sec, d)
		for item in d["movement"] + d["port_now"] + d["port_range"]:
			if item.get("split"):
				s = item["split"]
				self.assertEqual(s["total"], s["Local"] + s["Transit"] + s["Unknown"], item["key"])

	def test_reversed_range_is_swapped(self):
		d = dashboard.get_dashboard("2026-11-18", "2026-11-01")
		self.assertEqual((d["from_date"], d["to_date"]), ("2026-11-01", "2026-11-18"))
