import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from tanesw_integration.tanesw_integration.report.tanesw_receiving_by_manifest_and_bl import (
	tanesw_receiving_by_manifest_and_bl as rep,
)

TODAY = getdate("2026-11-12")


def box(cntr, status, received_on=None):
	return frappe._dict(container_no=cntr, status=status, received_on=received_on, mrn="26TST000001")


class TestReceivingByBL(FrappeTestCase):
	def test_complete_bl_starts_storage_at_its_last_box(self):
		r = rep._bl_row(
			"26TST000001",
			"BL1",
			[
				box("A", "Received at ICD", "2026-11-10 09:00:00"),
				box("B", "Received at ICD", "2026-11-11 15:30:00"),
			],
			False,
			{},
			TODAY,
		)
		self.assertEqual(r.bl_status, rep.COMPLETE)
		self.assertEqual(str(r.last_in), "2026-11-11 15:30:00")

	def test_partial_bl_has_no_storage_start_and_counts_days_open(self):
		r = rep._bl_row(
			"26TST000001",
			"BL1",
			[
				box("A", "Received at ICD", "2026-11-09 09:00:00"),
				box("B", "At Terminal"),
				box("C", "In Transit"),
			],
			False,
			{},
			TODAY,
		)
		self.assertEqual((r.bl_status, r.last_in, r.days_open), (rep.PARTIAL, None, 3))
		self.assertIn("2 box(es) still to come", r.check)

	def test_diverted_boxes_are_not_waited_for(self):
		r = rep._bl_row(
			"26TST000001",
			"BL1",
			[box("A", "Received at ICD", "2026-11-10 09:00:00"), box("B", "Diverted")],
			False,
			{},
			TODAY,
		)
		self.assertEqual(r.bl_status, rep.COMPLETE)

	def test_erp_storage_date_must_match_the_last_box(self):
		erp = {
			("26TST000001", "A"): {"received": 1, "received_date": getdate("2026-11-10")},
			("26TST000001", "B"): {"received": 1, "received_date": getdate("2026-11-10")},
		}
		r = rep._bl_row(
			"26TST000001",
			"BL1",
			[
				box("A", "Received at ICD", "2026-11-10 09:00:00"),
				box("B", "Received at ICD", "2026-11-11 15:30:00"),
			],
			True,
			erp,
			TODAY,
		)
		self.assertEqual(r.reception_gap, 0)
		self.assertIn("is not the last box's arrival", r.check)
