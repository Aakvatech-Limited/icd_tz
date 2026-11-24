from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tanesw_integration import api, api_client


class TestTANeSWCarryIn(FrappeTestCase):
	def test_list_defaults_date_range_when_omitted(self):
		with patch(
			"tanesw_integration.api.get_carry_in_list", return_value={"wrhsCriList": {"content": []}}
		) as get_list:
			api.carry_in_list(page=0, size=10)
		self.assertTrue(get_list.called)
		args, _ = get_list.call_args
		self.assertIsNotNone(args[0])
		self.assertIsNotNone(args[1])

	def test_list_passes_filters_and_preserves_paging(self):
		payload = {
			"wrhsCriList": {
				"content": [{"crn": "TEST-CRN", "rptStatNm": "NOT REPORT", "wrhsCd": "TEST-WH"}],
				"page": {"number": 0, "totalPages": 1, "totalElements": 1},
			}
		}
		with patch("tanesw_integration.api.get_carry_in_list", return_value=payload) as get_list:
			result = api.carry_in_list("2026-01-01", "2026-01-02", 0, 10, "N,P,Y", "TEST-CNTR", "TEST-CRN")

		get_list.assert_called_once_with("2026-01-01", "2026-01-02", 0, 10, "N,P,Y", "TEST-CNTR", "TEST-CRN")
		self.assertEqual(result["page"]["totalElements"], 1)
		self.assertEqual(result["content"][0]["stsCd"], "NOT REPORT")

	def test_client_uses_composite_identity_for_detail(self):
		with patch("tanesw_integration.api_client._authed_get", return_value={}) as get:
			api_client.get_carry_in_detail("TEST-CRN", "TEST-WH", "TEST-BASE")

		get.assert_called_once_with(
			"/cgm/api/v1/cgme/wrhs/cri/imp/TEST-CRN",
			{"wrhsCd": "TEST-WH", "criBaseNo": "TEST-BASE"},
		)

	def test_vehicle_mode_detail_allows_null_other_collections(self):
		payload = {
			"wrhsCriImp": {
				"content": {
					"crioPrcssUtCd": "V",
					"wrhsCriVhclList": [{"prcssStatCd": "D06"}],
					"wrhsCriCntrList": None,
					"wrhsCriBlList": None,
					"wrhsCriItmList": None,
				}
			}
		}
		with patch("tanesw_integration.api.get_carry_in_detail", return_value=payload):
			result = api.carry_in_detail("TEST-CRN", "TEST-WH", "TEST-BASE")

		self.assertEqual(result["crioPrcssUtCd"], "V")
		self.assertEqual(result["wrhsCriVhclList"][0]["prcssStatCd"], "D06")
		self.assertIsNone(result["wrhsCriCntrList"])

	def test_api_client_register_carry_in(self):
		with patch("tanesw_integration.api_client._authed_post", return_value={"dclrNo": "D123"}) as post:
			res = api_client.register_carry_in({"test": 1})
		post.assert_called_once_with("/cgm/api/v1/cgme/wrhs/cri/imp", {"test": 1}, is_write=True)
		self.assertEqual(res["dclrNo"], "D123")

	def test_api_client_submit_carry_in(self):
		with patch("tanesw_integration.api_client._authed_post", return_value={"status": "D06"}) as post:
			res = api_client.submit_carry_in({"test": 2})
		post.assert_called_once_with("/cgm/api/v1/cgme/wrhs/cri/imp/sbmt", {"test": 2}, is_write=True)
		self.assertEqual(res["status"], "D06")

	def test_api_register_carry_in_guard(self):
		with (
			patch("frappe.get_single", return_value=frappe._dict(enable_write_operations=0)),
			patch("tanesw_integration.test_mode.on", return_value=False),
		):
			with self.assertRaises(frappe.ValidationError):
				api.register_carry_in({"criBaseNo": "TEST-BASE"})

	def test_api_submit_carry_in_guard(self):
		with (
			patch("frappe.get_single", return_value=frappe._dict(enable_write_operations=0)),
			patch("tanesw_integration.test_mode.on", return_value=False),
		):
			with self.assertRaises(frappe.ValidationError):
				api.submit_carry_in({"criBaseNo": "TEST-BASE"})

	def test_api_register_carry_in_success(self):
		with (
			patch("tanesw_integration.api.assert_write_operations_enabled"),
			patch("tanesw_integration.api.client_register_carry_in", return_value={"dclrNo": "D999"}) as reg,
			patch("tanesw_integration.api.import_carry_in_record") as imp,
		):
			res = api.register_carry_in({"criBaseNo": "BASE1", "wrhsCd": "W1"})
			reg.assert_called_once_with({"criBaseNo": "BASE1", "wrhsCd": "W1"})
			self.assertEqual(res["dclrNo"], "D999")
			imp.assert_called_once()

	def test_api_submit_carry_in_success(self):
		with (
			patch("tanesw_integration.api.assert_write_operations_enabled"),
			patch("tanesw_integration.api.client_submit_carry_in", return_value={"dclrNo": "D999"}) as sub,
			patch("tanesw_integration.api.import_carry_in_record") as imp,
		):
			api.submit_carry_in({"criBaseNo": "BASE1", "wrhsCd": "W1"})
			sub.assert_called_once_with({"criBaseNo": "BASE1", "wrhsCd": "W1"})
			imp.assert_called_once()
