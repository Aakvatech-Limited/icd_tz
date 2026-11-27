from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from tanesw_integration import api_client


class TestTANeSWDeclaration(FrappeTestCase):
	"""New Declaration flow — Usable Cargo to ICD List (screen cgme0301003q)."""

	def test_client_usable_cargo_uses_prefixed_search_parameters(self):
		with patch("tanesw_integration.api_client._authed_get", return_value={}) as get:
			api_client.search_usable_cargo("2026-09-27", "2026-11-27", "C", " 26BFL000033 ", 0, 10)

		get.assert_called_once_with(
			"/cgm/api/v1/cgme/trsf/icd/dcla/trgt",
			{
				"page": 0,
				"size": 10,
				"srchArvlDtFrom": "2026-09-27",
				"srchArvlDtTo": "2026-11-27",
				"srchCagTp": "C",
				"srchMrn": "26BFL000033",
			},
		)

	def test_client_declaration_template_hits_singular_route(self):
		with patch("tanesw_integration.api_client._authed_get", return_value={}) as get:
			api_client.get_declaration_template(" 26BFL000033 ")

		get.assert_called_once_with("/cgm/api/v1/cgme/trsf/icd/dcla/trgt/26BFL000033")

	def test_client_available_containers_uses_trgt_cntr_route(self):
		with patch("tanesw_integration.api_client._authed_get", return_value={}) as get:
			api_client.get_available_containers("26AFS000007", "", "26AFS0000070000000", "CDD", "N", 0, 10)

		get.assert_called_once_with(
			"/cgm/api/v1/cgme/trsf/icd/dcla/trgt/cntr",
			{
				"page": 0,
				"size": 10,
				"mrn": "26AFS000007",
				"cagDclrTpCd": "CDD",
				"isBulk": "N",
				"crn": "26AFS0000070000000",
			},
		)


def frappe_days_between(start, end):
	from frappe.utils import date_diff

	return date_diff(end, start)
