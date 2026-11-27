from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import icd_link

MRN = "26TST000901"
MF = "TEST-ICDLINK-MF"
TRUCK, TRAILER, TRANSPORTER = "T945DXL", "T268DYR", "TEST ICDLINK TRANSPORTER"
CNTR, OTHER_CNTR = "TSTU2663494", "TSTU2663495"
BL, OTHER_BL = "TESTBL0001", "TESTBL0002"
REPORT = {
	"crn": "26TST0009010000000",
	"criBaseNo": "WTTZDL0082026H9990001",
	"mrn": MRN,
	"wrhsCd": "WITZDL019",
}


def truck_row(entry="N", dclr="WITZDL0192026I9990001", truck="T 945 DXL", info=f"{CNTR} (22G0, HB524896)"):
	return {
		"dclrNo": dclr,
		"crn": REPORT["crn"],
		"vhclNo": truck,
		"trlrNo": "T268DYR",
		"drvrNm": "TEST DRIVER",
		"drvrLcneNo": "4005395198",
		"prcssStatCd": "D06",
		"prcssDtm": "2026-11-02 21:06:06",
		"gateExitCfrmYn": "Y",
		"entryCfrmYn": entry,
		"cntrInfo": info,
	}


class TestParsing(FrappeTestCase):
	def test_container_info_with_one_or_several_boxes(self):
		self.assertEqual(
			icd_link.parse_cntr_info("BMOU2663494 (22G0, HB524896)"),
			[("BMOU2663494", {"size": "22G0", "seal": "HB524896"})],
		)
		self.assertEqual(
			[c for c, _ in icd_link.parse_cntr_info("MSKU1234567 (45G1, X1), TGHU7654321 (22G1)")],
			["MSKU1234567", "TGHU7654321"],
		)
		self.assertEqual(icd_link.parse_cntr_info("TGHU7654321 (22G1)")[0][1], {"size": "22G1", "seal": None})
		self.assertEqual(icd_link.parse_cntr_info(None), [])

	def test_plates_compare_without_spaces_or_case(self):
		self.assertEqual(icd_link.norm_plate(" t 945-dxl "), "T945DXL")
		self.assertIsNone(icd_link.norm_plate(""))


