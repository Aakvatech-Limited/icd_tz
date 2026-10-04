# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from icd_tz.icd_tz.api.edi.codeco import attach_gate_in
from icd_tz.icd_tz.api.edi.delivery import (
	GATE_OUT_CONFIRMED,
	RETRY_DAYS,
	get_due_filters,
	get_receiver_id,
	queue_delivery,
	retry_failed_deliveries,
	send_edi_file,
)
from icd_tz.icd_tz.doctype.edi_partner.edi_partner import EDIPartner
from icd_tz.icd_tz.doctype.gate_pass.gate_pass import GatePass
from icd_tz.tests.test_edi_codeco import make_partner
from icd_tz.tests.test_edi_movement import make_manifest, make_reception

test_ignore = ["Company", "Cost Center"]


class TestEDIDelivery(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "enable_edi", 1)
		frappe.db.set_single_value("ICD TZ Settings", "icd_un_locode", "TZDAR")
		frappe.db.set_single_value("ICD TZ Settings", "default_sender_id", "TZDARDSEL")
		self.partner = make_partner()
		self.partner.db_set({"connection_type": "SFTP", "url": "sftp.example.com", "user": "edi"})
		frappe.clear_document_cache("EDI Partner", "CMA")
		make_manifest()
		self.reception = self.make_submitted_reception()

	def tearDown(self):
		frappe.db.rollback()

	def make_submitted_reception(self):
		reception = make_reception(shipping_line_code="CMA")
		attach_gate_in(reception)
		# the submit hooks of a reception reach far beyond EDI, so only its outcome is set
		reception.db_set({"edi_file": reception.edi_file, "docstatus": 1})

		return reception

	def send(self, side_effect=None):
		with patch.object(EDIPartner, "send_file", side_effect=side_effect) as send_file:
			send_edi_file("Container Reception", self.reception.name)

		return send_file

	def is_sent(self) -> bool:
		return bool(frappe.db.get_value("Container Reception", self.reception.name, "edi_sent"))

	def test_the_attached_file_is_uploaded_and_marked_sent(self):
		send_file = self.send()

		file_name, content = send_file.call_args.args
		self.assertTrue(file_name.endswith(".edi"))
		self.assertTrue(content.startswith("UNB+UNOA:2+TZDARDSEL+CMA+"))
		self.assertTrue(self.is_sent())

	def test_a_sent_file_is_not_uploaded_again(self):
		self.reception.db_set("edi_sent", 1)

		self.send().assert_not_called()

	def test_a_draft_is_not_uploaded(self):
		self.reception.db_set("docstatus", 0)

		self.send().assert_not_called()

	def test_an_smtp_partner_is_not_uploaded_to(self):
		self.partner.db_set("connection_type", "SMTP")
		frappe.clear_document_cache("EDI Partner", "CMA")

		self.send().assert_not_called()
		self.assertFalse(self.is_sent())

	def test_a_failed_upload_is_logged_against_the_document_and_stays_unsent(self):
		send_file = self.send(side_effect=OSError("connection reset"))

		send_file.assert_called_once()
		error_log = self.get_error_log()
		self.assertEqual(error_log.method, "CODECO Gate In EDI not sent")
		self.assertTrue(error_log.error.startswith("connection reset<br>\nTraceback"))
		self.assertFalse(self.is_sent())

	def test_a_file_addressed_to_another_line_is_refused(self):
		file_url = self.reception.edi_file
		edi_file = frappe.get_doc("File", {"file_url": file_url})
		content = edi_file.get_content().replace("+TZDARDSEL+CMA+", "+TZDARDSEL+MSK+", 1)
		frappe.db.set_value("File", edi_file.name, "content_hash", None)
		with open(edi_file.get_full_path(), "w") as file:
			file.write(content)

		self.send().assert_not_called()

		self.assertIn("addressed to shipping line MSK, not to EDI Partner CMA", self.get_error_log().error)
		self.assertFalse(self.is_sent())

	def get_error_log(self):
		name = frappe.db.get_value(
			"Error Log",
			{"reference_doctype": "Container Reception", "reference_name": self.reception.name},
			order_by="creation desc",
		)

		return frappe.get_doc("Error Log", name)

	def test_the_receiver_is_read_from_the_unb_segment(self):
		self.assertEqual(get_receiver_id("UNB+UNOA:2+TZDARDSEL+CMA:ZZ+261004:0843+1'\nUNH+1'"), "CMA")
		self.assertEqual(get_receiver_id("UNB+UNOA:2+A?+B+C?'D+1'"), "C?'D")
		self.assertEqual(get_receiver_id("UNH+1+CODECO'"), "")

	def test_a_gate_pass_under_a_workflow_waits_for_the_gate_out(self):
		with patch_gate_pass_workflow(True):
			self.assertEqual(get_due_filters("Gate Pass"), {"workflow_state": GATE_OUT_CONFIRMED})
		with patch_gate_pass_workflow(False):
			self.assertEqual(get_due_filters("Gate Pass"), {})

		self.assertEqual(get_due_filters("Container Reception"), {})

	def test_gate_pass_without_a_workflow_is_queued_on_submit(self):
		self.assertEqual(self.get_gate_pass_queued("on_submit", has_workflow=False), 1)

	def test_gate_pass_under_a_workflow_is_not_queued_on_submit(self):
		self.assertEqual(self.get_gate_pass_queued("on_submit", has_workflow=True), 0)

	def test_gate_pass_is_queued_when_the_gate_out_is_confirmed(self):
		self.assertEqual(
			self.get_gate_pass_queued("on_update_after_submit", workflow_state=GATE_OUT_CONFIRMED), 1
		)
		self.assertEqual(self.get_gate_pass_queued("on_update_after_submit", workflow_state="Approved"), 0)

	def get_gate_pass_queued(self, method: str, has_workflow=True, workflow_state=None) -> int:
		gate_pass = frappe.new_doc("Gate Pass")
		gate_pass.workflow_state = workflow_state

		with (
			patch_gate_pass_workflow(has_workflow),
			patch.object(GatePass, "update_container_status"),
			patch.object(GatePass, "validate_pending_payments"),
			patch.object(GatePass, "set_gate_out_date"),
			patch("icd_tz.icd_tz.doctype.gate_pass.gate_pass.queue_delivery") as queue,
		):
			getattr(gate_pass, method)()

		return queue.call_count

	def test_submit_queues_one_job_per_document(self):
		with patch("frappe.enqueue") as enqueue:
			queue_delivery(self.reception)

		arguments = enqueue.call_args.kwargs
		self.assertEqual(arguments["job_id"], f"edi-delivery::Container Reception::{self.reception.name}")
		self.assertTrue(arguments["deduplicate"])
		self.assertTrue(arguments["enqueue_after_commit"])

	def test_nothing_is_queued_without_a_file(self):
		self.reception.edi_file = None

		with patch("frappe.enqueue") as enqueue:
			queue_delivery(self.reception)

		enqueue.assert_not_called()

	def test_nothing_is_queued_for_a_message_sent_by_email(self):
		self.reception.receiver_email = "edi@example.com"

		with patch("frappe.enqueue") as enqueue:
			queue_delivery(self.reception)

		enqueue.assert_not_called()

	def test_retry_queues_an_unsent_document(self):
		self.assertIn(self.reception.name, self.get_retried())

	def test_retry_skips_a_sent_document(self):
		self.reception.db_set("edi_sent", 1)

		self.assertNotIn(self.reception.name, self.get_retried())

	def test_retry_skips_a_document_older_than_the_window(self):
		self.reception.db_set("creation", add_days(now_datetime(), -RETRY_DAYS - 1))

		self.assertNotIn(self.reception.name, self.get_retried())

	def test_retry_skips_a_message_sent_by_email(self):
		self.reception.db_set("receiver_email", "edi@example.com")

		self.assertNotIn(self.reception.name, self.get_retried())

	def test_retry_does_nothing_while_edi_is_off(self):
		frappe.db.set_single_value("ICD TZ Settings", "enable_edi", 0)

		self.assertEqual(self.get_retried(), [])

	def get_retried(self) -> list:
		with patch("icd_tz.icd_tz.api.edi.delivery.enqueue_delivery") as enqueue:
			retry_failed_deliveries()

		return [
			name
			for doctype, name in (call.args for call in enqueue.call_args_list)
			if doctype == "Container Reception"
		]


def patch_gate_pass_workflow(has_workflow: bool):
	meta = frappe.get_meta("Gate Pass")
	has_field = meta.has_field

	return patch.object(
		meta,
		"has_field",
		side_effect=lambda fieldname: has_workflow if fieldname == "workflow_state" else has_field(fieldname),
	)
