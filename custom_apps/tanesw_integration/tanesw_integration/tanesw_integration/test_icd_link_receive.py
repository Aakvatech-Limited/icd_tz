from unittest.mock import patch

import frappe

from tanesw_integration import icd_link
from tanesw_integration.tanesw_integration import test_icd_link as base

LOC = "TEST-ICDLINK-BLOCK"


class TestReceiveFromCarryIn(base.TestIcdLink):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("Container Location", LOC):
			loc = frappe.get_doc({"doctype": "Container Location", "name": LOC, "location_name": LOC})
			loc.flags.ignore_mandatory = True
			loc.insert(ignore_permissions=True, set_name=LOC)
		self.clerk = frappe.db.get_value("Employee", {"first_name": "TEST ICDLINK CLERK"})
		if not self.clerk:
			e = frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "TEST ICDLINK CLERK",
					"company": self.company,
					"status": "Active",
				}
			)
			e.flags.ignore_mandatory = True
			self.clerk = e.insert(ignore_permissions=True).name

	def tearDown(self):
		for cid in frappe.get_all("Container", filters={"manifest": base.MF}, pluck="name"):
			frappe.db.delete("Container Service Detail", {"parent": cid})
			frappe.db.delete("Container", {"name": cid})
		super().tearDown()

	def given_at_gate(self, name, location=LOC):
		frappe.db.set_value(
			"TANeSW Carry In Container",
			name,
			{"clerk": self.clerk, "container_location": location, "received_at_gate": 1},
		)

	def test_details_from_the_carry_in_screen_submit_the_reception(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(
			base.truck_row(entry="N")
		)  # TANeSW has not confirmed entry yet: our screen says it arrived
		self.given_at_gate(name)
		status = icd_link.process_link(name)
		msg = frappe.db.get_value("TANeSW Carry In Container", name, "link_message")
		self.assertEqual(status, icd_link.SUBMITTED, msg)
		rec = frappe.get_doc(
			"Container Reception",
			frappe.db.get_value("TANeSW Carry In Container", name, "container_reception"),
		)
		self.assertEqual((rec.docstatus, rec.container_location, rec.clerk), (1, LOC, self.clerk))
		self.assertTrue(
			frappe.db.exists("Container", {"container_reception": rec.name})
		)  # icd_tz made the Container

	def test_a_waiting_draft_is_submitted_once_details_arrive(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(base.truck_row(entry="Y"))
		self.assertEqual(icd_link.process_link(name), icd_link.DRAFTED)  # portal carry-in: no details yet
		self.given_at_gate(name)
		self.assertEqual(icd_link.process_link(name), icd_link.SUBMITTED)
		self.assertEqual(frappe.db.count("Container Reception", {"manifest": base.MF}), 1)

	def test_submit_refused_by_icd_tz_stays_a_draft_with_the_reason(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(base.truck_row(entry="Y"))
		self.given_at_gate(name)
		with patch(
			"icd_tz.icd_tz.doctype.container_reception.container_reception.ContainerReception.before_submit",
			side_effect=frappe.ValidationError("Clerk is missing"),
		):
			self.assertEqual(icd_link.process_link(name), icd_link.DRAFTED)
		self.assertIn(
			"could not submit: Clerk is missing",
			frappe.db.get_value("TANeSW Carry In Container", name, "link_message"),
		)
		rec = frappe.db.get_value("TANeSW Carry In Container", name, "container_reception")
		self.assertEqual(frappe.db.get_value("Container Reception", rec, "docstatus"), 0)

	def test_receive_carry_in_uses_per_container_location(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		old = frappe.db.get_single_value("TANeSW Settings", "enable_icd_link")
		detail = {"mrn": base.MRN, "wrhsCriVhclList": [base.truck_row(entry="N")]}
		try:
			frappe.db.set_single_value("TANeSW Settings", "enable_icd_link", 1)
			with (
				patch.object(icd_link, "_report_detail", return_value=detail),
				patch("tanesw_integration.containers._facility_code", return_value="WITZDL019"),
			):
				out = icd_link.receive_carry_in(
					base.REPORT["crn"],
					base.REPORT["criBaseNo"],
					{"clerk": self.clerk, "default_location": "NOT-USED", "locations": {base.CNTR: LOC}},
				)
		finally:
			frappe.db.set_single_value("TANeSW Settings", "enable_icd_link", old or 0)
		self.assertEqual(
			[(o["container_no"], o["status"]) for o in out], [(base.CNTR, icd_link.SUBMITTED)], out
		)
		self.assertEqual(
			frappe.db.get_value("Container Reception", out[0]["container_reception"], "container_location"),
			LOC,
		)

	# ---- screen only (setting off, the default): a portal carry-in fills the order, then waits for our screen
	def screen_only(self):
		frappe.db.set_single_value(
			"TANeSW Settings", "draft_portal_receptions", 0
		)  # base tearDown restores it

	def test_screen_only_portal_carry_in_waits_without_a_draft(self):
		self.screen_only()
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(base.truck_row(entry="Y"))  # TANeSW: entered our gate, carried in through the portal
		self.assertEqual(icd_link.process_link(name), icd_link.AWAITING)
		self.assertEqual(
			frappe.db.get_value("TANeSW Carry In Container", name, "movement_order"), "TEST-ICDLINK-CMO-1"
		)
		self.assertEqual(frappe.db.count("Container Reception", {"manifest": base.MF}), 0)

	def test_screen_only_receive_into_erp_on_a_reported_carry_in_submits_it(self):
		self.screen_only()
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(base.truck_row(entry="Y"))
		icd_link.process_link(name)
		old = frappe.db.get_single_value("TANeSW Settings", "enable_icd_link")
		detail = {"mrn": base.MRN, "wrhsCriVhclList": [base.truck_row(entry="Y")]}
		try:
			frappe.db.set_single_value("TANeSW Settings", "enable_icd_link", 1)
			with (
				patch.object(icd_link, "_report_detail", return_value=detail),
				patch("tanesw_integration.containers._facility_code", return_value="WITZDL019"),
				patch("tanesw_integration.cargo._post") as post,
			):
				out = icd_link.receive_reported(
					base.REPORT["crn"],
					base.REPORT["criBaseNo"],
					{"clerk": self.clerk, "default_location": LOC},
				)
				post.assert_not_called()  # nothing goes to TANeSW
		finally:
			frappe.db.set_single_value("TANeSW Settings", "enable_icd_link", old or 0)
		self.assertEqual(
			[(o["container_no"], o["status"]) for o in out], [(base.CNTR, icd_link.SUBMITTED)], out
		)
		self.assertEqual(frappe.db.count("Container Reception", {"manifest": base.MF, "docstatus": 1}), 1)

	def test_screen_only_receive_into_erp_needs_a_clerk(self):
		self.screen_only()
		with self.assertRaises(frappe.ValidationError):
			icd_link.receive_reported("C", "B", {"default_location": LOC})
