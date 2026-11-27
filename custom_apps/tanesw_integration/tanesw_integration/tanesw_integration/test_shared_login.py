"""One TANeSW login on TANeSW Settings for every user with a TANeSW role (no personal credentials needed)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import credentials as cr
from tanesw_integration.session_utils import as_user

ROLE_USER = "test-tanesw-role@example.com"
NO_ROLE_USER = "test-tanesw-norole@example.com"


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		)
		u.insert(ignore_permissions=True)
		u.add_roles(*roles)


class TestSharedLogin(FrappeTestCase):
	def setUp(self):
		make_user(ROLE_USER, ["TANeSW User"])
		make_user(NO_ROLE_USER, ["Blogger"])
		s = frappe.get_single("TANeSW Settings")
		self.before = (s.get("login_tanesw_id"), s.get_password("login_password", raise_exception=False))
		s.login_tanesw_id = "SHARED.ID"
		s.login_password = "secret-pass"
		s.login_company_code = "WITZDL019"
		s.save(ignore_permissions=True)
		self.addCleanup(self.restore)

	def restore(self):
		s = frappe.get_single("TANeSW Settings")
		s.login_tanesw_id, s.login_password = self.before[0], self.before[1]
		s.save(ignore_permissions=True)

	def test_a_user_with_the_role_uses_the_shared_login(self):
		with as_user(ROLE_USER):
			acc = cr.get_current_user_account()
		self.assertIsInstance(acc, cr.SharedAccount)
		self.assertEqual(acc.tanesw_id, "SHARED.ID")
		self.assertEqual(acc.get_password("tanesw_password"), "secret-pass")
		self.assertEqual(acc.user, cr.SHARED_USER)  # one token cache for everybody

	def test_a_user_without_the_role_is_refused(self):
		with as_user(NO_ROLE_USER), self.assertRaises(frappe.PermissionError):
			cr.get_current_user_account()

	def test_a_personal_account_still_wins(self):
		acc = frappe.get_doc(
			{
				"doctype": "TANeSW User Account",
				"user": ROLE_USER,
				"enabled": 1,
				"tanesw_id": "OWN.ID",
				"tanesw_password": "own",
				"company_tin": "000000000",
				"company_code": "WITZDL019",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "TANeSW User Account", acc.name, force=True)
		with as_user(ROLE_USER):
			self.assertEqual(cr.get_current_user_account().tanesw_id, "OWN.ID")

	def test_login_status_is_written_to_settings(self):
		cr.SharedAccount().db_set("last_connection_status", "Successful")
		self.assertEqual(frappe.db.get_single_value("TANeSW Settings", "login_status"), "Successful")

	def test_background_jobs_fall_back_to_the_shared_login(self):
		s = frappe._dict(background_watcher_account=None, background_watcher_fallback_account=None)
		with patch.object(cr, "shared_login_configured", return_value=True):
			self.assertEqual(cr.watcher_accounts(s), [cr.SHARED])
		s.background_watcher_account = "SOME-ACCOUNT"
		self.assertEqual(cr.watcher_accounts(s), ["SOME-ACCOUNT"])

	def test_not_configured_says_where_to_set_it(self):
		s = frappe.get_single("TANeSW Settings")
		s.login_tanesw_id = ""
		s.save(ignore_permissions=True)
		with as_user(ROLE_USER), self.assertRaises(frappe.ValidationError) as e:
			cr.get_current_user_account()
		self.assertIn("TANeSW Settings", str(e.exception))
