import unicodedata
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from frappe.tests.utils import FrappeTestCase

from tanesw_integration import api, api_client, cargo


class TestTANeSWManifest(FrappeTestCase):
	def test_client_manifest_list_uses_blank_mrn_search_parameters(self):
		with patch("tanesw_integration.api_client._authed_get", return_value={}) as get:
			api_client.get_manifest_list("2026-10-26", "2026-11-02", page=0, size=10)

		get.assert_called_once_with(
			"/cgm/api/v1/cgme/mnfs/imp/imp-mnfs/info",
			{
				"page": 0,
				"size": 10,
				"srchDtFrom": "2026-10-26",
				"srchDtTo": "2026-11-02",
				"trptModeCd": "10",
				"srchTp": "mrn",
			},
		)

	def test_client_manifest_list_sends_mrn_when_provided(self):
		with patch("tanesw_integration.api_client._authed_get", return_value={}) as get:
			api_client.get_manifest_list("2026-10-26", "2026-11-02", " 26SFS000198 ", 1, 10)

		self.assertEqual(get.call_args.args[1]["srchTpCn"], "26SFS000198")

	def test_manifest_list_defaults_dates_and_preserves_paging(self):
		payload = {
			"impMnfsLst": {
				"content": [{"mrn": "26SFS000198", "vsslNm": "MINTAKA"}],
				"page": {"number": 0, "totalPages": 2, "totalElements": 13, "size": 10},
			}
		}
		with patch("tanesw_integration.api.get_manifest_list", return_value=payload) as get_list:
			result = api.manifest_list(page=0, size=10)

		args = get_list.call_args.args
		self.assertTrue(args[0])
		self.assertTrue(args[1])
		self.assertEqual(args[2:], (None, 0, 10))
		self.assertEqual(result["content"][0]["mrn"], "26SFS000198")
		self.assertEqual(result["page"]["totalElements"], 13)

	def test_client_manifest_bl_list_uses_native_detail_parameters(self):
		with patch("tanesw_integration.api_client._authed_get", return_value={}) as get:
			api_client.get_bl_list("26SFS000198", page=2, size=10)

		get.assert_called_once_with(
			"/cgm/api/v1/cgme/mnfs/imp/imp-mnfs/mrn",
			{
				"mrn": "26SFS000198",
				"trptModeCd": "10",
				"page": 2,
				"size": 10,
			},
		)

	def test_manifest_detail_returns_header_and_native_bl_paging(self):
		header = {"mrn": "26SFS000198", "vsslNm": "MINTAKA", "vygNo": "2610"}
		bls = {
			"impMnfsBlLst": {
				"content": [{"msn": "0001", "mblNo": "837MNK1", "blAudtStatCd": "AP"}],
				"page": {"number": 0, "size": 10, "totalElements": 71, "totalPages": 8},
			}
		}
		with (
			patch("tanesw_integration.api.get_manifest", return_value={"impMnfsMrn": {"content": header}}),
			patch("tanesw_integration.api.get_bl_list", return_value=bls),
		):
			result = api.manifest_detail("26SFS000198", page=0, size=10)

		self.assertEqual(result["manifest"]["vsslNm"], "MINTAKA")
		self.assertEqual(result["content"][0]["mblNo"], "837MNK1")
		self.assertEqual(result["page"]["totalElements"], 71)

	def test_our_facility_filter_keeps_only_matching_bls(self):
		page = {
			"impMnfsBlLst": {
				"content": [
					{"mblNo": "A1", "dlvrPlcCd": "WITZDL019", "cntrCnt": 2},
					{"mblNo": "A2", "dlvrPlcCd": "WITZDL025", "cntrCnt": 5},
					{"mblNo": "A3", "dlvrPlcCd": " witzdl019 ", "cntrCnt": 1},
				],
				"page": {"totalPages": 1, "totalElements": 3},
			}
		}
		with patch("tanesw_integration.api.get_bl_list", return_value=page):
			bls = api._our_bls("26SFS000198", "WITZDL019")

		self.assertEqual([b["mblNo"] for b in bls], ["A1", "A3"])

	def test_manifest_list_only_our_facility_drops_manifests_without_our_bls(self):
		payload = {
			"impMnfsLst": {
				"content": [{"mrn": "OUR1"}, {"mrn": "OTHER"}, {"mrn": "OUR2"}],
				"page": {"number": 0, "size": 3, "totalElements": 3, "totalPages": 1},
			}
		}

		def summary(mrn, code):
			return {
				"our_bl_count": 4 if mrn.startswith("OUR") else 0,
				"our_cntr_count": 6 if mrn.startswith("OUR") else 0,
			}

		with (
			patch("tanesw_integration.api.get_manifest_list", return_value=payload),
			patch("tanesw_integration.api._our_bl_summary", side_effect=summary),
		):
			result = api.manifest_list("2026-10-01", "2026-10-07", only_our_facility=1)

		self.assertEqual([row["mrn"] for row in result["content"]], ["OUR1", "OUR2"])
		# coverage is reported against the window, matches are counted by the UI
		self.assertEqual(result["total_manifests"], 3)
		self.assertEqual(result["scanned"], 3)
		self.assertFalse(result["has_more"])
		self.assertEqual(result["facility_code"], "WITZDL019")

	def test_manifest_detail_only_our_facility_pages_filtered_bls(self):
		bls = [{"mblNo": f"B{i}", "dlvrPlcCd": "WITZDL019", "cntrCnt": 1} for i in range(12)]
		with (
			patch("tanesw_integration.api.get_manifest", return_value={}),
			patch("tanesw_integration.api._our_bls", return_value=bls),
		):
			result = api.manifest_detail("26SFS000198", page=1, size=10, only_our_facility=1)

		self.assertEqual(result["our_bl_count"], 12)
		self.assertEqual(result["our_cntr_count"], 12)
		self.assertEqual(len(result["content"]), 2)
		self.assertEqual(result["page"]["totalPages"], 2)

	def test_client_transfers_uses_honoured_filter_names(self):
		with patch("tanesw_integration.api_client._authed_get", return_value={}) as get:
			api_client.search_transfers(
				"26SML000006",
				"2026-10-01",
				"2026-10-31",
				0,
				100,
				dclr_no="WITZDL0192026C0007118",
				cntr_no="FCIU6535102",
				dptr_wrhs_cd="WTTZDL008",
			)

		params = get.call_args.args[1]
		# the names TANeSW actually filters on — srchDtStrt/srchDtEnd are ignored upstream
		self.assertEqual(params["srchDtTpFrom"], "2026-10-01")
		self.assertEqual(params["srchDtTpTo"], "2026-10-31")
		self.assertEqual(params["srchMrn"], "26SML000006")
		self.assertEqual(params["srchDclrNo"], "WITZDL0192026C0007118")
		self.assertEqual(params["srchCntrNo"], "FCIU6535102")
		self.assertEqual(params["srchDptrWrhsCd"], "WTTZDL008")
		self.assertNotIn("srchDtStrt", params)
		self.assertNotIn("mrn", params)

	def test_manifest_list_declared_source_pages_the_declared_set(self):
		"""Declared mode pages the ARRIVAL-filtered intersection, not the raw declared set."""
		declared = {
			"26AAA000001": {
				"decl_count": 2,
				"containers": 3,
				"last_status": "D06",
				"last_prcss_dtm": "2026-10-02 10:00:00",
			},
			"26BBB000002": {
				"decl_count": 1,
				"containers": 1,
				"last_status": "A01",
				"last_prcss_dtm": "2026-10-05 10:00:00",
			},
			"26CCC000003": {
				"decl_count": 4,
				"containers": 5,
				"last_status": "D06",
				"last_prcss_dtm": "2026-10-06 10:00:00",
			},
		}
		manifests = {
			"impMnfsLst": {
				"content": [
					{"mrn": "26AAA000001", "actlArvlDt": "2026-10-02 00:00:00"},
					{"mrn": "26BBB000002", "actlArvlDt": "2026-10-05 00:00:00"},
					{"mrn": "26CCC000003", "actlArvlDt": "2026-10-06 00:00:00"},
				],
				"page": {"number": 0, "totalPages": 1, "totalElements": 3},
			}
		}
		with (
			patch("tanesw_integration.api._declared_mrns", return_value=declared),
			patch("tanesw_integration.api.get_manifest_list", return_value=manifests),
		):
			result = api.manifest_list(
				"2026-10-01", "2026-10-07", only_our_facility=1, source="declared", page=0, size=2
			)

		self.assertEqual(result["source"], "declared")
		self.assertEqual(result["page"]["totalElements"], 3)
		self.assertEqual(len(result["content"]), 2)
		# arrival desc, and the aggregate rides along
		self.assertEqual([row["mrn"] for row in result["content"]], ["26CCC000003", "26BBB000002"])
		self.assertEqual(result["content"][1]["decl_count"], 1)

		with (
			patch("tanesw_integration.api._declared_mrns", return_value=declared),
			patch("tanesw_integration.api.get_manifest_list", return_value=manifests),
		):
			page2 = api.manifest_list(
				"2026-10-01", "2026-10-07", only_our_facility=1, source="declared", page=1, size=2
			)
		self.assertEqual([row["mrn"] for row in page2["content"]], ["26AAA000001"])

	def test_declared_mode_filters_by_vessel_arrival_window(self):
		"""A manifest declared in-window but arriving outside it must not appear."""
		declared = {
			"26PIL000023": {
				"decl_count": 7,
				"containers": 7,
				"last_status": "D06",
				"last_prcss_dtm": "2026-10-20",
			},
			"26SML000006": {
				"decl_count": 26,
				"containers": 27,
				"last_status": "D06",
				"last_prcss_dtm": "2026-10-24",
			},
		}
		manifests = {
			"impMnfsLst": {
				"content": [
					{"mrn": "26SML000006", "vsslNm": "GFS PEARL", "actlArvlDt": "2026-10-13 00:00:00"}
				],
				"page": {"number": 0, "totalPages": 1, "totalElements": 1},
			}
		}
		with (
			patch("tanesw_integration.api._declared_mrns", return_value=declared),
			patch("tanesw_integration.api.get_manifest_list", return_value=manifests),
		):
			result = api.manifest_list(
				"2026-10-27", "2026-11-03", only_our_facility=1, source="declared", size=20
			)

		self.assertEqual(result["page"]["totalElements"], 1)
		self.assertEqual([r["mrn"] for r in result["content"]], ["26SML000006"])
		# the arrival date shown comes from the manifest list, not the declaration
		self.assertEqual(result["content"][0]["actlArvlDt"], "2026-10-13")
		self.assertEqual(result["content"][0]["decl_count"], 26)

	def test_declared_mode_scans_declarations_over_padded_window(self):
		"""Declarations are filed around the arrival date, so the lookup is padded."""
		with (
			patch("tanesw_integration.api._declared_mrns", return_value={}) as decl,
			patch("tanesw_integration.api.get_manifest_list", return_value={"impMnfsLst": {}}),
		):
			api.manifest_list("2026-10-27", "2026-11-03", only_our_facility=1, source="declared")

		scan_from, scan_to = decl.call_args.args[0], decl.call_args.args[1]
		self.assertEqual(scan_from, "2026-08-28")
		self.assertEqual(scan_to, "2027-01-02")

	def test_declared_mode_sorts_by_arrival_descending(self):
		declared = {
			m: {"decl_count": 1, "containers": 1, "last_status": "D06", "last_prcss_dtm": "2026-10-20"}
			for m in ("26MAE000061", "26PIL000021", "26MAE000058")
		}
		manifests = {
			"impMnfsLst": {
				"content": [
					{"mrn": "26PIL000021", "actlArvlDt": "2026-10-03 00:00:00"},
					{"mrn": "26MAE000061", "actlArvlDt": "2026-10-11 00:00:00"},
					{"mrn": "26MAE000058", "actlArvlDt": "2026-10-01 00:00:00"},
				],
				"page": {"totalPages": 1},
			}
		}
		with (
			patch("tanesw_integration.api._declared_mrns", return_value=declared),
			patch("tanesw_integration.api.get_manifest_list", return_value=manifests),
		):
			result = api.manifest_list(
				"2026-10-01", "2026-10-27", only_our_facility=1, source="declared", size=10
			)

		self.assertEqual(
			[r["actlArvlDt"] for r in result["content"]], ["2026-10-11", "2026-10-03", "2026-10-01"]
		)

	def _all_mode_payload(self):
		manifests = {
			"impMnfsLst": {
				"content": [
					{"mrn": "26SML000006", "vsslNm": "GFS PEARL", "actlArvlDt": "2026-10-13 00:00:00"},
					{"mrn": "26MSC000142", "vsslNm": "MSC SKY II", "actlArvlDt": "2026-10-13 00:00:00"},
					{"mrn": "26XXX000001", "vsslNm": "NOT OURS", "actlArvlDt": "2026-10-12 00:00:00"},
					{"mrn": "26ASE000050", "vsslNm": "JOLLY ARGENTO", "actlArvlDt": "2026-10-15 00:00:00"},
				],
				"page": {"totalPages": 1, "totalElements": 4},
			}
		}
		summaries = {
			"26SML000006": {"our_bl_count": 17, "our_cntr_count": 28},
			"26MSC000142": {"our_bl_count": 10, "our_cntr_count": 12},
			"26XXX000001": {"our_bl_count": 0, "our_cntr_count": 0},
			"26ASE000050": {"our_bl_count": 0, "our_cntr_count": 0},
		}
		declared = {
			"26SML000006": {"decl_count": 26, "containers": 27, "last_status": "D06"},
			"26ASE000050": {"decl_count": 2, "containers": 3, "last_status": "D06"},
		}
		return manifests, summaries, declared

	def test_all_mode_unions_bl_allocation_and_declarations(self):
		manifests, summaries, declared = self._all_mode_payload()
		with (
			patch("tanesw_integration.api.get_manifest_list", return_value=manifests),
			patch("tanesw_integration.api._our_bl_summaries", return_value=summaries),
			patch("tanesw_integration.api._declared_mrns", return_value=declared),
		):
			result = api.manifest_list(
				"2026-10-11", "2026-10-15", only_our_facility=1, source="all", page=0, size=25
			)

		self.assertEqual(result["source"], "all")
		self.assertEqual(result["scanned"], 4)
		by_mrn = {r["mrn"]: r for r in result["content"]}
		# not ours at all
		self.assertNotIn("26XXX000001", by_mrn)
		# allocated + declared
		self.assertEqual((by_mrn["26SML000006"]["allocated"], by_mrn["26SML000006"]["declared"]), (1, 1))
		self.assertEqual(by_mrn["26SML000006"]["our_cntr_count"], 28)
		self.assertEqual(by_mrn["26SML000006"]["decl_count"], 26)
		# allocated only: B/Ls say ours, no declaration yet
		self.assertEqual((by_mrn["26MSC000142"]["allocated"], by_mrn["26MSC000142"]["declared"]), (1, 0))
		# declared only: paperwork exists, B/L allocation does not — the discrepancy case
		self.assertEqual((by_mrn["26ASE000050"]["allocated"], by_mrn["26ASE000050"]["declared"]), (0, 1))

	def test_all_mode_is_arrival_ordered(self):
		manifests, summaries, declared = self._all_mode_payload()
		with (
			patch("tanesw_integration.api.get_manifest_list", return_value=manifests),
			patch("tanesw_integration.api._our_bl_summaries", return_value=summaries),
			patch("tanesw_integration.api._declared_mrns", return_value=declared),
		):
			result = api.manifest_list(
				"2026-10-11", "2026-10-15", only_our_facility=1, source="all", page=0, size=25
			)

		self.assertEqual(
			[r["actlArvlDt"] for r in result["content"]], ["2026-10-15", "2026-10-13", "2026-10-13"]
		)

	def test_bl_summary_handles_empty_and_single(self):
		rows = [
			{"dlvrPlcCd": "WITZDL019", "cntrCnt": 2},
			{"dlvrPlcCd": "witzdl019 ", "cntrCnt": 1},
			{"dlvrPlcCd": "WITZDL046", "cntrCnt": 9},
		]
		with (
			patch("tanesw_integration.api._cached_summary", return_value=None),
			patch("tanesw_integration.api._iter_bls", return_value=iter(rows)) as read,
		):
			self.assertEqual(api._our_bl_summaries([], "WITZDL019"), {})
			one = api._our_bl_summaries(["26SML000006", "26SML000006"], "WITZDL019")
		self.assertEqual(one["26SML000006"], {"our_bl_count": 2, "our_cntr_count": 3})
		self.assertEqual(read.call_count, 1)

	def test_workers_send_http_only_never_open_a_frappe_context(self):
		"""Review #27: parallel reads add no database connection; the request's thread does the rest."""
		page = {
			"impMnfsBlLst": {"content": [{"dlvrPlcCd": "WITZDL019", "cntrCnt": 4}], "page": {"totalPages": 1}}
		}
		resp = MagicMock(status_code=200)
		resp.json.return_value = page
		with (
			patch("tanesw_integration.api._cached_summary", return_value=None),
			patch("tanesw_integration.api.plain_request_args", return_value=("https://x", {}, 5, True)),
			patch("requests.Session.get", return_value=resp),
			patch("tanesw_integration.api.frappe.init") as init,
			patch("tanesw_integration.api.frappe.connect") as connect,
			patch("tanesw_integration.api._iter_bls") as normal_read,
		):
			result = api._our_bl_summaries(["MRN-1", "MRN-2"], "WITZDL019", workers=2)
		self.assertEqual(
			result,
			{
				"MRN-1": {"our_bl_count": 1, "our_cntr_count": 4},
				"MRN-2": {"our_bl_count": 1, "our_cntr_count": 4},
			},
		)
		init.assert_not_called()
		connect.assert_not_called()
		normal_read.assert_not_called()

	def test_a_worker_failure_is_read_again_the_normal_way(self):
		with (
			patch("tanesw_integration.api._cached_summary", return_value=None),
			patch("tanesw_integration.api.plain_request_args", return_value=("https://x", {}, 5, True)),
			patch("tanesw_integration.api._fetch_bl_rows", side_effect=[None, []]),
			patch(
				"tanesw_integration.api._iter_bls", return_value=iter([{"dlvrPlcCd": "WITZDL019"}])
			) as normal,
		):
			result = api._our_bl_summaries(["MRN-1", "MRN-2"], "WITZDL019", workers=2)
		self.assertEqual(normal.call_count, 1)
		self.assertEqual(result["MRN-1"]["our_bl_count"] + result["MRN-2"]["our_bl_count"], 1)

	def test_zip10_single_scan_failure_is_explicit(self):
		with (
			patch("tanesw_integration.api._cached_summary", return_value=None),
			patch("tanesw_integration.api._iter_bls", side_effect=RuntimeError("TANeSW unavailable")),
			patch("tanesw_integration.api.frappe.log_error"),
			patch("tanesw_integration.api.frappe.get_traceback", return_value="trace"),
			patch("tanesw_integration.api.frappe.clear_messages") as clear_messages,
		):
			result = api._our_bl_summaries(["MRN-FAIL"], "WITZDL019")

		self.assertEqual(result, {"MRN-FAIL": {"scan_failed": 1}})
		clear_messages.assert_called_once_with()

	def test_zip10_manifest_filter_separates_unverified_scans(self):
		rows = [
			{"mrn": "OUR", "vsslNm": "OUR VESSEL", "actlArvlDt": "2026-11-01"},
			{"mrn": "OTHER", "vsslNm": "OTHER VESSEL", "actlArvlDt": "2026-11-02"},
			{"mrn": "FAILED", "vsslNm": "FAILED VESSEL", "actlArvlDt": "2026-11-03"},
		]
		summaries = {
			"OUR": {"our_bl_count": 2, "our_cntr_count": 3},
			"OTHER": {"our_bl_count": 0, "our_cntr_count": 0},
			"FAILED": {"scan_failed": 1},
		}
		xptd = [{"mrn": "OUR", "trgtCnt": "4", "dclrCnt": "2"}]
		with (
			patch("tanesw_integration.cargo._all_pages", side_effect=[rows, xptd]),
			patch("tanesw_integration.api._our_facility_code", return_value="WITZDL019"),
			patch("tanesw_integration.api._our_bl_summaries", return_value=summaries),
		):
			result = cargo.manifest_info_list("2026-11-01", "2026-11-07", our_only="cntr")

		self.assertEqual(result["basis"], "ours")
		self.assertEqual([row["mrn"] for row in result["content"]], ["OUR"])
		self.assertEqual(result["content"][0]["our_trgt_count"], 4)
		self.assertEqual(
			result["unverified"], [{"mrn": "FAILED", "vsslNm": "FAILED VESSEL", "arvlDt": "2026-11-03"}]
		)
		self.assertEqual(result["verified"], 2)
		self.assertFalse(result["complete"])

	def test_zip10_manifest_ui_contract(self):
		source = (
			Path(cargo.__file__).parent / "tanesw_integration/page/tanesw_cargo/tanesw_cargo.js"
		).read_text(encoding="utf-8")

		self.assertIn('__("Our Cargo")', source)
		self.assertIn('__("All Port Manifests")', source)
		self.assertIn("const unv = (res && res.unverified) || [];", source)
		self.assertIn('__("Check again")', source)
		self.assertIn('$h.find(".ji-retry").on("click", reload);', source)
		non_ascii_symbols = sorted(
			{char for char in source if ord(char) > 127 and unicodedata.category(char).startswith("S")}
		)
		self.assertEqual(non_ascii_symbols, [])
