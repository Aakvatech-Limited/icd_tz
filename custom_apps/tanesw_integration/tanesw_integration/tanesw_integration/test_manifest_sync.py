"""manifest_sync: TANeSW manifest Excel vs ERP Manifest, box by box. TANeSW is never called: the 'fresh' Manifest
(what icd_tz's import makes of TANeSW's Excel) is built here, and tracing is switched off."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import manifest_sync as ms

MRN = "TEST26MSYNC01"
LOG = ms.LOG
CONSIGNEE = "TEST MSYNC CONSIGNEE"


def rows(boxes):
	"""boxes: {container_no: m_bl_no} -> the four Manifest tables."""
	bls = sorted(set(boxes.values()))
	return {
		"containers": [
			{
				"container_no": c,
				"m_bl_no": b,
				"container_size": "40",
				"freight_indicator": "FCL",
				"type_of_container": "C",
			}
			for c, b in boxes.items()
		],
		"master_bl": [
			{
				"m_bl_no": b,
				"place_of_delivery": "WITZDL019",
				"cargo_classification": "IM",
				"consignee_name": CONSIGNEE,
				"number_of_containers": list(boxes.values()).count(b),
			}
			for b in bls
		],
		"hbl_containers": [],
		"house_bl": [],
	}


TEST_FILE = "test-msync-manifest.xlsx"


def test_file_url():
	"""A real (tiny) private file: a made-up path makes Frappe log 'Error Attaching File' on every save."""
	url = frappe.db.get_value(
		"File", {"file_name": TEST_FILE, "attached_to_name": ["is", "not set"]}, "file_url"
	)
	if not url:
		url = (
			frappe.get_doc({"doctype": "File", "file_name": TEST_FILE, "is_private": 1, "content": b"test"})
			.insert(ignore_permissions=True)
			.file_url
		)
	return url


def fresh(boxes):
	return frappe.get_doc(
		{
			"doctype": "Manifest",
			"mrn": MRN,
			"vessel_name": "TEST VESSEL",
			"voyage_no": "1T",
			"company": company(),
			"manifest": test_file_url(),
			**rows(boxes),
		}
	)


def company():
	return frappe.db.get_value("Company", {}, "name")


def settings(**kw):
	s = frappe._dict(
		{
			"enable_manifest_sync": 1,
			"auto_create_manifests": 0,
			"manifest_create_status": "Draft",
			"update_erp_manifests": 0,
		}
	)
	s.update(kw)
	return s


class TestManifestSync(FrappeTestCase):
	def setUp(self):
		self.cleanup()
		self.addCleanup(self.cleanup)
		p = patch.object(ms, "trace")  # never call TANeSW
		p.start()
		self.addCleanup(p.stop)

	def cleanup(self):
		names = frappe.get_all("Manifest", filters={"mrn": MRN}, pluck="name")
		for n in names:
			for t in ("Containers Detail", "Master BL", "HBL Container", "House BL"):
				frappe.db.delete(t, {"parent": n})
			frappe.db.delete("ICD Container", {"manifest": n})
			frappe.db.delete("ICD Master BL", {"manifest": n})
			frappe.db.delete("Comment", {"reference_doctype": "Manifest", "reference_name": n})
		frappe.db.delete("Manifest", {"mrn": MRN})
		frappe.db.delete(LOG, {"mrn": MRN})
		frappe.db.delete("TANeSW Container", {"mrn": MRN})
		frappe.db.delete("Consignee", {"name": CONSIGNEE})
		frappe.db.delete("File", {"file_name": ["like", "test-msync-manifest%"]})

	def manifest(self, boxes, submit=True):
		doc = fresh(boxes)
		doc.port = "TEAGTL"
		doc.insert(ignore_permissions=True)
		if submit:
			doc.submit()
		return doc.name

	def run_sync(self, boxes, **kw):
		stats = ms._new_stats()
		ms.sync_vessel(MRN, settings(**kw), stats, {"traces": 0}, fresh=fresh(boxes))
		return stats

	def log(self, cntr, change="Removed"):
		return frappe.db.get_value(
			LOG,
			ms._log_name(MRN, cntr, change),
			["outcome", "manifest_action", "on_erp_manifest"],
			as_dict=True,
		)

	def boxes_on(self, name):
		return sorted(frappe.get_all("Containers Detail", filters={"parent": name}, pluck="container_no"))

	# ------------------------------------------------------------------ recording
	def test_changes_are_recorded_and_manifest_left_alone_when_updates_are_off(self):
		name = self.manifest({"AAAA0000001": "BL1", "BBBB0000001": "BL1", "CCCC0000001": "BL2"})
		st = self.run_sync({"AAAA0000001": "BL1", "BBBB0000001": "BL1", "DDDD0000001": "BL3"})
		self.assertEqual((st.removed, st.added), (1, 1))
		self.assertEqual(self.log("CCCC0000001").manifest_action, ms.KEPT_OFF)
		self.assertEqual(self.log("CCCC0000001").on_erp_manifest, 1)
		self.assertEqual(self.log("DDDD0000001", "Added").outcome, ms.ADDED)
		self.assertEqual(self.boxes_on(name), ["AAAA0000001", "BBBB0000001", "CCCC0000001"])

	def test_a_box_only_tanesw_container_saw_is_still_caught(self):
		"""A box gone before anyone looked, but our sync had seen it on our B/Ls."""
		doc = frappe.new_doc("TANeSW Container")
		doc.update({"container_no": "EEEE0000001", "mrn": MRN, "bl_no": "BL9", "status": "At Terminal"})
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		self.run_sync({"AAAA0000001": "BL1"})
		self.assertEqual(self.log("EEEE0000001").manifest_action, ms.NO_MANIFEST)

	def test_running_twice_records_once(self):
		self.manifest({"AAAA0000001": "BL1", "CCCC0000001": "BL2"})
		self.run_sync({"AAAA0000001": "BL1"})
		st = self.run_sync({"AAAA0000001": "BL1"})
		self.assertEqual(st.removed, 0)
		self.assertEqual(frappe.db.count(LOG, {"mrn": MRN}), 1)

	def test_a_box_that_comes_back_is_marked_back(self):
		self.manifest({"AAAA0000001": "BL1", "CCCC0000001": "BL2"})
		self.run_sync({"AAAA0000001": "BL1"})
		self.run_sync({"AAAA0000001": "BL1", "CCCC0000001": "BL2"})
		self.assertEqual(self.log("CCCC0000001").outcome, ms.BACK)

	# ------------------------------------------------------------------ applying to the ERP Manifest
	def test_updates_on_take_off_free_boxes_and_add_new_ones(self):
		ms.apply_setters(True)
		self.addCleanup(ms.apply_setters, False)
		name = self.manifest({"AAAA0000001": "BL1", "BBBB0000001": "BL1", "CCCC0000001": "BL2"})
		st = self.run_sync(
			{"AAAA0000001": "BL1", "BBBB0000001": "BL1", "DDDD0000001": "BL3"}, update_erp_manifests=1
		)
		self.assertEqual((st.taken_off, st.put_on), (1, 1))
		self.assertEqual(self.boxes_on(name), ["AAAA0000001", "BBBB0000001", "DDDD0000001"])
		bls = sorted(frappe.get_all("Master BL", filters={"parent": name}, pluck="m_bl_no"))
		self.assertEqual(bls, ["BL1", "BL3"])  # BL2 lost its only box, BL3 came with the new one
		self.assertEqual(self.log("CCCC0000001").manifest_action, ms.TAKEN_OFF)
		self.assertEqual(self.log("DDDD0000001", "Added").manifest_action, ms.PUT_ON)
		self.assertTrue(frappe.db.exists("ICD Container", {"manifest": name, "container_no": "DDDD0000001"}))
		self.assertTrue(frappe.db.exists("ICD Master BL", {"manifest": name, "m_bl_no": "BL3"}))
		self.assertEqual(frappe.db.get_value("Manifest", name, "docstatus"), 1)

	def test_dimensions_still_made_if_icd_tz_renames_its_functions(self):
		"""The fallback copy makes the same records when icd_tz's own functions cannot be found."""
		ms.apply_setters(True)
		self.addCleanup(ms.apply_setters, False)
		name = self.manifest({"AAAA0000001": "BL1"})
		real = frappe.get_attr

		def gone(path):
			return (
				(_ for _ in ()).throw(AttributeError(path))
				if path.startswith(ms.ICD_DIMENSIONS)
				else real(path)
			)

		with patch.object(ms.frappe, "get_attr", side_effect=gone):
			self.run_sync({"AAAA0000001": "BL1", "DDDD0000001": "BL3"}, update_erp_manifests=1)
		self.assertTrue(frappe.db.exists("ICD Container", {"manifest": name, "container_no": "DDDD0000001"}))
		self.assertTrue(frappe.db.exists("ICD Master BL", {"manifest": name, "m_bl_no": "BL3"}))

	def test_a_b_l_box_count_follows_its_boxes(self):
		"""Movement Orders show 'box x of y' from Master BL Number of Containers."""
		ms.apply_setters(True)
		self.addCleanup(ms.apply_setters, False)
		name = self.manifest({"AAAA0000001": "BL1", "BBBB0000001": "BL1"})
		self.run_sync({"AAAA0000001": "BL1"}, update_erp_manifests=1)
		n = frappe.db.get_value("Master BL", {"parent": name, "m_bl_no": "BL1"}, "number_of_containers")
		self.assertEqual(frappe.utils.cint(n), 1)  # a Data field in icd_tz

	def test_a_b_l_kept_by_tanesw_takes_tanesw_figures(self):
		"""Billing Efficiency splits an LCL B/L's volume over its box count: both must be TANeSW's."""
		ms.apply_setters(True)
		self.addCleanup(ms.apply_setters, False)
		name = self.manifest({"AAAA0000001": "BL1", "BBBB0000001": "BL1", "CCCC0000001": "BL2"})
		f = fresh({"AAAA0000001": "BL1", "BBBB0000001": "BL1"})
		for r in f.master_bl:
			r.gross_volume = 33.5  # TANeSW restated the B/L
		ms.sync_vessel(MRN, settings(update_erp_manifests=1), ms._new_stats(), {"traces": 0}, fresh=f)
		self.assertEqual(
			frappe.utils.flt(
				frappe.db.get_value("Master BL", {"parent": name, "m_bl_no": "BL1"}, "gross_volume")
			),
			33.5,
		)

	def test_users_cannot_add_or_remove_rows_on_a_submitted_manifest(self):
		ms.apply_setters(True)
		self.addCleanup(ms.apply_setters, False)
		name = self.manifest({"AAAA0000001": "BL1", "BBBB0000001": "BL1"})
		doc = frappe.get_doc("Manifest", name)
		doc.containers = doc.containers[:1]
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_a_removed_box_with_a_movement_order_stays_and_is_flagged(self):
		ms.apply_setters(True)
		self.addCleanup(ms.apply_setters, False)
		name = self.manifest({"AAAA0000001": "BL1", "CCCC0000001": "BL2"})
		real = ms._linked

		def fake(m, c):
			return {"movement_order": "CMO-TEST"} if c == "CCCC0000001" else real(m, c)

		with patch.object(ms, "_linked", side_effect=fake):
			self.run_sync({"AAAA0000001": "BL1"}, update_erp_manifests=1)
		self.assertIn("CCCC0000001", self.boxes_on(name))
		self.assertEqual(self.log("CCCC0000001").manifest_action, ms.KEPT_ORDER)

	def test_a_removed_box_with_a_port_charge_stays(self):
		"""Review #11: a box we already raised a port-charge PO/PI for is never taken off its Manifest."""
		ms.apply_setters(True)
		self.addCleanup(ms.apply_setters, False)
		name = self.manifest({"AAAA0000001": "BL1", "CCCC0000001": "BL2"})
		box = frappe.db.get_value("ICD Container", {"manifest": name, "container_no": "CCCC0000001"})
		self.assertTrue(box, "icd_tz makes an ICD Container per box on submit")
		frappe.db.set_value("ICD Container", box, "purchase_invoice", "ACC-PINV-TEST-PORT")
		self.assertEqual(ms._port_charge(name, "CCCC0000001"), "ACC-PINV-TEST-PORT")
		self.run_sync({"AAAA0000001": "BL1"}, update_erp_manifests=1)
		self.assertIn("CCCC0000001", self.boxes_on(name))
		self.assertEqual(self.log("CCCC0000001").manifest_action, ms.KEPT_ORDER)

	def test_terminal_ports_come_from_the_settings(self):
		old = frappe.db.get_single_value("TANeSW Settings", "terminal_ports")
		self.addCleanup(frappe.db.set_single_value, "TANeSW Settings", "terminal_ports", old)
		frappe.db.set_single_value(
			"TANeSW Settings", "terminal_ports", "wttzdl008 = TEAGTL\nbad line\nWTTZDL007=DP WORLD"
		)
		self.assertEqual(ms.terminal_ports(), {"WTTZDL008": "TEAGTL", "WTTZDL007": "DP WORLD"})
		frappe.db.set_single_value("TANeSW Settings", "terminal_ports", "")
		self.assertEqual(ms.terminal_ports(), {})

	def test_draft_manifest_follows_tanesw_too(self):
		name = self.manifest({"AAAA0000001": "BL1", "CCCC0000001": "BL2"}, submit=False)
		self.run_sync({"AAAA0000001": "BL1", "DDDD0000001": "BL3"}, update_erp_manifests=1)
		self.assertEqual(self.boxes_on(name), ["AAAA0000001", "DDDD0000001"])

	# ------------------------------------------------------------------ creating Manifests
	def test_new_allocation_creates_a_draft_manifest(self):
		with patch.object(ms, "port_of", return_value=None):
			st = self.run_sync(
				{"AAAA0000001": "BL1"}, auto_create_manifests=1, manifest_create_status="Submitted"
			)
		name = ms.erp_manifest(MRN)
		self.assertEqual(st.created, 1)
		self.assertEqual(frappe.db.get_value("Manifest", name, "docstatus"), 0)  # no port known: stays Draft

	def test_new_allocation_is_submitted_when_the_port_is_known(self):
		with patch.object(ms, "port_of", return_value="TEAGTL"):
			self.run_sync({"AAAA0000001": "BL1"}, auto_create_manifests=1, manifest_create_status="Submitted")
		name = ms.erp_manifest(MRN)
		self.assertEqual(frappe.db.get_value("Manifest", name, ["docstatus", "port"]), (1, "TEAGTL"))
		self.assertTrue(frappe.db.exists("ICD Container", {"manifest": name, "container_no": "AAAA0000001"}))

	def test_a_refused_submit_keeps_the_draft_and_says_why(self):
		"""icd_tz refused TANeSW's consignee phone 'TEL:+243800000001' on dev: keep the Draft, comment the reason."""
		boom = frappe.ValidationError("TEL:+243800000001 is not a valid Phone Number")
		with (
			patch.object(ms, "port_of", return_value="TEAGTL"),
			patch("frappe.model.document.Document.submit", side_effect=boom),
		):
			st = self.run_sync(
				{"AAAA0000001": "BL1"}, auto_create_manifests=1, manifest_create_status="Submitted"
			)
		name = ms.erp_manifest(MRN)
		self.assertEqual((st.created, st.get("submit_failed")), (1, 1))
		self.assertEqual(frappe.db.get_value("Manifest", name, "docstatus"), 0)
		self.assertTrue(
			frappe.db.exists("Comment", {"reference_name": name, "content": ["like", "%not a valid Phone%"]})
		)

	def test_nothing_is_created_when_the_option_is_off(self):
		self.run_sync({"AAAA0000001": "BL1"})
		self.assertIsNone(ms.erp_manifest(MRN))

	# ------------------------------------------------------------------ download only on a change
	def vessel(self, **kw):
		v = frappe._dict(
			{
				"name": MRN,
				"bl_count": 2,
				"container_count": 3,
				"manifest_synced_on": frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-1),
				"manifest_synced_counts": "2/3",
			}
		)
		v.update(kw)
		return v

	def test_an_unchanged_vessel_is_not_downloaded(self):
		self.assertIsNone(ms.why_check(self.vessel(), 0))

	def test_reasons_to_download(self):
		self.assertEqual(ms.why_check(self.vessel(manifest_synced_on=None), 0), "first check")
		self.assertEqual(ms.why_check(self.vessel(container_count=2), 0), "allocation counts changed")
		self.assertEqual(ms.why_check(self.vessel(), 1), "no ERP Manifest yet")
		old = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-30)
		self.assertEqual(ms.why_check(self.vessel(manifest_synced_on=old), 0), "daily re-check")

	def test_a_box_seen_or_lost_by_the_container_sync_triggers_a_download(self):
		doc = frappe.new_doc("TANeSW Container")
		doc.update({"container_no": "EEEE0000001", "mrn": MRN, "status": "At Terminal"})
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		self.assertEqual(ms.why_check(self.vessel(), 0), "new box on our B/Ls")
		later = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=5)
		frappe.db.set_value("TANeSW Container", doc.name, "removed_from_allocation_on", later)
		self.assertEqual(
			ms.why_check(self.vessel(manifest_synced_on=frappe.utils.now_datetime()), 0), "box left our B/Ls"
		)

	def test_a_manifest_uploaded_after_the_last_check_triggers_a_download(self):
		self.manifest({"AAAA0000001": "BL1"}, submit=False)
		self.assertEqual(ms.why_check(self.vessel(), 0), "ERP Manifest uploaded")

	# ------------------------------------------------------------------ received here, then moved out
	def test_received_here_then_moved_is_transferred_out_not_back(self):
		"""Carried in by us, then a Simple Transfer to another ICD: an ordinary exit, not a diversion."""

		def ev(when, name, wh):
			return {"prcssDt": when, "cagTrkngPrcssCdNm": name, "wrhsCd": wh, "wrhsCdNm": wh}

		history = [
			ev("2026-11-09 13:59:43", "Carry In Report Approved", "WITZDL019"),
			ev("2026-11-14 13:23:11", "Simple Transfer Declaration Approved", "WITZDL019"),
			ev("2026-11-15 00:14:18", "Carry In Report Approved", "WITZDL032"),
		]
		got = ms.where_it_went(
			{}, history, "WITZDL019", "WITZDL032", frappe.utils.get_datetime("2026-11-09 13:59:43"), {}
		)
		self.assertEqual(got["outcome"], ms.TRANSFERRED_OUT)
		self.assertEqual(str(got["moved_on"]), "2026-11-14 13:23:11")
		self.assertEqual(got["carried_in_at"], "WITZDL032")
		self.assertEqual(
			ms.where_it_went({}, history, "WITZDL019", "WITZDL019", None, {})["outcome"], ms.BACK
		)
		self.assertEqual(ms.where_it_went({}, [], "WITZDL019", "WITZDL046", None, {})["outcome"], ms.TO_ICD)

	def test_a_box_tanesw_saw_us_receive_stays_on_the_manifest(self):
		ms.apply_setters(True)
		self.addCleanup(ms.apply_setters, False)
		name = self.manifest({"AAAA0000001": "BL1", "CCCC0000001": "BL2"})
		doc = frappe.new_doc("TANeSW Container")
		doc.update(
			{
				"container_no": "CCCC0000001",
				"mrn": MRN,
				"status": "Received at ICD",
				"received_on": frappe.utils.now_datetime(),
			}
		)
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		st = self.run_sync({"AAAA0000001": "BL1"}, update_erp_manifests=1)
		self.assertIn("CCCC0000001", self.boxes_on(name))
		# a Simple Transfer after receipt is an ordinary exit of a box that was ours: no allocation change at all
		self.assertIsNone(self.log("CCCC0000001"))
		self.assertEqual((st.removed, st.simple_transfer), (0, 1))

	def test_a_tanesw_phone_is_cleaned_not_lost(self):
		"""'0700 000101/0768' is refused by Frappe's Phone check: the first number is kept."""
		r = frappe._dict(
			consignee_name=CONSIGNEE,
			consignee_tel="0700 000101/0768",
			consignee_tin=None,
			consignee_address=None,
		)
		ms._add_consignees([r])
		self.assertEqual(frappe.db.get_value("Consignee", CONSIGNEE, "consignee_tel"), "0700000101")
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{"reference_name": CONSIGNEE, "content": ["like", "%0700 000101/0768%saved as 0700000101%"]},
			)
		)

	def test_an_unusable_tanesw_phone_does_not_stop_the_update(self):
		"""TANeSW itself holds many phones as '2.55759E+11': the digits are gone, so nothing is guessed."""
		r = frappe._dict(
			consignee_name=CONSIGNEE, consignee_tel="2.55759E+11", consignee_tin=None, consignee_address=None
		)
		ms._add_consignees([r])
		self.assertTrue(frappe.db.exists("Consignee", CONSIGNEE))
		self.assertFalse(frappe.db.get_value("Consignee", CONSIGNEE, "consignee_tel"))

	def test_clean_phone(self):
		for given, kept in (
			("TEL:+243800000001", "+243800000001"),
			("0700 000101/0768", "0700000101"),
			("MOB. 0755-123456", "0755123456"),
			("Tel No: +255 22 200 0000", "+255222000000"),
			("+255 713 000 111, +255 754 000 222", "+255713000111"),
			("0713000111 OR 0754000222", "0713000111"),
			("N/A", None),
			("123", None),
			("", None),
			(None, None),
			("2.55759E+11", None),
			("2.60077E+12", None),
			("2.66E+11", None),
			("2.55256e+14", None),
		):
			self.assertEqual(ms.clean_phone(given), kept, given)
			if kept:
				self.assertTrue(frappe.utils.validate_phone_number(kept), kept)

	def test_a_new_manifest_with_a_bad_phone_is_still_submitted(self):
		"""Consignees are made with the cleaned phone BEFORE icd_tz's submit, so its create_consignees skips them."""
		with (
			patch.object(ms, "port_of", return_value="TEAGTL"),
			patch.object(ms, "_add_consignees", wraps=ms._add_consignees) as made,
		):
			self.run_sync({"AAAA0000001": "BL1"}, auto_create_manifests=1, manifest_create_status="Submitted")
		self.assertTrue(made.called)
		self.assertEqual(frappe.db.get_value("Manifest", ms.erp_manifest(MRN), "docstatus"), 1)

	# ------------------------------------------------------------------ helpers
	def test_where_a_box_went(self):
		self.assertEqual(ms.place_outcome("WITZDL046", "WITZDL019"), ms.TO_ICD)  # another ICD
		self.assertEqual(ms.place_outcome("WTTZDL01C", "WITZDL019"), ms.TO_PORT)  # a port shed
		self.assertEqual(ms.place_outcome("witzdl019", "WITZDL019"), ms.BACK)
		self.assertEqual(ms.place_outcome("", "WITZDL019"), ms.NOT_TRACED)

	def test_setting_switches_the_property_setters(self):
		ms.apply_setters(True)
		self.assertEqual(frappe.get_meta("Manifest").get_field("containers").allow_on_submit, 1)
		ms.apply_setters(False)
		self.assertFalse(frappe.get_meta("Manifest").get_field("containers").allow_on_submit)

	def test_summary_for_the_manifest_card(self):
		name = self.manifest({"AAAA0000001": "BL1", "CCCC0000001": "BL2", "FFFF0000001": "BL2"})
		self.run_sync({"AAAA0000001": "BL1"})
		frappe.db.set_value(
			LOG,
			ms._log_name(MRN, "CCCC0000001", "Removed"),
			{"outcome": ms.TO_ICD, "new_place": "GALCO LIMITED"},
		)
		with patch.object(frappe.db, "get_single_value", return_value=1):
			s = ms.manifest_summary(name)
		self.assertEqual((s["diverted"], s["to_icd"]), (2, 1))
		self.assertEqual(s["places"]["GALCO LIMITED"], 1)
