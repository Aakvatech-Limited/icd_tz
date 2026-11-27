import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration.credentials import (
	assert_write_operations_enabled,
	build_token_cache_key,
	get_current_user_account,
)


class TestTANeSWCredentials(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# keep the real site's settings so they can be put back (tests run on the live site otherwise clobber them)
		cur = frappe.get_single("TANeSW Settings")
		fields = (
			"base_url",
			"environment",
			"enable_write_operations",
			"background_watcher_account",
			"background_watcher_fallback_account",
		)
		self._saved = {field: cur.get(field) for field in fields}
		frappe.db.delete("TANeSW User Account")
		settings = frappe.get_single("TANeSW Settings")
		settings.background_watcher_account = None
		settings.background_watcher_fallback_account = None
		settings.base_url = "https://tanesw.example.test/api"
		settings.environment = "Development"
		settings.enable_write_operations = 0
		settings.save(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()  # undo the deleted accounts / test settings
		for f, v in self._saved.items():
			frappe.db.set_single_value("TANeSW Settings", f, v)

	def make_user(self, email):
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "TANeSW Test User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		return email

	def make_account(self, user, enabled=1, company_code="WITZDL019", role_code="WI"):
		return frappe.get_doc(
			{
				"doctype": "TANeSW User Account",
				"user": user,
				"enabled": enabled,
				"tanesw_id": f"TRA-{user}",
				"tanesw_password": "test-secret",
				"company_tin": "100000000",
				"company_code": company_code,
				"company_type": "WI",
				"role_code": role_code,
			}
		).insert(ignore_permissions=True)

	def test_resolves_account_for_logged_in_user(self):
		user = self.make_user("tanesw-user@example.com")
		self.make_account(user)
		frappe.set_user(user)

		account = get_current_user_account()

		self.assertEqual(account.user, user)
		self.assertEqual(account.tanesw_id, f"TRA-{user}")

	def test_no_account_and_no_tanesw_role_is_rejected(self):
		# since the shared login, a user without their own account falls back to TANeSW Settings,
		# but only if they hold a TANeSW role
		user = self.make_user("missing-tanesw@example.com")
		frappe.set_user(user)

		with self.assertRaises(frappe.PermissionError):
			get_current_user_account()

	def test_disabled_account_without_tanesw_role_is_rejected(self):
		user = self.make_user("disabled-tanesw@example.com")
		self.make_account(user, enabled=0)
		frappe.set_user(user)

		with self.assertRaises(frappe.PermissionError):
			get_current_user_account()

	def test_resolver_never_accepts_another_user_argument(self):
		user = self.make_user("active-tanesw@example.com")
		other_user = self.make_user("other-tanesw@example.com")
		self.make_account(user)
		self.make_account(other_user)
		frappe.set_user(user)

		with self.assertRaises(TypeError):
			get_current_user_account(other_user)

	def test_token_cache_key_is_isolated_by_user_company_and_role(self):
		first = build_token_cache_key("one@example.com", "WITZDL019", "WI")
		second_user = build_token_cache_key("two@example.com", "WITZDL019", "WI")
		second_company = build_token_cache_key("one@example.com", "OTHER", "WI")
		second_role = build_token_cache_key("one@example.com", "WITZDL019", "APPROVER")

		self.assertEqual(len({first, second_user, second_company, second_role}), 4)
		self.assertNotIn("@", first)

	def test_write_operations_fail_closed_by_default(self):
		with self.assertRaises(frappe.ValidationError):
			assert_write_operations_enabled()
