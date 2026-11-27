from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import containers

OURS, OTHER = "WITZDL019", "WITZDL034"
TEST_MRN = "TEST-CNTR-DIVERT"


def ev(code, when, wh=OURS, name=None, dclr=None):
	return {"cagTrkngPrcssCd": code, "prcssDt": when, "wrhsCd": wh, "wrhsCdNm": name, "dclrNo": dclr}


DISCHARGE = ev("B21", "2026-11-01 08:00:00", "WTTZDL008")
GATE_OUT = ev("C61", "2026-11-03 10:00:00", "WTTZDL008")


class TestMilestones(FrappeTestCase):
	def test_carry_in_at_another_icd_is_diverted_and_complete(self):
		m = containers.milestones(
			[DISCHARGE, GATE_OUT, ev("C03", "2026-11-03 15:00:00", OTHER, "OTHER ICD LTD", "CRI-9")], OURS
		)
		self.assertEqual(m["status"], "Diverted")
		self.assertEqual(m["diverted_to"], "OTHER ICD LTD")
		self.assertEqual(str(m["diverted_on"]), "2026-11-03 15:00:00")
		self.assertEqual(m["tracking_complete"], 1)
		self.assertIsNone(m["received_on"])
		self.assertIsNone(m["carry_in_report_no"])  # another ICD's carry-in is not ours

	def test_diverted_falls_back_to_warehouse_code_without_a_name(self):
		m = containers.milestones([DISCHARGE, GATE_OUT, ev("C03", "2026-11-03 15:00:00", OTHER)], OURS)
		self.assertEqual(m["diverted_to"], OTHER)

	def test_received_by_us_wins_even_after_another_icd(self):
		m = containers.milestones(
			[
				DISCHARGE,
				GATE_OUT,
				ev("C03", "2026-11-03 15:00:00", OTHER),
				ev("C03", "2026-11-05 09:00:00", OURS, dclr="CRI-OURS"),
			],
			OURS,
		)
		self.assertEqual(m["status"], "Received at ICD")
		self.assertIsNone(m["diverted_to"])
		self.assertIsNone(m["diverted_on"])
		self.assertEqual(m["carry_in_report_no"], "CRI-OURS")

	def test_normal_flow_is_unchanged(self):
		self.assertEqual(containers.milestones([DISCHARGE], OURS)["status"], "At Terminal")
		m = containers.milestones([DISCHARGE, GATE_OUT], OURS)
		self.assertEqual(m["status"], "In Transit")
		self.assertEqual(m["tracking_complete"], 0)
		self.assertIsNone(m["diverted_to"])
		self.assertEqual(containers.milestones([], OURS)["status"], "Not Discharged")


class TestRecheckUnseen(FrappeTestCase):
	def setUp(self):
		frappe.db.delete("TANeSW Container", {"mrn": TEST_MRN})
		for cntr, complete in (("SEEN0000001", 0), ("GONE0000001", 0), ("DONE0000001", 1)):
			doc = frappe.new_doc("TANeSW Container")
			doc.update(
				{
					"name": f"{TEST_MRN}-{cntr}",
					"container_no": cntr,
					"mrn": TEST_MRN,
					"crn": "CRN1",
					"status": "In Transit",
					"tracking_complete": complete,
				}
			)
			doc.flags.ignore_links = True
			doc.insert(ignore_permissions=True, set_name=f"{TEST_MRN}-{cntr}")

	def tearDown(self):
		frappe.db.delete("TANeSW Container", {"mrn": TEST_MRN})

	@patch("tanesw_integration.cargo.tracking_container", return_value={})
	def test_box_off_our_bls_is_marked_removed_from_our_allocation(self, _tracking):
		from tanesw_integration.containers import _recheck_unseen

		stats = {"detail_calls": 0}
		_recheck_unseen(TEST_MRN, {f"{TEST_MRN}-SEEN0000001"}, "WITZDL019", stats, {"left": 10})

		def got(c):
			return frappe.db.get_value("TANeSW Container", f"{TEST_MRN}-{c}", "removed_from_allocation_on")

		self.assertTrue(got("GONE0000001"))  # TANeSW no longer lists it on our B/Ls
		self.assertFalse(got("SEEN0000001"))
		self.assertFalse(got("DONE0000001"))  # finished boxes are left alone
		self.assertEqual(stats.get("removed_from_allocation"), 1)

	@patch("tanesw_integration.cargo.tracking_container")
	def test_only_open_containers_missing_from_our_bls_are_reread(self, tracking):
		tracking.return_value = {
			"cntrPrcssLst": [DISCHARGE, GATE_OUT, ev("C03", "2026-11-03 15:00:00", OTHER, "OTHER ICD LTD")]
		}
		stats, budget = {"detail_calls": 0}, {"left": 10}
		containers._recheck_unseen(TEST_MRN, {f"{TEST_MRN}-SEEN0000001"}, OURS, stats, budget)

		tracking.assert_called_once_with("CRN1", "GONE0000001")
		gone = frappe.get_doc("TANeSW Container", f"{TEST_MRN}-GONE0000001")
		self.assertEqual(gone.status, "Diverted")
		self.assertEqual(gone.diverted_to, "OTHER ICD LTD")
		self.assertEqual(gone.tracking_complete, 1)
		self.assertEqual(
			frappe.db.get_value("TANeSW Container", f"{TEST_MRN}-SEEN0000001", "status"), "In Transit"
		)
		self.assertEqual((stats["detail_calls"], stats["off_our_bls"], budget["left"]), (1, 1, 9))

	@patch("tanesw_integration.cargo.tracking_container")
	def test_respects_the_detail_call_budget(self, tracking):
		containers._recheck_unseen(TEST_MRN, set(), OURS, {"detail_calls": 0}, {"left": 0})
		tracking.assert_not_called()

	@patch("tanesw_integration.cargo.tracking_container", return_value={})
	def test_empty_history_leaves_the_record_alone(self, _tracking):
		containers._recheck_unseen(TEST_MRN, set(), OURS, {"detail_calls": 0}, {"left": 10})
		self.assertEqual(
			frappe.db.get_value("TANeSW Container", f"{TEST_MRN}-GONE0000001", "status"), "In Transit"
		)


