# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.utils import validate_no_draft_container_records
from icd_tz.icd_tz.doctype.gate_pass.gate_pass import GatePass
from icd_tz.icd_tz.doctype.gate_pass.test_gate_pass import make_container
from icd_tz.icd_tz.doctype.service_order.service_order import ServiceOrder

test_ignore = ["Company", "Cost Center"]


def make_record(doctype, container, docstatus=0):
	record = frappe.get_doc(
		{
			"doctype": doctype,
			"container_id": container.name,
			"container_no": container.container_no,
			"docstatus": docstatus,
		}
	)
	record.set_new_name()
	record.db_insert()
	return record.name


class TestDraftContainerRecords(FrappeTestCase):
	"""A container does not move on while its booking or inspection is still a draft"""

	def tearDown(self):
		frappe.db.rollback()

	def test_no_drafts_lets_the_container_through(self):
		container = make_container()
		make_record("In Yard Container Booking", container, docstatus=1)
		make_record("Container Inspection", container, docstatus=2)

		validate_no_draft_container_records(container.name, container.container_no)

	def test_draft_booking_or_inspection_blocks(self):
		for doctype, container_no in (
			("In Yard Container Booking", "GPTU1111111"),
			("Container Inspection", "GPTU2222222"),
		):
			with self.subTest(doctype=doctype):
				container = make_container(container_no=container_no)
				draft = make_record(doctype, container)

				with self.assertRaises(frappe.ValidationError) as error:
					validate_no_draft_container_records(container.name, container.container_no)

				self.assertIn(draft, str(error.exception))

	def test_draft_of_another_container_is_ignored(self):
		container = make_container()
		make_record("Container Inspection", make_container(container_no="GPTU7654321"))

		validate_no_draft_container_records(container.name, container.container_no)

	def test_submit_runs_the_draft_check(self):
		for controller, doctype, next_check, container_no in (
			(GatePass, "Gate Pass", "validate_pending_payments", "GPTU3333333"),
			(ServiceOrder, "Service Order", "validate_mandatory_fields", "GPTU4444444"),
		):
			with self.subTest(doctype=doctype):
				container = make_container(container_no=container_no)
				make_record("In Yard Container Booking", container)
				document = frappe.get_doc(
					{
						"doctype": doctype,
						"container_id": container.name,
						"container_no": container.container_no,
					}
				)

				with (
					patch.object(controller, next_check) as later_check,
					self.assertRaises(frappe.ValidationError),
				):
					document.before_submit()

				later_check.assert_not_called()
