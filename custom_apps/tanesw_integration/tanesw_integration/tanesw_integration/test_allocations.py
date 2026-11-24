from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import allocations

TEST_MRN = "TEST-ALLOCATION-WATCHER"


class TestAllocationWatcher(FrappeTestCase):
	def setUp(self):
		self.settings = frappe.get_single("TANeSW Settings")
		self.original = {
			"enable_read_sync": self.settings.enable_read_sync,
			"background_watcher_account": self.settings.background_watcher_account,
			"background_watcher_fallback_account": self.settings.background_watcher_fallback_account,
			"allocation_watcher_initialized": self.settings.allocation_watcher_initialized,
			"landed_watch_initialized": self.settings.get("landed_watch_initialized") or 0,
		}
		frappe.db.delete("TANeSW Vessel Allocation", {"mrn": TEST_MRN})

	def tearDown(self):
		frappe.db.delete("TANeSW Vessel Allocation", {"mrn": TEST_MRN})
		for fieldname, value in self.original.items():
			frappe.db.set_single_value("TANeSW Settings", fieldname, value)

	def configure(self, initialized):
		frappe.db.set_single_value("TANeSW Settings", "enable_read_sync", 1)
		frappe.db.set_single_value("TANeSW Settings", "background_watcher_account", "Administrator")
		frappe.db.set_single_value(
			"TANeSW Settings", "background_watcher_fallback_account", "watcher-two@example.com"
		)
		frappe.db.set_single_value("TANeSW Settings", "allocation_watcher_initialized", initialized)

	def row(self, bl_count=1, container_count=2):
		return {
			"mrn": TEST_MRN,
			"vsslNm": "TEST VESSEL",
			"voygNo": "V001",
			"arvlXptdDt": "2026-11-12",
			"our_bl_count": bl_count,
			"our_cntr_count": container_count,
		}

	@patch("tanesw_integration.allocations._watch_landed")
	@patch("tanesw_integration.allocations._queue_notification")
	@patch("tanesw_integration.allocations._scan_using_accounts")
	def test_first_complete_scan_seeds_without_notification(self, scan, notify, _landed):
		self.configure(initialized=0)
		scan.return_value = (
			{"content": [self.row()], "unverified": [], "facility_code": "WITZDL019"},
			"Administrator",
		)

		result = allocations.watch_allocations()

		allocation = frappe.get_doc("TANeSW Vessel Allocation", TEST_MRN)
		self.assertEqual(allocation.bl_count, 1)
		self.assertEqual(allocation.container_count, 2)
		self.assertEqual(allocation.facility_code, "WITZDL019")
		self.assertEqual(result["seeded"], 1)
		self.assertEqual(frappe.db.get_single_value("TANeSW Settings", "allocation_watcher_initialized"), 1)
		notify.assert_not_called()

	@patch("tanesw_integration.allocations._watch_landed")
	@patch("tanesw_integration.allocations._queue_notification")
	@patch("tanesw_integration.allocations._scan_using_accounts")
	def test_count_change_updates_record_and_notifies(self, scan, notify, _landed):
		self.configure(initialized=1)
		allocations._insert_allocation(self.row(), "Administrator", "Baseline")
		scan.return_value = (
			{"content": [self.row(bl_count=3, container_count=4)], "unverified": []},
			"Administrator",
		)

		result = allocations.watch_allocations()

		allocation = frappe.get_doc("TANeSW Vessel Allocation", TEST_MRN)
		self.assertEqual((allocation.bl_count, allocation.container_count), (3, 4))
		self.assertEqual(result["changed"], 1)
		notify.assert_called_once()

	@patch("tanesw_integration.allocations._watch_landed")
	@patch("tanesw_integration.allocations._queue_notification")
	@patch("tanesw_integration.allocations._scan_using_accounts", return_value=(None, None))
	def test_failed_scan_does_not_change_existing_allocation(self, scan, notify, _landed):
		self.configure(initialized=1)
		allocations._insert_allocation(self.row(), "Administrator", "Baseline")

		result = allocations.watch_allocations()

		allocation = frappe.get_doc("TANeSW Vessel Allocation", TEST_MRN)
		self.assertEqual((allocation.bl_count, allocation.container_count), (1, 2))
		self.assertEqual(result["status"], "scan_failed")
		notify.assert_not_called()

	@patch("tanesw_integration.allocations.frappe.sendmail")
	@patch("tanesw_integration.allocations.frappe.db.get_single_value", return_value=1)
	@patch("frappe.desk.doctype.notification_log.notification_log.make_notification_logs")
	@patch("tanesw_integration.allocations.frappe.get_all")
	def test_notification_creates_one_atomic_bell_batch_with_record_link(
		self, get_all, make_logs, _gsv, sendmail
	):
		# role holders, enabled TANeSW accounts, then enabled system users
		get_all.side_effect = [
			["watcher-two@example.com"],
			["tanesw-account@example.com"],
			["watcher-two@example.com", "tanesw-account@example.com"],
			# email: TANeSW Operations role holders, then enabled system users among them
			["ops@example.com"],
			["ops@example.com"],
		]
		allocation = frappe._dict(
			name=TEST_MRN,
			mrn=TEST_MRN,
			vessel_name="TEST VESSEL",
			bl_count=1,
			container_count=2,
		)

		allocations._queue_notification(allocation, "New Allocation")

		doc, users = make_logs.call_args.args
		self.assertEqual(users, ["watcher-two@example.com", "tanesw-account@example.com"])
		self.assertEqual(doc["type"], "Alert")
		self.assertEqual(doc["document_type"], "TANeSW Vessel Allocation")
		self.assertEqual(doc["document_name"], TEST_MRN)
		# Frappe never emails "Alert" notifications itself, so the watcher must send the email explicitly.
		sendmail.assert_called_once()
		self.assertEqual(sendmail.call_args.kwargs["recipients"], ["ops@example.com"])  # operations team only
		self.assertIn("TEST VESSEL", sendmail.call_args.kwargs["subject"])

	@patch("tanesw_integration.allocations.frappe.sendmail")
	@patch("tanesw_integration.allocations.frappe.db.get_single_value", return_value=1)
	@patch("frappe.desk.doctype.notification_log.notification_log.make_notification_logs")
	@patch("tanesw_integration.allocations.frappe.get_all")
	def test_no_operations_role_holder_means_bell_only(self, get_all, make_logs, _gsv, sendmail):
		get_all.side_effect = [["a@example.com"], [], ["a@example.com"], []]
		allocations._queue_notification(
			frappe._dict(name=TEST_MRN, mrn=TEST_MRN, vessel_name="V", bl_count=1, container_count=1),
			"New Allocation",
		)
		make_logs.assert_called_once()
		sendmail.assert_not_called()

	@patch("tanesw_integration.allocations._scan_as_account")
	def test_scanner_uses_fallback_account(self, scan):
		scan.side_effect = [RuntimeError("primary unavailable"), {"content": [], "unverified": []}]

		result, account = allocations._scan_using_accounts(
			["Administrator", "watcher-two@example.com"], "2026-11-01", "2026-12-01"
		)

		self.assertEqual(account, "watcher-two@example.com")
		self.assertEqual(result["content"], [])
		self.assertEqual(scan.call_count, 2)

	@patch("tanesw_integration.allocations._watch_landed")
	@patch("tanesw_integration.allocations._queue_notification")
	@patch("tanesw_integration.allocations._scan_using_accounts")
	def test_baseline_with_unverified_still_initializes_and_seeds_them_silently_later(
		self, scan, notify, _landed
	):
		self.configure(initialized=0)
		frappe.db.set_single_value("TANeSW Settings", "allocation_baseline_pending", "[]")
		scan.return_value = (
			{"content": [], "unverified": [{"mrn": TEST_MRN}], "facility_code": "WITZDL019"},
			"Administrator",
		)
		allocations.watch_allocations()
		self.assertEqual(frappe.db.get_single_value("TANeSW Settings", "allocation_watcher_initialized"), 1)

		# next run: the manifest answers and is ours -> seeded as Baseline, no alert
		scan.return_value = (
			{"content": [self.row()], "unverified": [], "facility_code": "WITZDL019"},
			"Administrator",
		)
		result = allocations.watch_allocations()
		self.assertEqual(result["seeded"], 1)
		self.assertEqual(frappe.get_doc("TANeSW Vessel Allocation", TEST_MRN).last_event, "Baseline")
		notify.assert_not_called()

	@patch("tanesw_integration.allocations._watch_landed")
	@patch("tanesw_integration.allocations._queue_notification", return_value=2)
	@patch("tanesw_integration.allocations._scan_using_accounts")
	def test_new_allocation_after_baseline_alerts_and_run_is_recorded(self, scan, notify, _landed):
		self.configure(initialized=1)
		frappe.db.set_single_value("TANeSW Settings", "allocation_baseline_pending", "[]")
		scan.return_value = ({"content": [self.row()], "unverified": [], "scanned": 5}, "Administrator")
		result = allocations.watch_allocations()
		self.assertEqual((result["new"], result["notified"]), (1, 2))
		notify.assert_called_once()
		self.assertIn('"new": 1', frappe.db.get_single_value("TANeSW Settings", "allocation_last_result"))

	def landed_row(self, total=50, landed=6, declared=0):
		return {
			"mrn": TEST_MRN,
			"vsslNm": "TEST VESSEL",
			"vygNo": "V001",
			"arvlDt": "2026-11-05 00:00:00",
			"totCnt": total,
			"trgtCnt": landed,
			"dclrCnt": declared,
		}

	@patch("tanesw_integration.allocations._queue_notification", return_value=1)
	@patch("tanesw_integration.cargo.icd_expected_list")
	def test_first_landed_run_after_deploy_is_silent_even_with_int_default_zero(self, xptd, notify):
		"""Int columns default to 0: the first run must not treat every landed vessel as 0 -> N."""
		self.configure(initialized=1)
		frappe.db.set_single_value("TANeSW Settings", "landed_watch_initialized", 0)
		allocations._insert_allocation(self.row(), "Administrator", "Baseline")  # landed_count = 0 (default)
		xptd.return_value = {"content": [self.landed_row(landed=40)], "page": {"totalPages": 1}}
		stats = {}
		with patch("tanesw_integration.containers._as_watcher") as aw:
			aw.return_value.__enter__.return_value = "Administrator"
			allocations._watch_landed(["Administrator"], stats)
		notify.assert_not_called()
		self.assertEqual(frappe.get_doc("TANeSW Vessel Allocation", TEST_MRN).landed_count, 40)
		self.assertEqual(frappe.db.get_single_value("TANeSW Settings", "landed_watch_initialized"), 1)

		# next run: 40 -> 46 landed is a real new landing
		xptd.return_value = {"content": [self.landed_row(landed=46, declared=10)], "page": {"totalPages": 1}}
		with patch("tanesw_integration.containers._as_watcher") as aw:
			aw.return_value.__enter__.return_value = "Administrator"
			allocations._watch_landed(["Administrator"], stats)
		notify.assert_called_once()
		doc = frappe.get_doc("TANeSW Vessel Allocation", TEST_MRN)
		self.assertEqual(
			(doc.landed_count, doc.available_count, doc.last_event), (46, 36, "Containers Landed")
		)
