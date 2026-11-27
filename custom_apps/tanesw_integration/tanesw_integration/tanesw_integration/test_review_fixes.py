"""PR #714 review fixes: safe defaults, POST-only endpoints, clean uninstall, codes from the settings."""

import importlib
import pathlib
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import best_pick_setup, credentials, icd_link, install, manifest_sync

APP = pathlib.Path(__file__).resolve().parents[1]


class TestReviewFixes(FrappeTestCase):
	def test_reception_check_only_warns_by_default(self):
		"""Review #15: ticking the check must not start changing Posting Dates."""
		self.assertEqual(
			frappe.get_meta("TANeSW Settings").get_field("reception_date_on_save").default, "Warn"
		)

	def test_every_endpoint_is_post_only(self):
		"""Review #26: no endpoint of this app answers a plain GET (opening a link cannot change anything)."""
		allowed = frappe.allowed_http_methods_for_whitelisted_func
		loose = []
		for path in APP.rglob("*.py"):
			if path.name.startswith("test_") or "@frappe.whitelist" not in path.read_text():
				continue
			dotted = ".".join(
				path.relative_to(APP.parent).with_suffix("").parts
			)  # the app's own files, found on disk
			module = importlib.import_module(dotted)  # nosemgrep: non-literal-import
			for name in dir(module):
				fn = getattr(module, name)
				if (
					callable(fn)
					and fn in frappe.whitelisted
					and getattr(fn, "__module__", "") == module.__name__
				):
					if allowed.get(fn) != ["POST"]:
						loose.append(f"{module.__name__}.{name}")
		self.assertEqual(loose, [])

	def test_icd_tz_is_a_declared_requirement(self):
		"""Review #7."""
		self.assertIn("icd_tz", frappe.get_hooks("required_apps", app_name="tanesw_integration"))

	def test_uninstall_puts_icd_tz_form_rules_back(self):
		"""Review #9: no Property Setter of ours survives an uninstall."""
		best_pick_setup.apply(True)
		manifest_sync.apply_setters(True)
		tags = (best_pick_setup.TAG, manifest_sync.TAG)
		self.assertTrue(frappe.get_all("Property Setter", filters={"default_value": ["in", tags]}))
		install.before_uninstall()
		self.assertFalse(frappe.get_all("Property Setter", filters={"default_value": ["in", tags]}))
		# the switches decide again what the site has
		if frappe.db.get_single_value("TANeSW Settings", "best_pick_without_manifest"):
			best_pick_setup.apply(True)
		if frappe.db.get_single_value("TANeSW Settings", "update_erp_manifests"):
			manifest_sync.apply_setters(True)

	def test_facility_code_comes_from_the_settings(self):
		"""Review #19, #22: our ICD code is a setting, with no other ICD's code built in."""
		old = frappe.db.get_single_value("TANeSW Settings", "login_warehouse_code")
		self.addCleanup(frappe.db.set_single_value, "TANeSW Settings", "login_warehouse_code", old)
		frappe.db.set_single_value("TANeSW Settings", "login_warehouse_code", " witzdl999 ")
		self.assertEqual(credentials.facility_code(), "WITZDL999")
		frappe.db.set_single_value("TANeSW Settings", "login_warehouse_code", "")
		self.assertEqual(credentials.facility_code(), "")
		self.assertFalse(frappe.get_meta("TANeSW Settings").get_field("login_warehouse_code").default)

	def test_receiving_needs_the_users_own_icd_tz_rights(self):
		"""Review #25: the app does not lend a TANeSW user rights on icd_tz they do not hold."""
		with patch.object(
			frappe, "has_permission", side_effect=lambda dt, ptype=None, *a, **k: dt != "Container Reception"
		):
			with self.assertRaises(frappe.PermissionError):
				icd_link.require_receiving_rights()
		with patch.object(frappe, "has_permission", return_value=True):
			icd_link.require_receiving_rights()

	def test_tanesw_operations_can_save_what_its_screens_save(self):
		for doctype in (
			"TANeSW Carry In",
			"TANeSW Carry Out",
			"TANeSW Declaration",
			"TANeSW Inspection Booking",
			"TANeSW Stripping Report",
			"TANeSW Transfer Allocation",
		):
			perm = next(
				(p for p in frappe.get_meta(doctype).permissions if p.role == "TANeSW Operations"), None
			)
			self.assertTrue(perm and perm.create and perm.write, doctype)

	def test_icd_tz_dimension_functions_are_still_there(self):
		"""Review #12: added boxes get their ICD Master BL / ICD Container from icd_tz's own functions. If icd_tz
		renames them the app falls back to its copy; this test fails so the change is seen and the app updated."""
		for fn in ("get_bl_consignees", "create_master_bls", "create_containers"):
			self.assertTrue(callable(frappe.get_attr(f"{manifest_sync.ICD_DIMENSIONS}.{fn}")), fn)
