"""Upload of the attached EDI file to the partner's SFTP server, after submit and on retry."""

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime

from icd_tz.icd_tz.api.edi.movement import (
	from_container_reception,
	from_container_unpacking,
	from_gate_pass,
)
from icd_tz.icd_tz.api.edi.syntax import (
	COMPONENT_SEPARATOR,
	ELEMENT_SEPARATOR,
	SEGMENT_TERMINATOR,
	split_on,
	text,
)
from icd_tz.icd_tz.doctype.edi_partner.edi_partner import get_partner

# the message each document carries, and its movement, which gives the shipping line the way the message was built
DOCUMENT_MESSAGES = {
	"Container Reception": ("CODECO Gate In", from_container_reception),
	"Gate Pass": ("CODECO Gate Out", from_gate_pass),
	"Container Unpacking": ("COSTCO Unpacking", from_container_unpacking),
}

# older unsent files are left alone, so the first run does not replay the history of the yard
RETRY_DAYS = 3

# a gate pass under a workflow is reported once the truck is confirmed out, not when it is submitted
GATE_OUT_CONFIRMED = "Gate Out Confirmed"


def queue_delivery(document):
	"""Upload the document's EDI file in the background once the submit is committed"""

	# a receiver email marks a message the SMTP channel carries, not SFTP
	if document.edi_file and not document.receiver_email:
		enqueue_delivery(document.doctype, document.name)


def enqueue_delivery(doctype: str, name: str):
	# one job id per document, so a submit and a retry never upload the same file side by side
	frappe.enqueue(
		send_edi_file,
		queue="short",
		job_id=f"edi-delivery::{doctype}::{name}",
		deduplicate=True,
		enqueue_after_commit=True,
		doctype=doctype,
		name=name,
	)


def send_edi_file(doctype: str, name: str):
	"""Upload one document's EDI file and mark it sent. A failure goes to the Error Log and waits for the retry."""

	document = frappe.get_doc(doctype, name)
	if document.docstatus != 1 or document.edi_sent or not document.edi_file:
		return

	if any(document.get(fieldname) != value for fieldname, value in get_due_filters(doctype).items()):
		return

	try:
		upload_edi_file(document)
	except Exception as error:
		# logged here and not raised, so the job runner does not log it a second time
		message = frappe.utils.strip_html(str(error)) or type(error).__name__
		frappe.log_error(
			title=_("{0} EDI not sent").format(DOCUMENT_MESSAGES[doctype][0]),
			message=message + "<br>\n" + frappe.get_traceback(),
			reference_doctype=doctype,
			reference_name=name,
		)


def upload_edi_file(document):
	movement = DOCUMENT_MESSAGES[document.doctype][1](document)
	partner = get_partner(movement.shipping_line_code)
	if partner is None or not partner.is_sftp:
		return

	edi_file = frappe.get_doc(
		"File",
		{
			"file_url": document.edi_file,
			"attached_to_doctype": document.doctype,
			"attached_to_name": document.name,
		},
	)
	content = edi_file.get_content()
	validate_receiver(content, partner, edi_file.file_name)
	partner.send_file(edi_file.file_name, content)

	document.db_set("edi_sent", 1, update_modified=False)


def retry_failed_deliveries():
	"""Queue again every recent submitted document whose EDI file has not gone out"""

	if not frappe.db.get_single_value("ICD TZ Settings", "enable_edi"):
		return

	since = add_days(now_datetime(), -RETRY_DAYS)
	for doctype in DOCUMENT_MESSAGES:
		names = frappe.get_all(
			doctype,
			filters={
				"docstatus": 1,
				"edi_sent": 0,
				"edi_file": ["is", "set"],
				# a receiver email marks a message the SMTP channel carries, not SFTP
				"receiver_email": ["is", "not set"],
				"creation": [">=", since],
				**get_due_filters(doctype),
			},
			pluck="name",
		)
		for name in names:
			enqueue_delivery(doctype, name)


def get_due_filters(doctype: str) -> dict:
	"""What a submitted document must also match before its file goes out"""

	if doctype == "Gate Pass" and frappe.get_meta(doctype).has_field("workflow_state"):
		return {"workflow_state": GATE_OUT_CONFIRMED}

	return {}


def validate_receiver(content: str, partner, file_name: str):
	"""Refuse a file whose interchange is addressed to another shipping line than the partner it goes to"""

	receiver = get_receiver_id(content)
	if receiver != text(partner.shipping_line_code, 35):
		frappe.throw(
			_(
				"EDI file {0} is addressed to shipping line {1}, not to EDI Partner {2}, so it was not sent"
			).format(file_name, receiver or _("(none)"), partner.name)
		)


def get_receiver_id(content: str) -> str:
	"""Recipient of the interchange, the third element of its UNB segment"""

	elements = split_on(split_on(content.lstrip(), SEGMENT_TERMINATOR)[0], ELEMENT_SEPARATOR)
	if elements[0] != "UNB" or len(elements) < 4:
		return ""

	return split_on(elements[3], COMPONENT_SEPARATOR)[0]
