from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from tanesw_integration import anomalies as an
from tanesw_integration import containers

OURS = "WITZDL019"
MRN, MF = "26TST000777", "TEST-ANOM-MF"


def t(**kw):
	base = dict(
		name=f"{MRN}-TSTU0000001",
		container_no="TSTU0000001",
		mrn=MRN,
		bl_no="BL1",
		crn="CRN1",
		status="At Terminal",
		terminal="WTTZDL008",
		dwell_days=1.0,
		last_event="x",
		last_event_on=None,
		discharged_on=None,
		received_on=None,
		left_icd_on=None,
		left_icd_event=None,
		diverted_to=None,
		diverted_on=None,
		arrival_date=None,
		tracking_complete=0,
	)
	base.update(kw)
	return frappe._dict(base)


def erp(**kw):
	base = {
		"containers": ["C1"],
		"status": "In Yard",
		"empty": 0,
		"invoice": None,
		"outstanding": 0.0,
		"submitted_reception": "CR1",
		"draft_reception": None,
	}
	base.update(kw)
	return base


class TestExitTracking(FrappeTestCase):
	def ev(self, code, when, wh, name=""):
		return {"cagTrkngPrcssCd": code, "prcssDt": when, "wrhsCd": wh, "cagTrkngPrcssCdNm": name}

	def test_exit_from_our_icd_after_receipt_completes_tracking(self):
		h = [
			self.ev("B21", "2026-11-01 08:00:00", "WTTZDL008"),
			self.ev("C61", "2026-11-02 09:00:00", "WTTZDL008"),
			self.ev("C03", "2026-11-02 12:00:00", OURS),
			self.ev("C61", "2026-11-09 10:00:00", OURS, "Gate Out Confirm"),
		]
		m = containers.milestones(h, OURS)
		self.assertEqual(m["status"], "Received at ICD")
		self.assertEqual(str(m["left_icd_on"]), "2026-11-09 10:00:00")
		self.assertEqual(m["tracking_complete"], 1)
		self.assertEqual(str(m["gate_out_on"]), "2026-11-02 09:00:00")  # port gate-out unchanged

	def test_received_but_not_left_keeps_tracking(self):
		h = [
			self.ev("C03", "2026-11-02 12:00:00", OURS),
			self.ev("C51", "2026-11-05 10:00:00", OURS, "Carry Out Report Approved"),
		]
		m = containers.milestones(h, OURS)
		self.assertIsNone(m["left_icd_on"])  # an approved carry-out is not the exit (3 Nov rule)
		self.assertEqual(m["tracking_complete"], 0)

	def test_exit_rule_matches_the_old_tracker(self):
		self.assertTrue(containers.is_exit_event("C62", ""))
		self.assertTrue(containers.is_exit_event("Z99", "Gate Out Confirm"))
		self.assertFalse(containers.is_exit_event("C50", "Carry Out Report Approved"))
		self.assertTrue(containers.is_exit_event("Z98", "Carry Out Confirmed"))
		self.assertFalse(containers.is_exit_event("C51", "Carry Out Report Submitted"))


class TestClassify(FrappeTestCase):
	def check(self, rec, side, expected, free=7):
		with patch.object(an, "erp_side", return_value=side):
			v = an.classify(rec, free)
		self.assertEqual(v["anomaly_type"], expected, v["action_required"])
		return v

	def test_delivered_on_tanesw_split_by_billing(self):
		left = t(status="Received at ICD", received_on=now_datetime(), left_icd_on=now_datetime())
		self.check(left, erp(invoice=None), an.LEAKAGE)
		self.check(left, erp(invoice="SI1", outstanding=500.0), an.UNPAID)
		self.check(left, erp(invoice="SI1", outstanding=0.0), an.NOT_IN_ERP)
		self.check(left, erp(empty=1), an.NOT_IN_ERP)
		self.check(left, erp(containers=[], status="Not Received in ERP"), an.NOT_IN_ERP)
		self.check(left, erp(status="Delivered"), an.NORMAL)

	def test_diverted_and_border(self):
		v = self.check(t(status="Diverted", diverted_to="OTHER ICD LTD"), erp(), an.DIVERTED)
		self.assertEqual((v["is_diverted"], v["diverted_to"]), (1, "OTHER ICD LTD"))
		self.check(t(status="Diverted", diverted_to="TUNDUMA BORDER POST"), erp(), an.BORDER)

	def test_ghost_and_pending_after_12_hours_only(self):
		old = t(status="Received at ICD", received_on=add_to_date(now_datetime(), hours=-13))
		new = t(status="Received at ICD", received_on=add_to_date(now_datetime(), hours=-2))
		self.check(old, erp(submitted_reception=None), an.GHOST)
		self.check(old, erp(submitted_reception=None, draft_reception="CR-D"), an.PENDING)
		self.check(new, erp(submitted_reception=None), an.NORMAL)
		self.check(old, erp(), an.NORMAL)

	def test_stranded_past_free_port_days_with_band(self):
		v = self.check(t(dwell_days=9.5), erp(), an.STRANDED)
		self.assertIn("single rate", v["action_required"])
		v = self.check(t(dwell_days=16), erp(), an.STRANDED)
		self.assertIn("double rate", v["action_required"])
		self.check(t(dwell_days=6.9), erp(), an.NORMAL)


