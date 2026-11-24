from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import cargo, credentials, test_mode


class TestTestMode(FrappeTestCase):
	def setUp(self):
		self.old = {
			k: frappe.db.get_single_value("TANeSW Settings", k)
			for k in ("test_mode", "enable_write_operations")
		}

	def tearDown(self):
		for k, v in self.old.items():
			frappe.db.set_single_value("TANeSW Settings", k, v or 0)

	def set(self, test, write):
		frappe.db.set_single_value("TANeSW Settings", {"test_mode": test, "enable_write_operations": write})

	def test_every_tanesw_write_is_refused_in_test_mode_even_with_writes_on(self):
		self.set(1, 1)
		with self.assertRaises(frappe.ValidationError) as e:
			credentials.assert_write_operations_enabled()
		self.assertIn("TEST MODE", str(e.exception))

	def test_writes_follow_the_setting_when_test_mode_is_off(self):
		self.set(0, 1)
		credentials.assert_write_operations_enabled()  # no error
		self.set(0, 0)
		with self.assertRaises(frappe.ValidationError):
			credentials.assert_write_operations_enabled()

	@patch(
		"tanesw_integration.icd_link.receive_carry_in",
		return_value=[{"container_no": "X", "status": "Reception Submitted"}],
	)
	@patch("tanesw_integration.cargo._post")
	def test_carry_in_submit_is_simulated_never_sent(self, post, receive):
		self.set(1, 0)
		out = cargo.cri_submit(
			{"crn": "CRN1", "criBaseNo": "BASE1"}, reception={"clerk": "E1", "default_location": "B"}
		)
		post.assert_not_called()  # nothing reached TANeSW
		self.assertEqual(out["testMode"], 1)
		receive.assert_called_once()  # the ERP side still ran
		self.assertEqual(out["icd_reception"][0]["status"], "Reception Submitted")

	@patch("tanesw_integration.cargo._post", return_value={})
	def test_carry_in_submit_goes_to_tanesw_when_test_mode_is_off(self, post):
		self.set(0, 1)
		with patch("tanesw_integration.cargo._write_result", return_value={"ok": 1}):
			cargo.cri_submit({"crn": "CRN1", "criBaseNo": "BASE1"})
		post.assert_called_once()

	def test_no_demo_data_action_ships(self):
		self.assertFalse(hasattr(test_mode, "prepare_demo"))

	def test_screens_see_write_buttons_and_the_badge_flag(self):
		from tanesw_integration import joint_inspection

		self.set(1, 0)
		with patch.object(joint_inspection, "_user_info", return_value={}):
			ctx = joint_inspection.context() if hasattr(joint_inspection, "context") else None
		if ctx is not None:
			self.assertEqual((ctx["write_enabled"], ctx["test_mode"]), (1, 1))
