"""Container pipeline stages and the port-charge check (no TANeSW calls)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from tanesw_integration import port_charge_check as pc
from tanesw_integration.tanesw_integration.report.tanesw_container_pipeline import (
	tanesw_container_pipeline as pl,
)

MRN = "TEST26PIPE01"


def box(**kw):
	b = frappe._dict(
		{
			"status": "At Terminal",
			"discharged_on": None,
			"declared_on": None,
			"gate_out_on": None,
			"received_on": None,
			"removed_from_allocation_on": None,
			"erp_order": False,
			"erp_reception": False,
		}
	)
	b.update(kw)
	return b


def hours_ago(h):
	return add_to_date(now_datetime(), hours=-h)


class TestPipelineStages(FrappeTestCase):
	def stage(self, **kw):
		b = box(**kw)
		b.stage, b.since, b.age_hours = pl.stage_of(b, now_datetime())
		return b

	def test_each_stage(self):
		self.assertEqual(self.stage(status="Not Discharged").stage, pl.NOT_LANDED)
		self.assertEqual(self.stage(discharged_on=hours_ago(30)).stage, pl.TO_DECLARE)
		self.assertEqual(self.stage(discharged_on=hours_ago(30), declared_on=hours_ago(5)).stage, pl.WAITING)
		self.assertEqual(
			self.stage(status="In Transit", gate_out_on=hours_ago(2), declared_on=hours_ago(5)).stage,
			pl.ON_ROAD,
		)
		self.assertEqual(self.stage(status="Received at ICD", received_on=hours_ago(1)).stage, pl.RECEIVED)
		self.assertEqual(self.stage(status="Diverted").stage, pl.LEFT)
		self.assertEqual(
			self.stage(removed_from_allocation_on=hours_ago(1), discharged_on=hours_ago(9)).stage, pl.LEFT
		)

	def test_flags(self):
		past = self.stage(discharged_on=hours_ago(8 * 24))
		self.assertIn("free days", pl.flag_of(past, 7))
		near = self.stage(discharged_on=hours_ago(6 * 24))
		self.assertIn("free day(s) left", pl.flag_of(near, 7))
		waiting = self.stage(declared_on=hours_ago(30), discharged_on=hours_ago(40))
		self.assertIn("no truck", pl.flag_of(waiting, 7))
		road = self.stage(status="In Transit", gate_out_on=hours_ago(20))
		self.assertIn("not at our gate", pl.flag_of(road, 7))
		got = self.stage(status="Received at ICD", received_on=hours_ago(2))
		self.assertIn("no Container Reception", pl.flag_of(got, 7))
		got.erp_reception = True
		self.assertIsNone(pl.flag_of(got, 7))

	def test_report_runs(self):
		cols, data, _m, _c, cards = pl.execute({"from_date": "2026-10-01", "to_date": "2026-12-31"})[:5]
		self.assertTrue(cols)
		self.assertEqual(len(cards), 8)


class TestPortChargeCheck(FrappeTestCase):
	def setUp(self):
		frappe.db.delete("TANeSW Allocation Change", {"mrn": MRN})
		self.addCleanup(frappe.db.delete, "TANeSW Allocation Change", {"mrn": MRN})
		log = frappe.get_doc(
			{
				"doctype": "TANeSW Allocation Change",
				"mrn": MRN,
				"container_no": "GONE0000001",
				"change_type": "Removed",
				"outcome": "Diverted to another ICD",
				"new_place": "GALCO LIMITED",
				"detected_on": now_datetime(),
			}
		)
		log.flags.ignore_links = True
		log.insert(ignore_permissions=True)
		self.lines = [(1, "TEST-MF", "GONE0000001"), (2, "TEST-MF", "OURS0000001")]
		for p in (
			patch.object(pc, "container_lines", return_value=self.lines),
			patch.object(frappe.db, "get_value", side_effect=self.get_value),
			patch.object(pc, "refresh"),
			patch.object(pc, "queue_refresh"),
			patch.object(pc, "stale_manifests", return_value={"TEST-MF"}),
		):
			p.start()
			self.addCleanup(p.stop)

	real_get_value = staticmethod(frappe.db.get_value)

	def get_value(self, doctype, *args, **kw):
		if doctype == "Manifest":
			return MRN
		return TestPortChargeCheck.real_get_value(doctype, *args, **kw)

	def settings(self, mode):
		s = frappe._dict({"check_port_charges": 1, "port_charge_check_mode": mode, "enable_manifest_sync": 1})
		return patch("frappe.get_single", return_value=s)

	def test_only_the_gone_box_is_reported(self):
		self.assertEqual(pc.not_ours(self.lines), [(1, "GONE0000001", "GALCO LIMITED")])

	def test_submit_is_blocked(self):
		with self.settings("Block"), self.assertRaises(frappe.ValidationError):
			pc.check_document(frappe._dict(items=[]), "before_submit")
		pc.refresh.assert_not_called()  # review #17: a submit never waits on TANeSW
		pc.queue_refresh.assert_not_called()

	def test_precheck_lists_gone_boxes_that_are_chargeable_here(self):
		real = TestPortChargeCheck.real_get_value

		def gv(doctype, *args, **kw):
			if doctype == "Manifest":
				return MRN
			if doctype == "ICD Container":
				return frappe._dict(name="GONE0000001:TEST", purchase_order=None)
			return real(doctype, *args, **kw)

		frappe.db.get_value.side_effect = gv
		with self.settings("Block"), patch.object(frappe, "has_permission", return_value=True):
			res = pc.precheck("TEST-MF")
		self.assertEqual([g["container_no"] for g in res["gone"]], ["GONE0000001"])
		self.assertEqual(res["gone"][0]["went_to"], "GALCO LIMITED")
		self.assertTrue(res["blocking"])

	def test_warn_mode_and_save_only_warn(self):
		with self.settings("Warn"):
			pc.check_document(frappe._dict(items=[]), "before_submit")
		with self.settings("Block"):
			pc.check_document(frappe._dict(items=[]), "validate")
		pc.refresh.assert_not_called()  # nothing calls TANeSW while the user waits
		pc.queue_refresh.assert_called_once_with({"TEST-MF"})  # the save queues a background re-read
