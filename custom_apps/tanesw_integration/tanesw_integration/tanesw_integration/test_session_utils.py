import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration.session_utils import as_user


class TestAsUser(FrappeTestCase):
	def setUp(self):
		self.original = frappe.local.session
		self.original_form = frappe.local.form_dict
		# what a browser request looks like: a real sid and a CSRF token in session.data
		frappe.local.session = frappe._dict(
			user="Administrator",
			sid="browser-sid-123",
			data=frappe._dict(csrf_token="tok-456", user_type="System User"),
		)
		frappe.local.form_dict = frappe._dict(cmd="frappe.desk.query_report.run", report_name="X")

	def tearDown(self):
		frappe.local.session = self.original
		frappe.local.form_dict = self.original_form
		frappe.set_user("Administrator")

	def test_session_is_put_back_exactly(self):
		session = frappe.local.session
		with as_user("Guest"):
			self.assertEqual(frappe.session.user, "Guest")
		self.assertIs(frappe.local.session, session)  # same object the request handler will save
		self.assertEqual(
			(session.user, session.sid, session.data.csrf_token),
			("Administrator", "browser-sid-123", "tok-456"),
		)
		self.assertEqual(frappe.local.form_dict.report_name, "X")

	def test_restored_even_when_the_block_fails(self):
		with self.assertRaises(ZeroDivisionError):
			with as_user("Guest"):
				1 / 0
		self.assertEqual((frappe.session.user, frappe.session.sid), ("Administrator", "browser-sid-123"))

	def test_plain_set_user_would_have_broken_it(self):
		# documents the bug this guards against
		frappe.set_user("Guest")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.session.sid, "Administrator")
		self.assertNotIn("csrf_token", frappe.session.data)

	def test_watcher_switch_in_a_request_keeps_the_login(self):
		from tanesw_integration.containers import _as_watcher

		name = "TEST-SESSION-WATCHER"
		if not frappe.db.exists("TANeSW User Account", name):
			acc = frappe.get_doc(
				{"doctype": "TANeSW User Account", "name": name, "user": "Guest", "enabled": 1}
			)
			acc.flags.ignore_mandatory = True
			acc.flags.ignore_links = True
			acc.db_insert()
		try:
			with _as_watcher([name]) as chosen:
				self.assertEqual((chosen, frappe.session.user), (name, "Guest"))
			self.assertEqual(
				(frappe.session.sid, frappe.session.data.csrf_token), ("browser-sid-123", "tok-456")
			)
			with _as_watcher(["NO-SUCH-ACCOUNT"]) as chosen:
				self.assertIsNone(chosen)
			self.assertEqual(frappe.session.user, "Administrator")
		finally:
			frappe.db.delete("TANeSW User Account", {"name": name})