class TestTrackLog(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("DocType", an.TRACK_LOG) or "icd_tz" not in frappe.get_installed_apps():
			raise cls.skipTest(cls, "needs the Container Allocation Track log DocType and icd_tz")

	def setUp(self):
		frappe.db.delete(an.TRACK_LOG, {"container_no": ["like", "TSTU%"]})

	def tearDown(self):
		frappe.db.delete(an.TRACK_LOG, {"container_no": ["like", "TSTU%"]})

	def test_anomaly_written_once_then_cleared_when_resolved(self):
		v = {
			"container_no": "TSTU0000001",
			"m_bl_no": "BL1",
			"anomaly_type": an.UNPAID,
			"action_required": "x",
			"is_diverted": 0,
		}
		self.assertTrue(an._upsert(v))
		self.assertTrue(an._upsert(v))  # same row updated, not duplicated
		self.assertEqual(frappe.db.count(an.TRACK_LOG, {"container_no": "TSTU0000001"}), 1)
		self.assertEqual(frappe.db.get_value(an.TRACK_LOG, "TSTU0000001", "anomaly_type"), an.UNPAID)
		an._upsert({**v, "anomaly_type": an.NORMAL})
		self.assertEqual(frappe.db.get_value(an.TRACK_LOG, "TSTU0000001", "anomaly_type"), an.NORMAL)

	def test_normal_container_never_creates_a_row(self):
		self.assertFalse(
			an._upsert({"container_no": "TSTU0000002", "anomaly_type": an.NORMAL, "is_diverted": 0})
		)
		self.assertFalse(frappe.db.exists(an.TRACK_LOG, "TSTU0000002"))

	def test_free_port_days_read_from_icd_setting(self):
		self.assertGreaterEqual(an.port_free_days(), 1)

	def test_job_off_by_default_does_nothing(self):
		old = frappe.db.get_single_value("TANeSW Settings", "enable_anomaly_tracking")
		try:
			frappe.db.set_single_value("TANeSW Settings", "enable_anomaly_tracking", 0)
			self.assertEqual(an.track_anomalies(), {"status": "off"})
		finally:
			frappe.db.set_single_value("TANeSW Settings", "enable_anomaly_tracking", old or 0)


class TestBlLevelAndLots(FrappeTestCase):
	def test_border_crossing_after_receipt_means_left(self):
		def ev(c, when, wh, n=""):
			return {"cagTrkngPrcssCd": c, "prcssDt": when, "wrhsCd": wh, "cagTrkngPrcssCdNm": n}

		m = containers.milestones(
			[
				ev("C03", "2026-10-02 01:00:00", OURS),
				ev("E31", "2026-10-20 10:00:00", "WVTZTM000", "Border Point Confirm"),
			],
			OURS,
		)
		self.assertEqual(str(m["left_icd_on"]), "2026-10-20 10:00:00")

	@patch("tanesw_integration.cargo.tracking_detail")
	def test_bl_steps_count_only_for_a_single_box_bl(self, detail):
		steps = [
			{
				"cagTrkngPrcssCd": "C61",
				"cagTrkngPrcssCdNm": "Gate Out Confirm",
				"wrhsCd": OURS,
				"prcssDt": "2026-06-20 03:31:11",
			}
		]
		detail.return_value = {"blCntrLst": [{"cntrNo": "A"}], "blPrcssLst": steps}
		self.assertEqual(str(containers.bl_level_exit("CRN", OURS)[0]), "2026-06-20 03:31:11")
		detail.return_value = {"blCntrLst": [{"cntrNo": "A"}, {"cntrNo": "B"}], "blPrcssLst": steps}
		self.assertIsNone(containers.bl_level_exit("CRN", OURS))  # a sister box's exit must not count

	def test_lcl_lot_problem_takes_the_worst_lot(self):
		rec = t(status="Received at ICD", received_on=now_datetime())
		probs = [
			{
				"kind": an.UNPAID,
				"h_bl_no": "H1",
				"left_on": now_datetime(),
				"status": "In Yard",
				"invoice": "SI1",
				"outstanding": 10.0,
			},
			{
				"kind": an.LEAKAGE,
				"h_bl_no": "H2",
				"left_on": now_datetime(),
				"status": "In Yard",
				"invoice": None,
				"outstanding": 0.0,
			},
		]
		with (
			patch.object(an, "erp_side", return_value=erp()),
			patch.object(an, "lot_problems", return_value=probs),
		):
			v = an.classify(rec, 7)
		self.assertEqual(v["anomaly_type"], an.LEAKAGE)
		self.assertIn("HBL H1", v["action_required"])
		self.assertIn("HBL H2", v["action_required"])
