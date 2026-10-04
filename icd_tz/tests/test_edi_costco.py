# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.edi.costco import COSTCOGenerator, attach_unpacking
from icd_tz.icd_tz.api.edi.interchange import preview
from icd_tz.icd_tz.api.edi.movement import ContainerMovement, from_container_unpacking
from icd_tz.icd_tz.api.edi.templates import COSTCO_VARIABLES
from icd_tz.icd_tz.doctype.container_unpacking.container_unpacking import ContainerUnpacking
from icd_tz.icd_tz.doctype.container_unpacking.test_container_unpacking import (
	make_lcl_manifest,
	make_unpacking,
	receive_lcl_box,
)
from icd_tz.tests.test_edi_codeco import GATE_IN_DEFAULTS, make_partner
from icd_tz.tests.test_edi_movement import CONTAINER_NO, INHERITED_EDI_VALUES, M_BL_NO
from icd_tz.tests.test_storage_contract import set_settings_storage_days

test_ignore = ["Company", "Cost Center"]

UNPACKING_DEFAULTS = {**GATE_IN_DEFAULTS, "is_gate_in": False, "is_empty": True, "weight": None}


class TestCOSTCO(FrappeTestCase):
	"""The stripping report of one container, built from the partner's COSTCO template"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "enable_edi", 1)
		frappe.db.set_single_value("ICD TZ Settings", "icd_un_locode", "TZDAR")
		frappe.db.set_single_value("ICD TZ Settings", "default_sender_id", "TZDARDSEL")
		self.partner = make_partner()

	def tearDown(self):
		frappe.db.rollback()

	def test_the_message_is_a_costco_d95b(self):
		lines = self.lines()

		self.assertTrue(lines[0].startswith("UNB+UNOA:2+TZDARDSEL+CMA+"))
		self.assertTrue(lines[1].endswith("+COSTCO:D:95B:UN'"), lines[1])

	def test_bgm_reports_an_unpacking(self):
		lines = self.lines()
		reference = lines[0].split("+")[-1].rstrip("'")

		self.assertIn(f"BGM+113+{reference}+9'", lines)

	def test_the_box_is_reported_empty_on_import(self):
		self.assertIn("EQD+CN+UACU6042588+45G1:102:5++3+4'", self.lines())

	def test_the_stripping_time_and_place_are_reported(self):
		lines = self.lines()

		self.assertIn("DTM+7:202603032255:203'", lines)
		self.assertIn("LOC+165+TZDAR:139:6+TZDARDSEL:TER:ZZZ'", lines)

	def test_the_master_bill_is_the_consignment(self):
		lines = self.lines()

		self.assertIn("RFF+BM:HLCUTYO250101920'", lines)
		self.assertIn("CNI+1+HLCUTYO250101920'", lines)

	def test_the_consignment_stays_without_a_master_bill(self):
		lines = self.lines(m_bl_no="")

		self.assertIn("CNI+1'", lines)
		self.assertFalse([line for line in lines if line.startswith("RFF+")])

	def test_segment_count_matches_the_body(self):
		lines = self.lines()

		self.assertEqual(int(lines[-2].split("+")[1]), len(lines) - 2)

	def test_the_file_name_carries_the_message_type(self):
		generator = COSTCOGenerator(ContainerMovement(**UNPACKING_DEFAULTS), self.partner)

		self.assertIn("_COSTCO_", generator.get_filename())

	def test_every_documented_value_is_handed_to_the_template(self):
		generator = COSTCOGenerator(ContainerMovement(**UNPACKING_DEFAULTS), self.partner)

		self.assertEqual(sorted(generator.get_context("9")), sorted(COSTCO_VARIABLES))

	def test_a_partner_is_previewed_with_its_message_type(self):
		message = preview(
			ContainerMovement(**UNPACKING_DEFAULTS), COSTCOGenerator, "original", self.partner.name
		)

		self.assertEqual(message["edi_type"], "COSTCO")
		self.assertIn("BGM+113+", message["edi_content"])

	def lines(self, **overrides) -> list[str]:
		movement = ContainerMovement(**{**UNPACKING_DEFAULTS, **overrides})

		return COSTCOGenerator(movement, self.partner).generate().split("\n")


class TestUnpackingEDI(FrappeTestCase):
	"""Submitting a Container Unpacking attaches its COSTCO, like a gate attaches its CODECO"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		frappe.db.set_single_value("ICD TZ Settings", "enable_edi", 1)
		frappe.db.set_single_value("ICD TZ Settings", "icd_un_locode", "TZDAR")
		set_settings_storage_days()
		make_partner().db_set("receiver_cc_email", "ops@example.com")
		make_lcl_manifest()

	def tearDown(self):
		frappe.db.rollback()

	def test_the_movement_is_the_stripped_box(self):
		movement = from_container_unpacking(self.make_unpacking())

		self.assertEqual(movement.container_no, CONTAINER_NO)
		self.assertEqual(movement.m_bl_no, M_BL_NO)
		self.assertEqual(movement.shipping_line_code, "CMA")
		self.assertEqual(movement.vessel_name, "YOKOHAMA STAR")
		self.assertTrue(movement.is_empty)

	def test_submit_attaches_the_costco_for_an_smtp_partner(self):
		unpacking = self.make_unpacking()
		unpacking.submit()

		self.assertTrue(unpacking.edi_file)
		self.assertEqual(unpacking.receiver_email, "edi@example.com")
		self.assertEqual(unpacking.receiver_cc_email, "ops@example.com")
		self.assertIn("BGM+113+", get_file_content(unpacking.edi_file))

	def test_submit_stamps_the_end_time_with_the_posting_date(self):
		# the time the form was opened, or one the clerk typed, gives way to the submit time
		unpacking = self.make_unpacking(end_time="08:00:00")

		with patch(
			f"{ContainerUnpacking.__module__}.now_datetime", return_value=datetime(2026, 10, 4, 14, 30, 15)
		):
			unpacking.submit()

		self.assertEqual(str(unpacking.posting_date), "2026-10-04")
		self.assertEqual(unpacking.end_time, "14:30:15")
		self.assertIn("DTM+7:202610041430:203'", get_file_content(unpacking.edi_file))

	def test_a_line_without_edi_is_unpacked_without_a_file(self):
		frappe.db.set_value("EDI Partner", "CMA", "enable_edi", 0)
		unpacking = self.make_unpacking()
		unpacking.submit()

		self.assertFalse(unpacking.edi_file)

	def test_an_amended_unpacking_drops_the_inherited_recipients(self):
		frappe.db.set_value("EDI Partner", "CMA", "enable_edi", 0)
		unpacking = self.make_unpacking(**INHERITED_EDI_VALUES)

		attach_unpacking(unpacking)

		for fieldname in INHERITED_EDI_VALUES:
			self.assertFalse(unpacking.get(fieldname), fieldname)

	def make_unpacking(self, **values):
		return make_unpacking(receive_lcl_box(), **values)


def get_file_content(file_url: str) -> str:
	return frappe.get_doc("File", {"file_url": file_url}).get_content()
