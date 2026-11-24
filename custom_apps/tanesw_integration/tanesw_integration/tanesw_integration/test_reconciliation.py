import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration.tanesw_integration.report.tanesw_icd_reconciliation import (
	tanesw_icd_reconciliation as rpt,
)

MRN, MF = "26TST000902", "TEST-RECON-MF"
BL, OTHER_PLACE_BL = "RECONBL1", "RECONBL2"


class TestIcdReconciliation(FrappeTestCase):
	def setUp(self):
		self.cleanup()
		va = frappe.get_doc(
			{
				"doctype": "TANeSW Vessel Allocation",
				"mrn": MRN,
				"vessel_name": "RECON VESSEL",
				"arrival_date": "2026-11-05",
				"container_count": 6,
				"landed_count": 5,
				"declared_count": 4,
			}
		)
		va.flags.ignore_mandatory = True
		va.insert(ignore_permissions=True)
		# 6 allocated: 1 not landed, 1 at port, 1 in transit, 2 received, 1 diverted
		for i, status in enumerate(
			["Not Discharged", "At Terminal", "In Transit", "Received at ICD", "Received at ICD", "Diverted"]
		):
			c = frappe.new_doc("TANeSW Container")
			c.update({"container_no": f"RCNU000000{i}", "mrn": MRN, "status": status})
			c.flags.ignore_links = True
			c.insert(ignore_permissions=True)
		if "icd_tz" in frappe.get_installed_apps():
			mf = frappe.get_doc(
				{
					"doctype": "Manifest",
					"name": MF,
					"mrn": MRN,
					"docstatus": 1,
					"containers": [{"m_bl_no": BL, "container_no": f"RCNU000000{i}"} for i in range(5)]
					+ [{"m_bl_no": OTHER_PLACE_BL, "container_no": "RCNU9999999"}],
					"master_bl": [
						{"m_bl_no": BL, "place_of_delivery": "WITZDL019"},
						{"m_bl_no": OTHER_PLACE_BL, "place_of_delivery": "WITZDL034"},
					],
				}
			)
			mf.db_insert()
			for child in mf.get_all_children():
				child.db_insert()
			for i, docstatus in ((3, 1), (4, 0)):  # one submitted reception, one still a draft
				r = frappe.get_doc(
					{
						"doctype": "Container Reception",
						"name": f"TEST-RECON-CR-{i}",
						"manifest": MF,
						"container_no": f"RCNU000000{i}",
						"docstatus": docstatus,
					}
				)
				r.db_insert()

	def tearDown(self):
		self.cleanup()

	def cleanup(self):
		frappe.db.delete("TANeSW Container", {"mrn": MRN})
		frappe.db.delete("TANeSW Vessel Allocation", {"mrn": MRN})
		if "icd_tz" in frappe.get_installed_apps():
			frappe.db.delete("Container Reception", {"manifest": MF})
			for t in ("Containers Detail", "Master BL"):
				frappe.db.delete(t, {"parent": MF})
			frappe.db.delete("Manifest", {"name": MF})

	def test_tanesw_side_balances(self):
		_cols, data, message, _chart, cards = rpt.execute(
			{"from_date": "2026-11-01", "to_date": "2026-11-10", "mrn": MRN}
		)
		r = data[0]
		self.assertEqual(
			(r.allocated, r.at_port, r.in_transit, r.received, r.diverted, r.tracked), (6, 1, 1, 2, 1, 6)
		)
		self.assertEqual(
			r.balances, "Yes"
		)  # 1 at port + 1 not landed + 1 in transit + 2 received + 1 diverted
		self.assertIsNone(message)  # no top note on the report
		self.assertEqual(next(c for c in cards if c["label"] == "Diverted to Other ICD")["value"], 1)

	def test_erp_side_and_gaps(self):
		if "icd_tz" not in frappe.get_installed_apps():
			self.skipTest("icd_tz is not installed on this site")
		r = rpt.execute({"from_date": "2026-11-01", "to_date": "2026-11-10", "mrn": MRN})[1][0]
		self.assertEqual(r.manifest, MF)
		self.assertEqual(r.on_manifest, 5)  # the B/L delivered to another ICD is not ours
		self.assertEqual(r.allocation_gap, 1)
		self.assertEqual((r.received_erp, r.draft_receptions), (1, 1))
		self.assertEqual(r.reception_gap, 1)  # TANeSW shows 2 received, ERP has 1 submitted
		self.assertIn("1 allocated not on the Manifest", r.check)
		self.assertIn("1 received on TANeSW without a submitted reception", r.check)

	def test_vessel_without_manifest_is_flagged(self):
		if "icd_tz" not in frappe.get_installed_apps():
			self.skipTest("icd_tz is not installed on this site")
		frappe.db.set_value("Manifest", MF, "mrn", "SOMETHING-ELSE")
		r = rpt.execute({"from_date": "2026-11-01", "to_date": "2026-11-10", "mrn": MRN})[1][0]
		self.assertEqual(r.check, "No submitted Manifest in ERP for this MRN")
