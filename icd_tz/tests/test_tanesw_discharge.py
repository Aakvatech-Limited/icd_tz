# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from icd_tz.icd_tz.api import tanesw

M_BL_NO = "ONEYTA4DJA390900"
CRN = "25PIL0000060735"
BOXES = ("BEAU5429741", "CAIU9904891", "FDCU0533798")
DISCHARGE_DATES = {
	"BEAU5429741": "2025-03-09 12:49:38",
	"CAIU9904891": "2025-03-07 17:33:25",
	# FDCU0533798 has no approved discharge report yet
}


class FakeTracking:
	"""Stands in for the TANeSW endpoints and counts what was asked of them"""

	def __init__(self, containers=BOXES, crns=(CRN,)):
		self.containers = containers
		self.crns = crns
		self.calls = []

	def __call__(self, path, params):
		self.calls.append(path)

		if path == "srch":
			return {"trkngDtl": {"content": [self.get_bill_row(crn) for crn in self.crns]}}

		return {"trkngCntrDtl": {"content": self.get_container_row(params.get("srchCntrNo"))}}

	def get_bill_row(self, crn):
		return {
			"crn": crn,
			"blNo": M_BL_NO,
			# the API returns the container list of a bill but never its events
			"blCntrLst": [{"cntrNo": box, "cntrPrcssLst": []} for box in self.containers],
			"blPrcssLst": [{"cagTrkngPrcssCd": "B12", "prcssDt": "2025-03-09 12:49:38"}],
		}

	def get_container_row(self, container_no):
		events = [{"cagTrkngPrcssCd": "C01", "prcssDt": "2025-03-12 11:01:59"}]
		if container_no in DISCHARGE_DATES:
			events.append({"cagTrkngPrcssCd": "B21", "prcssDt": DISCHARGE_DATES[container_no]})

		return {"cntrNo": container_no, "cntrPrcssLst": events}

	def count(self, path):
		return self.calls.count(path)


class TestTaneswDischarge(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_a_bill_is_searched_once_however_many_containers(self):
		"""What the background job does: resolve the bill once, then ask per container"""

		boxes = [f"TEST{n:07d}" for n in range(10)]
		fake = FakeTracking(containers=boxes)

		with patch.object(tanesw, "call_tracking_api", fake):
			crns = tanesw.get_bill_crns(M_BL_NO)
			for box in boxes:
				tanesw.get_discharge_date(box, M_BL_NO, crns=crns)

		self.assertEqual(fake.count("srch"), 1)
		self.assertEqual(fake.count("cntr-dtl"), 10)

	def test_each_container_gets_its_own_discharge_date(self):
		fake = FakeTracking()

		with patch.object(tanesw, "call_tracking_api", fake):
			crns = tanesw.get_bill_crns(M_BL_NO)
			dates = {box: tanesw.get_discharge_date(box, M_BL_NO, crns=crns) for box in BOXES}

		self.assertEqual(dates["BEAU5429741"], getdate("2025-03-09"))
		self.assertEqual(dates["CAIU9904891"], getdate("2025-03-07"))

	def test_a_container_with_no_approved_discharge_gets_nothing(self):
		fake = FakeTracking()

		with patch.object(tanesw, "call_tracking_api", fake):
			self.assertIsNone(tanesw.get_discharge_date("FDCU0533798", M_BL_NO))

	def test_the_bill_level_event_is_never_used_as_a_container_date(self):
		"""B12 is the last container discharged on the bill, not each container's own date"""

		fake = FakeTracking()

		with patch.object(tanesw, "call_tracking_api", fake):
			discharge_date = tanesw.get_discharge_date("CAIU9904891", M_BL_NO)

		self.assertEqual(discharge_date, getdate("2025-03-07"))
		self.assertNotEqual(discharge_date, getdate("2025-03-09"))

	def test_a_known_cargo_reference_skips_the_search_call(self):
		fake = FakeTracking()

		with patch.object(tanesw, "call_tracking_api", fake):
			discharge_date = tanesw.get_discharge_date("BEAU5429741", M_BL_NO, crns=[CRN])

		self.assertEqual(fake.count("srch"), 0)
		self.assertEqual(fake.count("cntr-dtl"), 1)
		self.assertEqual(discharge_date, getdate("2025-03-09"))

	def test_an_incomplete_request_asks_for_nothing(self):
		"""A container number alone matches several shipments, so it is not enough"""

		fake = FakeTracking()

		with patch.object(tanesw, "call_tracking_api", fake):
			self.assertIsNone(tanesw.get_discharge_date("", M_BL_NO))
			self.assertIsNone(tanesw.get_discharge_date("BEAU5429741", ""))

		self.assertEqual(fake.calls, [])

	def test_a_container_is_searched_under_every_cargo_reference_of_its_bill(self):
		fake = FakeTracking(containers=["BEAU5429741"], crns=("CRN-A", "CRN-B"))

		with patch.object(tanesw, "call_tracking_api", fake):
			discharge_date = tanesw.get_discharge_date("BEAU5429741", M_BL_NO)

		self.assertEqual(discharge_date, getdate("2025-03-09"))
		self.assertEqual(fake.count("srch"), 1)

	def test_a_failed_lookup_returns_nothing_instead_of_raising(self):
		with patch.object(tanesw, "call_tracking_api", lambda path, params: None):
			self.assertIsNone(tanesw.get_discharge_date("BEAU5429741", M_BL_NO))
			self.assertEqual(tanesw.get_bill_crns(M_BL_NO), [])

	def test_one_match_is_read_the_same_as_many(self):
		"""The API answers a single match with a dict and several with a list"""

		self.assertEqual(tanesw.get_rows({"content": {"cntrNo": "X"}}), [{"cntrNo": "X"}])
		self.assertEqual(tanesw.get_rows({"content": [{"cntrNo": "X"}]}), [{"cntrNo": "X"}])
		self.assertEqual(tanesw.get_rows(None), [])
