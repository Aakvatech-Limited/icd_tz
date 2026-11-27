from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import api, api_client


class TestTANeSWBooking(FrappeTestCase):
	# These tests flip "Enable Write Operations". They used to COMMIT 0 to the real site, which silently
	# switched writes off for everyone (no Version entry). Now the original value is put back after each test.
	def setUp(self):
		self._ewo = frappe.db.get_single_value("TANeSW Settings", "enable_write_operations")

	def tearDown(self):
		frappe.db.set_single_value("TANeSW Settings", "enable_write_operations", self._ewo or 0)

	def test_booking_detail_combines_bkng_and_approval_info(self):
		bkng_payload = {
			"result": {
				"content": {
					"tansadNo": "TZDL261750076",
					"jntInscBkngInfo": {"prcsStatCd": "B", "blNo": "AMIGL260452838A"},
					"tansadInfo": {"cstmOfceCd": "TZDL", "sltvRsltCd": "R"},
				}
			}
		}
		app_bkng_payload = {"appBkngInfo": {"content": {"cagBkngYn": "Y", "godsLoctWrhsCd": "WITZDL019"}}}
		app_aprv_payload = {
			"appAprvInfo": {"content": {"prcssStatCd": "AP", "prcssRsnCn": "done", "rmrk": "ok"}}
		}
		with (
			patch("tanesw_integration.api.get_booking_detail", return_value=bkng_payload),
			patch("tanesw_integration.api.get_booking_app_info", return_value=app_bkng_payload),
			patch("tanesw_integration.api.get_booking_approval_info", return_value=app_aprv_payload),
		):
			res = api.booking_detail("TZDL261750076")

		self.assertEqual(res["tansadNo"], "TZDL261750076")
		self.assertEqual(res["appBkngInfo"]["cagBkngYn"], "Y")
		self.assertEqual(res["appAprvInfo"]["prcssStatCd"], "AP")

	def test_save_booking_approval_fails_closed_when_writes_disabled(self):
		frappe.db.set_single_value("TANeSW Settings", "enable_write_operations", 0)

		with self.assertRaises(frappe.ValidationError):
			api.save_booking_approval_result({"test": 1})

	def test_submit_booking_approval_fails_closed_when_writes_disabled(self):
		frappe.db.set_single_value("TANeSW Settings", "enable_write_operations", 0)

		with self.assertRaises(frappe.ValidationError):
			api.submit_booking_approval_result({"test": 1})

	def test_save_booking_approval_executes_when_writes_enabled(self):
		frappe.db.set_single_value("TANeSW Settings", "enable_write_operations", 1)

		try:
			with patch(
				"tanesw_integration.api.client_save_booking_approval", return_value={"status": 201}
			) as mock_save:
				res = api.save_booking_approval_result({"esweComnAsnmtRDto": {}})
				self.assertEqual(res, {"status": 201})
				mock_save.assert_called_once()
		finally:
			pass

	def test_booking_list_uses_tanesw_search_parameters(self):
		with patch("tanesw_integration.api_client._authed_get", return_value={}) as get:
			api_client.get_booking_list(
				"2026-09-26",
				"2026-10-26",
				"WITZDL019",
				0,
				10,
				tansad_no="TZDL-26-0000001",
				reference_no="100000001-26-0000001",
				status="B",
			)

		get.assert_called_once_with(
			"/esw/api/v1/eswe/jnt/insc/bkng",
			{
				"srchDtStrt": "2026-09-26",
				"srchDtEnd": "2026-10-26",
				"srchWrhsCd": "WITZDL019",
				"cstmOfceCd": "TZDL",
				"tansadYy": "26",
				"tansadSrno": "0000001",
				"reffTin": "100000001",
				"reffYy": "26",
				"reffSrno": "0000001",
				"srchStatCd": "B",
				"page": 0,
				"size": 10,
			},
		)

	def test_booking_list_preserves_server_pagination(self):
		payload = {
			"jntInscBkngList": {
				"content": [
					{
						"tansadNo": "TZDL260000001",
						"reffTin": "100000001",
						"reffYy": "26",
						"reffSrno": "0000001",
					}
				],
				"page": {"size": 10, "totalElements": 368, "totalPages": 37, "number": 0},
			}
		}
		with patch("tanesw_integration.api.get_booking_list", return_value=payload):
			result = api.booking_list(page=0, size=10)

		self.assertEqual(result["page"]["totalElements"], 368)
		self.assertEqual(result["content"][0]["referenceNo"], "100000001-26-0000001")
