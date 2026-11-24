"""Container Reception dates vs the TANeSW carry-in (reception_dates.py)."""

from datetime import date, datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import reception_dates as rd

MRN = "26TST000977"  # own MRN: test_icd_link uses 26TST000901
DT = rd.DOCTYPE


def rec(**kw):
	base = dict(
		name="TST-CR-0001",
		container_no="TSTU9000001",
		manifest="TST-MF-901",
		mrn=MRN,
		m_bl_no="BL901",
		freight_indicator="FCL",
		company="Test Co",
		posting_date=date(2026, 11, 16),
		icd_time_in="22:32:55",
		received_date=date(2026, 11, 16),
		ship_dc_date=date(2026, 11, 7),
		clerk=None,
	)
	base.update(kw)
	return frappe._dict(base)


class TestRules(FrappeTestCase):
	def test_icd_tz_received_date_rule(self):
		# 48 h after Ship D/C or more -> arrival date; inside 48 h -> Ship D/C
		self.assertEqual(rd.received_date_rule(date(2026, 11, 9), date(2026, 11, 7), 48), date(2026, 11, 9))
		self.assertEqual(rd.received_date_rule(date(2026, 11, 8), date(2026, 11, 7), 48), date(2026, 11, 7))

	def test_posted_two_days_after_the_carry_in_loses_two_storage_days(self):
		# carried in late on one day, posted two days later
		v = rd.compare(rec(), (datetime(2026, 11, 14, 22, 37, 10), "TANeSW Tracking"), date(2026, 11, 14), 48)
		self.assertEqual(v["status"], rd.LATE)
		self.assertEqual(v["days_late"], 2)
		self.assertEqual(v["expected_received_date"], date(2026, 11, 14))
		self.assertEqual(v["storage_days_lost"], 2)

	def test_same_day_and_time_matches(self):
		v = rd.compare(
			rec(posting_date=date(2026, 11, 14)),
			(datetime(2026, 11, 14, 22, 37), "TANeSW Tracking"),
			date(2026, 11, 14),
			48,
		)
		self.assertEqual(v["status"], rd.MATCHES)

	def test_same_day_hours_apart_is_time_differs(self):
		v = rd.compare(
			rec(posting_date=date(2026, 11, 14), icd_time_in="08:00:00"),
			(datetime(2026, 11, 14, 22, 37), "TANeSW Tracking"),
			date(2026, 11, 14),
			48,
		)
		self.assertEqual(v["status"], rd.TIME_DIFFERS)

	def test_late_posting_inside_the_threshold_costs_nothing(self):
		# Ship D/C 13/11, carried in 14/11, posted 15/11: storage starts at Ship D/C either way
		v = rd.compare(
			rec(
				posting_date=date(2026, 11, 15),
				received_date=date(2026, 11, 13),
				ship_dc_date=date(2026, 11, 13),
			),
			(datetime(2026, 11, 14, 9, 0), "TANeSW Tracking"),
			date(2026, 11, 14),
			48,
		)
		self.assertEqual(v["status"], rd.LATE)
		self.assertEqual(v["storage_days_lost"], 0)

	def test_storage_follows_the_last_box_on_the_bl(self):
		# this box came 10/11 but the B/L's last box 14/11: icd_tz starts the whole B/L on 14/11, not a loss
		v = rd.compare(
			rec(posting_date=date(2026, 11, 10), icd_time_in="09:05:00", received_date=date(2026, 11, 14)),
			(datetime(2026, 11, 10, 9, 0), "TANeSW Tracking"),
			date(2026, 11, 14),
			48,
		)
		self.assertEqual(v["status"], rd.MATCHES)
		self.assertEqual(v["storage_days_lost"], 0)

	def test_no_carry_in(self):
		self.assertEqual(rd.compare(rec(), None, None, 48)["status"], rd.NO_CARRY_IN)