class TestIcdLink(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not icd_link.icd_tz_installed():
			raise cls.skipTest(cls, "icd_tz is not installed on this site")
		cls.company = frappe.db.get_value("Company", {}, "name")
		if not cls.company:
			raise cls.skipTest(cls, "no Company on this site")

	def setUp(self):
		self.old_draft_portal = frappe.db.get_single_value("TANeSW Settings", "draft_portal_receptions")
		frappe.db.set_single_value("TANeSW Settings", "draft_portal_receptions", 1)
		self.cleanup()
		self.made_setting = False
		if not frappe.db.exists("ICD Setting", {"company": self.company}):
			# typical storage bands: icd_tz only accepts these places of destination
			bands = [
				("Local", 1, 7, "Free"),
				("Local", 8, 14, "Single"),
				("Local", 15, 9999999, "Double"),
				("DRC", 1, 30, "Free"),
				("DRC", 31, 37, "Single"),
				("DRC", 38, 9999999, "Double"),
				("Other", 1, 15, "Free"),
				("Other", 16, 22, "Single"),
				("Other", 23, 9999999, "Double"),
			]
			s = frappe.get_doc(
				{
					"doctype": "ICD Setting",
					"company": self.company,
					"received_date_threshold_hours": 24,
					"storage_days": [
						{"destination": d, "from": a, "to": b, "charge": c} for d, a, b, c in bands
					],
				}
			)
			s.flags.ignore_mandatory = True
			s.insert(ignore_permissions=True)
			self.made_setting = True
		# an existing setting without storage bands (a bare dev site): add typical ones, removed again in tearDown
		self.added_bands = []
		setting = frappe.db.get_value("ICD Setting", {"company": self.company})
		if not frappe.db.exists("ICD TZ Settings Detail", {"parent": setting, "parenttype": "ICD Setting"}):
			for i, (d, a, b, c) in enumerate(
				[("Local", 1, 7, "Free"), ("DRC", 1, 30, "Free"), ("Other", 1, 15, "Free")]
			):
				row = frappe.get_doc(
					{
						"doctype": "ICD TZ Settings Detail",
						"parent": setting,
						"parenttype": "ICD Setting",
						"parentfield": "storage_days",
						"idx": i + 1,
						"destination": d,
						"from": a,
						"to": b,
						"charge": c,
					}
				)
				row.db_insert()
				self.added_bands.append(row.name)
		frappe.clear_document_cache("ICD Setting", setting)
		# what a real submitted order carries: truck, trailer, driver, transporter (made once, kept for reruns)
		for plate in (TRUCK, TRAILER):
			if not frappe.db.exists("Vehicle", plate):
				v = frappe.get_doc({"doctype": "Vehicle", "license_plate": plate})
				v.flags.ignore_mandatory = True
				v.insert(ignore_permissions=True)
		if not frappe.db.exists("Supplier", TRANSPORTER):
			s = frappe.get_doc({"doctype": "Supplier", "supplier_name": TRANSPORTER})
			s.flags.ignore_mandatory = True
			s.insert(ignore_permissions=True)
		self.driver = frappe.db.get_value("Driver", {"full_name": "TEST ICDLINK DRIVER"})
		if not self.driver:
			d = frappe.get_doc({"doctype": "Driver", "full_name": "TEST ICDLINK DRIVER"})
			d.flags.ignore_mandatory = True
			self.driver = d.insert(ignore_permissions=True).name

		mf = frappe.get_doc(
			{
				"doctype": "Manifest",
				"name": MF,
				"mrn": MRN,
				"company": self.company,
				"docstatus": 1,
				"vessel_name": "TEST VESSEL",
				"voyage_no": "001",
				"containers": [
					{
						"m_bl_no": BL,
						"container_no": CNTR,
						"container_size": "22G0",
						"freight_indicator": "FCL",
						"weight": "26083",
						"weight_unit": "KG",
						"seal_no1": "MANIFESTSEAL",
					},
					{
						"m_bl_no": OTHER_BL,
						"container_no": OTHER_CNTR,
						"container_size": "22G0",
						"freight_indicator": "FCL",
					},
				],
				"master_bl": [
					{
						"m_bl_no": BL,
						"cargo_classification": "IM",
						"shipping_agent_code": "TST",
						"number_of_containers": "1",
						"place_of_destination": "CDLUB",
					},
					{
						"m_bl_no": OTHER_BL,
						"cargo_classification": "IM",
						"shipping_agent_code": "TST",
						"number_of_containers": "1",
					},
				],
			}
		)
		mf.db_insert()
		for child in mf.get_all_children():
			child.db_insert()

	def tearDown(self):
		frappe.db.set_single_value("TANeSW Settings", "draft_portal_receptions", self.old_draft_portal or 0)
		self.cleanup()
		if self.added_bands:
			frappe.db.delete("ICD TZ Settings Detail", {"name": ["in", self.added_bands]})
			frappe.clear_document_cache(
				"ICD Setting", frappe.db.get_value("ICD Setting", {"company": self.company})
			)
		if self.made_setting:
			frappe.db.delete("ICD Setting", {"company": self.company})

	def cleanup(self):
		frappe.db.delete("Container Reception", {"manifest": MF})
		frappe.db.delete("Container Movement Order", {"manifest": MF})
		for table in ("Containers Detail", "Master BL"):
			frappe.db.delete(table, {"parent": MF})
		frappe.db.delete("Manifest", {"name": MF})
		frappe.db.delete("TANeSW Carry In Container", {"mrn": MRN})

	def order_basics(self):
		return {
			"company": self.company,
			"ship_dc_date": "2026-11-02",
			"docstatus": 1,
			"status": "Pending",
			"movement_date": "2026-11-02",
			"icd_time_in": "21:00:00",
			"port_time_out": "19:00:00",
			"transporter": TRANSPORTER,
			"driver": self.driver,
			"trailer": TRAILER,
		}

	def best_pick(self, name, truck=TRUCK):
		cmo = frappe.get_doc(
			{
				"doctype": "Container Movement Order",
				"name": name,
				"manifest": MF,
				"best_pick": 1,
				"truck": truck,
				**self.order_basics(),
			}
		)
		cmo.db_insert()
		return name

	def log(self, row, bl=BL):
		name = icd_link.upsert_log(REPORT, row, *icd_link.parse_cntr_info(row["cntrInfo"])[0])
		# live, the B/L comes from the TANeSW Container record; here it is set directly
		if bl:
			frappe.db.set_value("TANeSW Carry In Container", name, "bl_no", bl)
		return name

	def bp(self, name, creation, licence, trailer):
		"""A Best Pick order for TRUCK with its own driver licence / trailer (one truck, several trips)."""
		cmo = frappe.get_doc(
			{
				"doctype": "Container Movement Order",
				"name": name,
				"manifest": MF,
				"best_pick": 1,
				"truck": TRUCK,
				**self.order_basics(),
				"trailer": trailer,
				"driver_license": licence,
				"creation": creation,
			}
		)
		cmo.db_insert()

	def test_best_pick_prefers_the_driver_then_the_trailer_then_the_oldest(self):
		self.bp("TEST-ICDLINK-CMO-1", "2026-11-01 08:00:00", "4009999999", "T111AAA")  # oldest, other driver
		self.bp(
			"TEST-ICDLINK-CMO-2", "2026-11-01 09:00:00", "4009999999", "T268DYR"
		)  # other driver, same trailer
		self.bp(
			"TEST-ICDLINK-CMO-3", "2026-11-01 10:00:00", "4005395198", "T111AAA"
		)  # this driver, other trailer
		self.bp(
			"TEST-ICDLINK-CMO-4", "2026-11-01 11:00:00", "4005395198", "T268DYR"
		)  # this driver and trailer
		log = frappe.get_doc("TANeSW Carry In Container", self.log(truck_row()))
		self.assertEqual(
			icd_link.best_pick_candidates(MF, log),
			["TEST-ICDLINK-CMO-4", "TEST-ICDLINK-CMO-3", "TEST-ICDLINK-CMO-2", "TEST-ICDLINK-CMO-1"],
		)

	def test_two_different_trips_for_one_truck_are_not_guessed(self):
		"""Review #16: a reused truck must not put the box on another transporter's order."""
		self.bp("TEST-ICDLINK-CMO-1", "2026-11-01 08:00:00", None, "T111AAA")
		self.bp("TEST-ICDLINK-CMO-2", "2026-11-01 09:00:00", None, "T222BBB")
		log = frappe.get_doc("TANeSW Carry In Container", self.log(truck_row()))
		log.trailer = None
		order, why = icd_link.pick_best_pick(MF, log)
		self.assertIsNone(order)
		self.assertIn("choose the right one at the gate", why)

	def test_an_order_for_another_driver_is_never_taken(self):
		self.bp("TEST-ICDLINK-CMO-1", "2026-11-01 08:00:00", "4009999999", "T268DYR")
		log = frappe.get_doc("TANeSW Carry In Container", self.log(truck_row()))
		order, why = icd_link.pick_best_pick(MF, log)
		self.assertIsNone(order)
		self.assertIn("other drivers", why)

	def test_the_one_order_for_this_driver_and_trailer_is_taken(self):
		self.bp("TEST-ICDLINK-CMO-1", "2026-11-01 08:00:00", "4005395198", "T111AAA")
		self.bp("TEST-ICDLINK-CMO-2", "2026-11-01 09:00:00", "4005395198", "T268DYR")
		log = frappe.get_doc("TANeSW Carry In Container", self.log(truck_row()))
		self.assertEqual(icd_link.pick_best_pick(MF, log), ("TEST-ICDLINK-CMO-2", None))

	def test_identical_best_picks_are_taken_oldest_first(self):
		self.bp("TEST-ICDLINK-CMO-2", "2026-11-01 09:00:00", "4005395198", "T268DYR")
		self.bp("TEST-ICDLINK-CMO-1", "2026-11-01 08:00:00", "4005395198", "T268DYR")
		log = frappe.get_doc("TANeSW Carry In Container", self.log(truck_row()))
		self.assertEqual(icd_link.best_pick_candidates(MF, log)[0], "TEST-ICDLINK-CMO-1")
		self.assertEqual(icd_link.pick_best_pick(MF, log), ("TEST-ICDLINK-CMO-1", None))

	def test_links_older_than_90_days_are_purged_the_rest_kept(self):
		old, new = self.log(truck_row()), self.log(truck_row(dclr="WITZDL0192026I9990002"))
		frappe.db.set_value(
			"TANeSW Carry In Container", old, "creation", "2026-01-01 00:00:00", update_modified=False
		)
		self.assertGreaterEqual(icd_link.purge_old_links(), 1)
		self.assertFalse(frappe.db.exists("TANeSW Carry In Container", old))
		self.assertTrue(frappe.db.exists("TANeSW Carry In Container", new))

	def without_manifest(self, name="TEST-ICDLINK-CMO-NOMF"):
		"""A Best Pick order made before the driver went to the port: no manifest yet (best_pick_setup)."""
		from tanesw_integration import best_pick_setup

		best_pick_setup.apply(True)
		self.addCleanup(best_pick_setup.apply, False)
		self.addCleanup(frappe.db.delete, "Container Movement Order", {"name": name})
		cmo = frappe.get_doc(
			{
				"doctype": "Container Movement Order",
				"name": name,
				"best_pick": 1,
				"truck": TRUCK,
				**self.order_basics(),
			}
		)
		cmo.db_insert()
		return name

	def test_best_pick_made_without_manifest_is_filled_at_handover(self):
		name = self.without_manifest()
		log = self.log(truck_row())
		icd_link.process_link(log)
		msg = frappe.db.get_value("TANeSW Carry In Container", log, "link_message")
		o = frappe.db.get_value(
			"Container Movement Order", name, ["manifest", "container_no", "m_bl_no"], as_dict=True
		)
		self.assertEqual((o.manifest, o.container_no, o.m_bl_no), (MF, CNTR, BL), msg)

	def test_an_order_for_the_manifest_beats_one_without(self):
		self.without_manifest()
		self.best_pick("TEST-ICDLINK-CMO-1")
		log = frappe.get_doc("TANeSW Carry In Container", self.log(truck_row()))
		self.assertEqual(icd_link.best_pick_candidates(MF, log)[0], "TEST-ICDLINK-CMO-1")

	def test_manifest_of_a_submitted_order_cannot_be_swapped(self):
		from tanesw_integration import best_pick_setup

		self.best_pick("TEST-ICDLINK-CMO-1")
		doc = frappe.get_doc("Container Movement Order", "TEST-ICDLINK-CMO-1")
		doc._doc_before_save = frappe.get_doc("Container Movement Order", "TEST-ICDLINK-CMO-1")
		doc.manifest = "SOME-OTHER-MANIFEST"
		with self.assertRaises(frappe.ValidationError):
			best_pick_setup.validate_manifest_change(doc)

	def test_only_the_tanesw_fill_may_fill_a_submitted_order(self):
		"""Review #13: the after-submit fields change through the app's fill only, never by hand."""
		from tanesw_integration import best_pick_setup

		name = self.without_manifest()
		doc = frappe.get_doc("Container Movement Order", name)
		doc._doc_before_save = frappe.get_doc("Container Movement Order", name)
		doc.manifest, doc.container_no = MF, CNTR
		with self.assertRaises(frappe.ValidationError):  # by hand, even to an empty order
			best_pick_setup.validate_manifest_change(doc)
		frappe.flags.tanesw_best_pick_fill = True
		try:
			best_pick_setup.validate_manifest_change(doc)  # the app's own fill
		finally:
			frappe.flags.tanesw_best_pick_fill = False
		doc.manifest, doc.port = doc._doc_before_save.manifest, "SOME OTHER PORT"
		with self.assertRaises(frappe.ValidationError):  # port alone, by hand
			best_pick_setup.validate_manifest_change(doc)

	# ------------------------------------------------------------------ tests
	def test_best_pick_is_filled_then_reception_drafted_on_entry(self):
		older = self.best_pick("TEST-ICDLINK-CMO-1")
		self.best_pick("TEST-ICDLINK-CMO-2")  # same truck, later: the oldest open order is used
		name = self.log(truck_row(entry="N"))

		status = icd_link.process_link(name)
		self.assertEqual(
			status, icd_link.LINKED, frappe.db.get_value("TANeSW Carry In Container", name, "link_message")
		)
		cmo = frappe.get_doc("Container Movement Order", older)
		self.assertEqual(
			(cmo.container_no, cmo.m_bl_no, cmo.size, cmo.freight_indicator, cmo.cargo_type),
			(CNTR, BL, "22G0", "FCL", "IM"),
		)
		self.assertEqual(
			frappe.db.get_value("Containers Detail", {"parent": MF, "container_no": CNTR}, "has_order"), 1
		)
		self.assertFalse(
			frappe.db.get_value("Container Movement Order", "TEST-ICDLINK-CMO-2", "container_no")
		)
		self.assertFalse(frappe.db.exists("Container Reception", {"movement_order": older}))

		# TANeSW now confirms entry at our gate
		icd_link.upsert_log(
			REPORT, truck_row(entry="Y"), *icd_link.parse_cntr_info(truck_row()["cntrInfo"])[0]
		)
		self.assertEqual(icd_link.process_link(name), icd_link.DRAFTED)
		rec = frappe.get_doc(
			"Container Reception",
			frappe.db.get_value("TANeSW Carry In Container", name, "container_reception"),
		)
		self.assertEqual(rec.docstatus, 0)
		# filled by icd_tz from the movement order, not by us
		self.assertEqual((rec.container_no, rec.m_bl_no, rec.manifest, rec.truck), (CNTR, BL, MF, TRUCK))
		self.assertEqual(
			rec.seal_no_1, "MANIFESTSEAL"
		)  # the manifest's, as on screen; TANeSW's only as a fallback
		self.assertEqual((rec.weight, rec.weight_unit), ("26083", "KG"))
		self.assertEqual((rec.abbr_for_destination, rec.place_of_destination), ("CDLUB", "DRC"))
		self.assertEqual(rec.country_of_destination, frappe.db.get_value("Country", {"code": "cd"}, "name"))
		self.assertEqual(rec.shipping_line_code, "TST")

		# running again changes nothing
		self.assertEqual(icd_link.process_link(name), icd_link.DRAFTED)
		self.assertEqual(frappe.db.count("Container Reception", {"movement_order": older}), 1)

	def test_no_order_for_the_truck_waits_then_becomes_an_exception_at_our_gate(self):
		self.best_pick("TEST-ICDLINK-CMO-1", truck=TRUCK)
		name = self.log(truck_row(truck="T111AAA"))
		self.assertEqual(icd_link.process_link(name), icd_link.WAITING)
		self.assertIn(
			"No open Best Pick Movement Order for truck T111AAA",
			frappe.db.get_value("TANeSW Carry In Container", name, "link_message"),
		)

		frappe.db.set_value("TANeSW Carry In Container", name, "entry_confirmed", 1)
		self.assertEqual(icd_link.process_link(name), icd_link.EXCEPTION)
		self.assertFalse(
			frappe.db.get_value("Container Movement Order", "TEST-ICDLINK-CMO-1", "container_no")
		)

	def test_bl_mismatch_leaves_the_order_untouched(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(truck_row(), bl=OTHER_BL)
		self.assertEqual(icd_link.process_link(name), icd_link.WAITING)
		self.assertIn("B/L mismatch", frappe.db.get_value("TANeSW Carry In Container", name, "link_message"))
		self.assertFalse(
			frappe.db.get_value("Container Movement Order", "TEST-ICDLINK-CMO-1", "container_no")
		)

	def test_container_not_on_the_manifest_is_reported(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(truck_row(info="ZZZU0000001 (22G0, S1)"), bl=None)
		self.assertEqual(icd_link.process_link(name), icd_link.WAITING)
		self.assertIn(
			"is not on manifest", frappe.db.get_value("TANeSW Carry In Container", name, "link_message")
		)

	def test_an_existing_order_for_the_container_is_used_as_is(self):
		cmo = frappe.get_doc(
			{
				"doctype": "Container Movement Order",
				"name": "TEST-ICDLINK-CMO-9",
				"manifest": MF,
				"container_no": CNTR,
				"m_bl_no": BL,
				"truck": TRUCK,
				**self.order_basics(),
			}
		)
		cmo.db_insert()
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(truck_row(entry="Y"))
		self.assertEqual(icd_link.process_link(name), icd_link.DRAFTED)
		self.assertEqual(
			frappe.db.get_value("TANeSW Carry In Container", name, "movement_order"), "TEST-ICDLINK-CMO-9"
		)
		self.assertFalse(
			frappe.db.get_value("Container Movement Order", "TEST-ICDLINK-CMO-1", "container_no")
		)

	def test_icd_tz_refusal_is_reported_and_rolled_back(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(truck_row())
		with patch(
			"icd_tz.icd_tz.doctype.container_movement_order.container_movement_order.get_unpaid_port_charges",
			return_value=["Wharfage"],
		):
			self.assertEqual(icd_link.process_link(name), icd_link.WAITING)
		self.assertIn(
			"icd_tz refused to fill", frappe.db.get_value("TANeSW Carry In Container", name, "link_message")
		)
		self.assertFalse(
			frappe.db.get_value("Container Movement Order", "TEST-ICDLINK-CMO-1", "container_no")
		)
		self.assertTrue(frappe.db.exists("Manifest", MF))  # only the failed step was undone

	def test_carry_in_number_arriving_later_keeps_the_handover_record(self):
		first = self.log(truck_row(dclr=None))
		self.assertEqual(first, f"{REPORT['criBaseNo']}-{CNTR}")
		again = icd_link.upsert_log(
			REPORT,
			truck_row(dclr="WITZDL0192026I9990001"),
			*icd_link.parse_cntr_info(truck_row()["cntrInfo"])[0],
		)
		self.assertEqual(again, first)
		self.assertEqual(
			frappe.db.get_value("TANeSW Carry In Container", first, "carry_in_no"), "WITZDL0192026I9990001"
		)
		self.assertEqual(frappe.db.count("TANeSW Carry In Container", {"mrn": MRN}), 1)

	def test_handover_is_skipped_only_when_every_truck_is_in(self):
		report = {**REPORT, "vhclCnt": "2"}
		self.assertFalse(icd_link._all_trucks_in(report))  # never logged: read it
		self.log(truck_row(entry="Y"))
		self.assertFalse(icd_link._all_trucks_in(report))  # one of two trucks logged
		self.log(
			truck_row(
				entry="N", truck="T111AAA", info=f"{OTHER_CNTR} (22G0, S2)", dclr="WITZDL0192026I9990002"
			)
		)
		self.assertFalse(icd_link._all_trucks_in(report))  # second truck still on the road
		frappe.db.set_value("TANeSW Carry In Container", {"container_no": OTHER_CNTR}, "entry_confirmed", 1)
		self.assertTrue(icd_link._all_trucks_in(report))

	def test_transport_details_are_compared_by_plate_and_licence(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		frappe.db.set_value("Container Movement Order", "TEST-ICDLINK-CMO-1", "driver_license", "4005395198")
		same = self.log(truck_row())  # same truck (spaced), trailer and licence as the order
		icd_link.process_link(same)
		self.assertEqual(frappe.db.get_value("TANeSW Carry In Container", same, "transport_check"), "Matches")

		order = frappe.get_doc("Container Movement Order", "TEST-ICDLINK-CMO-1")
		log = frappe._dict(
			truck=TRUCK, trailer="T999ZZZ", driver_license="4000000001", driver_name="OTHER DRIVER"
		)
		check, note = icd_link.compare_transport(order.name, log)
		self.assertEqual(check, "Differs")
		self.assertIn("trailer: TANeSW T999ZZZ, order T268DYR", note)
		self.assertIn("driver licence: TANeSW 4000000001, order 4005395198", note)
		self.assertIn("OTHER DRIVER", note)

	def test_both_triggers_together_make_one_order_fill_and_one_reception(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		self.best_pick("TEST-ICDLINK-CMO-2")
		a = self.log(truck_row(entry="Y"))
		b = icd_link.upsert_log(
			REPORT, truck_row(entry="Y"), *icd_link.parse_cntr_info(truck_row()["cntrInfo"])[0]
		)
		self.assertEqual(a, b)  # same carry-in + container: one log
		self.assertEqual(icd_link.process_link(a), icd_link.DRAFTED)
		self.assertEqual(icd_link.process_link(b), icd_link.DRAFTED)  # the second trigger finds it done
		self.assertEqual(frappe.db.count("Container Reception", {"manifest": MF}), 1)
		self.assertEqual(
			frappe.db.count("Container Movement Order", {"manifest": MF, "container_no": CNTR}), 1
		)
		self.assertFalse(
			frappe.db.get_value("Container Movement Order", "TEST-ICDLINK-CMO-2", "container_no")
		)

	def test_a_reception_made_by_hand_is_reused_not_duplicated(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(truck_row(entry="N"))
		icd_link.process_link(name)  # fills the order
		manual = frappe.new_doc("Container Reception")
		manual.movement_order = "TEST-ICDLINK-CMO-1"
		manual.flags.ignore_mandatory = True
		manual.insert(ignore_permissions=True)
		frappe.db.set_value("TANeSW Carry In Container", name, "entry_confirmed", 1)
		self.assertEqual(icd_link.process_link(name), icd_link.DRAFTED)
		self.assertEqual(
			frappe.db.get_value("TANeSW Carry In Container", name, "container_reception"), manual.name
		)
		self.assertEqual(frappe.db.count("Container Reception", {"movement_order": "TEST-ICDLINK-CMO-1"}), 1)

	def test_icd_tz_itself_refuses_a_second_reception_for_the_order(self):
		self.best_pick("TEST-ICDLINK-CMO-1")
		name = self.log(truck_row(entry="Y"))
		icd_link.process_link(name)
		dup = frappe.new_doc("Container Reception")
		dup.movement_order = "TEST-ICDLINK-CMO-1"
		dup.flags.ignore_mandatory = True
		with self.assertRaises(frappe.ValidationError):
			dup.insert(ignore_permissions=True)

	def test_simultaneous_log_insert_updates_the_existing_one(self):
		first = self.log(truck_row(entry="N"))
		with patch(
			"tanesw_integration.icd_link._existing_log", return_value=None
		):  # the race: neither saw the other
			again = icd_link.upsert_log(
				REPORT, truck_row(entry="Y"), *icd_link.parse_cntr_info(truck_row()["cntrInfo"])[0]
			)
		self.assertEqual(again, first)
		self.assertEqual(frappe.db.get_value("TANeSW Carry In Container", first, "entry_confirmed"), 1)
		self.assertEqual(frappe.db.count("TANeSW Carry In Container", {"mrn": MRN}), 1)

	def test_carry_in_from_this_app_queues_one_job_per_report(self):
		old = frappe.db.get_single_value("TANeSW Settings", "enable_icd_link")
		try:
			frappe.db.set_single_value("TANeSW Settings", "enable_icd_link", 1)
			with patch("frappe.enqueue") as enqueue:
				icd_link.on_carry_in_submitted({"crn": REPORT["crn"], "criBaseNo": REPORT["criBaseNo"]})
				icd_link.on_carry_in_submitted({"crn": REPORT["crn"]})  # no report number: nothing to link
			enqueue.assert_called_once()
			kw = enqueue.call_args.kwargs
			self.assertEqual(
				(kw["job_id"], kw["deduplicate"], kw["enqueue_after_commit"]),
				(f"tanesw_icd_link:{REPORT['criBaseNo']}", True, True),
			)
		finally:
			frappe.db.set_single_value("TANeSW Settings", "enable_icd_link", old or 0)

	def test_job_does_nothing_while_switched_off(self):
		old = frappe.db.get_single_value("TANeSW Settings", "enable_icd_link")
		try:
			frappe.db.set_single_value("TANeSW Settings", "enable_icd_link", 0)
			with patch("frappe.enqueue") as enqueue:
				icd_link.enqueue_icd_link()
			enqueue.assert_not_called()
			self.assertEqual(icd_link.sync_carry_ins()["status"], "disabled")
		finally:
			frappe.db.set_single_value("TANeSW Settings", "enable_icd_link", old or 0)
