"""TANeSW not answering: plain messages, one login retry, no lock-out, writes never retried."""

from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import api_client as tc


class FakeAccount(frappe._dict):
	def get_password(self, *a, **kw):
		return "pw"

	def db_set(self, field, value):
		self[field] = value


def account():
	return FakeAccount(
		name="ACC-TIMEOUT",
		user="timeout@test",
		company_code="C1",
		role_code="R1",
		tanesw_id="TEST.USER",
		company_tin="1",
		company_type="T",
	)


class TestTimeouts(FrappeTestCase):
	def setUp(self):
		from tanesw_integration import outage

		outage.resume()  # a login timeout below starts the outage pause (outage.py); never leak it
		self.addCleanup(outage.resume)
		self.settings = frappe._dict(
			base_url="https://tanesw.test", request_timeout=1, verify_tls=1, token_cache_duration=60
		)

	def session(self, post):
		s = MagicMock()
		s.post.side_effect = post
		s.headers = {}
		return s

	def test_login_timeout_retries_once_then_plain_message(self):
		acc = account()
		s = self.session(requests.exceptions.ReadTimeout("read timed out"))
		with (
			patch.object(tc, "_get_session", return_value=(s, self.settings)),
			patch.object(tc, "_cached_token", return_value=None),
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				tc.authenticate(acc)
		self.assertEqual(s.post.call_count, 2)
		self.assertIn("did not respond in time", str(ctx.exception))
		self.assertEqual(acc.last_connection_status, "Failed")
		# TRA being slow must not lock the user out the way a wrong password does
		key = tc.build_token_cache_key(acc.user, acc.company_code, acc.role_code)
		self.assertFalse(frappe.cache.get_value(f"{key}:login-failed"))

	def test_login_recovers_when_the_retry_answers(self):
		acc = account()
		ok1 = MagicMock(status_code=200)
		ok2 = MagicMock(status_code=200, headers={"Authorization": "Bearer TKN"})
		s = self.session([requests.exceptions.ConnectTimeout("slow"), ok1, ok2])
		with (
			patch.object(tc, "_get_session", return_value=(s, self.settings)),
			patch.object(tc, "_cached_token", return_value=None),
			patch.object(tc, "_cache_token"),
		):
			self.assertEqual(tc.authenticate(acc), "TKN")
		self.assertEqual(s.post.call_count, 3)

	def test_write_timeout_is_not_retried_and_says_check_tanesw(self):
		s = self.session(requests.exceptions.ReadTimeout("read timed out"))
		with (
			patch.object(tc, "assert_write_operations_enabled"),
			patch.object(tc, "authenticate", return_value="T"),
			patch.object(tc, "_get_session", return_value=(s, self.settings)),
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				tc._authed_post("/x", {"a": 1}, is_write=True)
		self.assertEqual(s.post.call_count, 1)
		self.assertIn("may or may not have recorded", str(ctx.exception))