class TestRealTimeFromCarryIn(FrappeTestCase):
	"""The 5-minute carry-in check moves a container's status forward at once (a box received
	two hours after leaving the port, while the hourly sync still showed it At Terminal)."""

	def make(self, status, cntr="RTTU0000001"):
		frappe.db.delete("TANeSW Container", {"mrn": TEST_MRN})
		doc = frappe.new_doc("TANeSW Container")
		doc.update({"container_no": cntr, "mrn": TEST_MRN, "crn": "CRN1", "status": status})
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True, set_name=f"{TEST_MRN}-{cntr}")
		return doc.name

	def tearDown(self):
		frappe.db.delete("TANeSW Container", {"mrn": TEST_MRN})

	def status(self, name):
		return frappe.db.get_value("TANeSW Container", name, "status")

	def test_left_the_port_moves_at_terminal_to_in_transit(self):
		from tanesw_integration.containers import advance_from_carry_in

		name = self.make("At Terminal")
		self.assertEqual(advance_from_carry_in(TEST_MRN, "RTTU0000001", 1, 0), "In Transit")
		self.assertEqual(self.status(name), "In Transit")

	def test_entered_our_gate_marks_received_with_the_carry_in_time(self):
		from tanesw_integration.containers import advance_from_carry_in

		name = self.make("In Transit")
		advance_from_carry_in(TEST_MRN, "RTTU0000001", 1, 1, "2026-11-12 13:23:43")
		self.assertEqual(self.status(name), "Received at ICD")
		self.assertEqual(
			str(frappe.db.get_value("TANeSW Container", name, "received_on")), "2026-11-12 13:23:43"
		)

	def test_never_moves_backwards(self):
		from tanesw_integration.containers import advance_from_carry_in

		name = self.make("Received at ICD")
		self.assertIsNone(advance_from_carry_in(TEST_MRN, "RTTU0000001", 1, 0))
		self.assertEqual(self.status(name), "Received at ICD")

	def test_unknown_container_is_ignored(self):
		from tanesw_integration.containers import advance_from_carry_in

		self.assertIsNone(advance_from_carry_in(TEST_MRN, "NOTT0000000", 1, 1))

	def test_live_pass_skips_ships_not_yet_arrived(self):
		from frappe.utils import add_days, nowdate

		from tanesw_integration.containers import _mrns_to_track

		names = []
		for mrn, arrival in (
			("26RTT000001", add_days(nowdate(), -2)),
			("26RTT000002", add_days(nowdate(), 5)),
		):
			if not frappe.db.exists("TANeSW Vessel Allocation", mrn):
				v = frappe.new_doc("TANeSW Vessel Allocation")
				v.update({"mrn": mrn, "arrival_date": arrival})
				v.flags.ignore_mandatory = True
				v.insert(ignore_permissions=True, set_name=mrn)
			names.append(mrn)
		try:
			live, full = _mrns_to_track(45, full=False), _mrns_to_track(45, full=True)
			self.assertIn("26RTT000001", live)
			self.assertNotIn("26RTT000002", live)
			self.assertIn("26RTT000002", full)
		finally:
			for n in names:
				frappe.db.delete("TANeSW Vessel Allocation", {"name": n})
