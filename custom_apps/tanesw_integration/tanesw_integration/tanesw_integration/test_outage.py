"""TANeSW outage pause (outage.py): pauses background work, resumes on its own, never blocks a user's click."""

import time
from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import api_client as tc
from tanesw_integration import outage


class TestOutagePause(FrappeTestCase):
	def setUp(self):
		outage.resume()
		self.addCleanup(outage.resume)
		self.settings = frappe._dict(base_url="https://tanesw.test", request_timeout=1, verify_tls=1)

	def session(self, get=None):
		s = MagicMock()
		s.get.side_effect = get
		s.headers = {}
		return s

	def outage_logs(self):
		return frappe.db.count("Error Log", {"method": ["like", "TANeSW not responding%"]})

	def test_timeout_pauses_and_logs_once(self):
		before = self.outage_logs()
		s = self.session(requests.exceptions.ReadTimeout("slow"))
		with (
			patch.object(tc, "authenticate", return_value="T"),
			patch.object(tc, "_get_session", return_value=(s, self.settings)),
		):
			with self.assertRaises(outage.TANeSWUnreachable):
				tc._authed_get("/x")
			self.assertTrue(outage.paused())
			# a second background call makes no network call at all
			with self.assertRaises(outage.TANeSWPaused):
				tc._authed_get("/y")
		self.assertEqual(s.get.call_count, 2)  # the first call and its one retry, nothing after
		self.assertEqual(self.outage_logs(), before + 1)
		outage.pause("again")  # extending the pause logs nothing new
		self.assertEqual(self.outage_logs(), before + 1)

	def test_pause_lifts_on_its_own(self):
		with patch.object(outage, "PAUSE_MINUTES", 1 / 60):  # one second
			outage.pause("test")
			self.assertTrue(outage.paused())
			time.sleep(2.2)
			self.assertFalse(outage.paused())

	def test_a_users_click_still_tries_and_clears_the_pause(self):
		outage.pause("test")
		ok = MagicMock(status_code=200)
		ok.json.return_value = {"ok": 1}
		s = self.session([ok])
		frappe.local.request = object()  # inside a web request = a user's action
		try:
			with (
				patch.object(tc, "authenticate", return_value="T"),
				patch.object(tc, "_get_session", return_value=(s, self.settings)),
			):
				self.assertEqual(tc._authed_get("/x"), {"ok": 1})
		finally:
			del frappe.local.request
		self.assertFalse(outage.paused())

	def test_job_errors_are_silent_during_an_outage(self):
		before = frappe.db.count("Error Log")
		try:
			raise outage.TANeSWPaused("paused")
		except Exception:
			outage.log_error(title="TANeSW container sync failed: TEST")
		self.assertEqual(frappe.db.count("Error Log"), before)

	def test_jobs_are_not_queued_while_paused(self):
		from tanesw_integration import allocations, containers, icd_link, manifest_sync

		outage.pause("test")
		with patch.object(frappe, "enqueue") as enq:
			allocations.enqueue_allocation_watch()
			containers.enqueue_container_sync()
			icd_link.enqueue_icd_link()
			manifest_sync.enqueue_manifest_sync()
		enq.assert_not_called()
