"""Endpoints that write TANeSW records without calling TANeSW are for TANeSW users only."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import api, cargo, icd_link, joint_inspection

NO_ROLE = "tanesw-norole@example.com"
CRI = "TSTSEC0000000001"


class TestRoleGuard(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("User", NO_ROLE):
			frappe.get_doc(
				{"doctype": "User", "email": NO_ROLE, "first_name": "No Role", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		self.addCleanup(self.cleanup)

	def cleanup(self):
		frappe.set_user("Administrator")
		frappe.db.delete("TANeSW Carry In", {"name": CRI})
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the test user and record must not outlive the test

	def test_user_without_tanesw_role_cannot_write_or_parse(self):
		frappe.set_user(NO_ROLE)
		with self.assertRaises(frappe.PermissionError):
			api.import_carry_in_record(CRI, data={"cntrNo": "TSTU0000001"})
		with self.assertRaises(frappe.PermissionError):
			api.import_declaration_from_tansad("TSTSEC-TANSAD")
		with self.assertRaises(frappe.PermissionError):
			cargo.export_xlsx("x", "[]", "[]")
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("TANeSW Carry In", CRI))

	def test_cached_lookups_and_test_mode_submit_need_a_tanesw_role(self):
		"""These answer from the cache (or simulate, in Test Mode) without calling TANeSW, so the TANeSW login's own
		role check never runs: each must check the role itself."""
		frappe.cache.set_value("tanesw:jnt:parties:v2", {"warehouses": {"X": "Y"}})
		frappe.cache.set_value("tanesw:cgm:prcd:TST", {"A": "B"})
		self.addCleanup(frappe.cache.delete_value, "tanesw:jnt:parties:v2")
		self.addCleanup(frappe.cache.delete_value, "tanesw:cgm:prcd:TST")
		frappe.set_user(NO_ROLE)
		for call in (
			lambda: joint_inspection.parties(),
			lambda: joint_inspection.codes("[]"),
			lambda: cargo.procedure_codes("TST"),
			lambda: cargo.cri_submit("{}"),
			lambda: icd_link.carry_in_context(),
			lambda: api.sync_declaration("TSTSEC-TANSAD"),
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_tanesw_user_still_can(self):
		frappe.set_user("Administrator")
		self.assertEqual(api.import_carry_in_record(CRI, data={"cntrNo": "TSTU0000001"})["status"], "ok")