class TestJob(FrappeTestCase):
	def setUp(self):
		self.addCleanup(self.cleanup)
		for c, received in (("TSTU9000001", "2026-11-14 22:37:10"), ("TSTU9000002", None)):
			frappe.get_doc(
				{
					"doctype": "TANeSW Container",
					"container_no": c,
					"mrn": MRN,
					"bl_no": "BL901",
					"status": "Received at ICD" if received else "At Terminal",
					"received_on": received,
				}
			).insert(ignore_permissions=True, set_name=f"{MRN}-{c}")

	def cleanup(self):
		frappe.db.delete("TANeSW Container", {"mrn": MRN})
		frappe.db.delete(DT, {"mrn": MRN})
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the job under test commits per row, so must its cleanup

	def test_job_writes_one_row_per_tracked_reception(self):
		# boxes 2 and 3 on another B/L: a B/L's storage starts from its LAST box, posted 16/11 here
		rows = [
			rec(),
			rec(name="TST-CR-0002", container_no="TSTU9000002", m_bl_no="BL902"),
			rec(name="TST-CR-0003", container_no="TSTU9999999", m_bl_no="BL902"),
		]  # 3: not tracked, skipped
		with patch.object(rd, "_receptions", return_value=rows), patch.object(rd, "_record"):
			stats = rd.check_reception_dates(force=True)
			again = rd.check_reception_dates(force=True)  # re-run updates, never duplicates
		self.assertEqual(stats["checked"], 2)
		self.assertEqual(again["checked"], 2)
		self.assertEqual(frappe.db.count(DT, {"mrn": MRN}), 2)
		self.assertEqual(frappe.db.get_value(DT, "TST-CR-0001", "status"), rd.LATE)
		self.assertEqual(frappe.db.get_value(DT, "TST-CR-0001", "storage_days_lost"), 2)
		self.assertEqual(frappe.db.get_value(DT, "TST-CR-0002", "status"), rd.NO_CARRY_IN)
		self.assertFalse(frappe.db.exists(DT, "TST-CR-0003"))


class FakeReception(frappe._dict):
	def is_new(self):
		return True

	def set_received_date(self):
		self.received_date = rd.received_date_rule(self.posting_date, self.ship_dc_date, 48)


class TestOnSave(FrappeTestCase):
	def doc(self, **kw):
		d = FakeReception(
			doctype="Container Reception",
			name="new-cr",
			docstatus=0,
			container_no="TSTU9000001",
			manifest="TST-MF-901",
			posting_date=date(2026, 11, 16),
			icd_time_in="22:32:55",
			ship_dc_date=date(2026, 11, 7),
			received_date=None,
		)
		d.update(kw)
		return d

	def run_hook(self, mode, doc, enabled=1):
		carry = {(MRN, "TSTU9000001"): (datetime(2026, 11, 14, 22, 37, 10), "TANeSW Tracking")}
		settings = {"reception_date_on_save": mode, "enable_reception_date_check": enabled}
		with (
			patch.object(frappe.db, "get_single_value", side_effect=lambda dt, f, *a, **k: settings.get(f)),
			patch.object(frappe.db, "get_value", return_value=MRN),
			patch.object(rd, "carry_in_times", return_value=carry),
			patch.object(frappe, "msgprint") as msg,
		):
			rd.on_reception_validate(doc)
		return msg

	def test_correct_sets_the_carry_in_and_icd_tz_recomputes_storage(self):
		d = self.doc()
		self.run_hook("Correct", d)
		self.assertEqual(d.posting_date, date(2026, 11, 14))
		self.assertEqual(d.icd_time_in, "22:37:10")
		self.assertEqual(d.received_date, date(2026, 11, 14))

	def test_warn_changes_nothing(self):
		d = self.doc()
		msg = self.run_hook("Warn", d)
		self.assertEqual(d.posting_date, date(2026, 11, 16))
		msg.assert_called_once()

	def test_off_and_matching_dates_do_nothing(self):
		self.run_hook("Off", self.doc()).assert_not_called()
		self.run_hook("Correct", self.doc(posting_date=date(2026, 11, 14))).assert_not_called()

	def test_carry_in_before_discharge_is_an_older_visit(self):
		d = self.doc(ship_dc_date=date(2026, 11, 15))
		self.run_hook("Correct", d).assert_not_called()
		self.assertEqual(d.posting_date, date(2026, 11, 16))

	def test_nothing_changes_until_the_check_is_switched_on(self):
		d = self.doc()
		self.run_hook("Correct", d, enabled=0).assert_not_called()
		self.assertEqual(d.posting_date, date(2026, 11, 16))
