"""TANeSW Summary report: one row per measure, Local + Transit + Unknown = Total, ERP gate-outs beside TANeSW."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import dashboard
from tanesw_integration.tanesw_integration.report.tanesw_summary import tanesw_summary as rpt


class TestTANeSWSummary(FrappeTestCase):
	def test_rows_add_up_and_both_left_rows_present(self):
		cols, rows, _m, _c, cards = rpt.execute({"from_date": "2026-11-01", "to_date": "2026-11-22"})
		self.assertTrue(rows)
		for r in rows:
			if r.get("local") is not None and "local" in r:
				self.assertEqual(r["total"], r["local"] + r["transit"] + r["unknown"], r["measure"])
		measures = [r["measure"] for r in rows]
		self.assertIn("Left our ICD (TANeSW-tracked vessels)", measures)
		self.assertIn("Left our ICD (ERP gate-outs, every box)", measures)
		self.assertTrue(any(c["label"].startswith("Left our ICD (ERP)") for c in cards))

	def test_erp_gate_outs_shape_without_data(self):
		out = dashboard.erp_gate_outs("2000-01-01", "2000-01-02")
		self.assertEqual(out["total"], 0)
		self.assertEqual(set(out), {"total", "Local", "Transit", "Unknown"})
