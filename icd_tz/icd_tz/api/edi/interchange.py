"""What every outbound EDIFACT message shares: the envelope, the partner template and the attached file.

A message type subclasses MessageGenerator with its own context. The envelope
and the delivery channel come from the EDI Partner of the shipping line, and
so does the body: each partner renders its own template.
"""

import frappe
from frappe.model.naming import getseries
from frappe.utils import now_datetime

from icd_tz.icd_tz.api.edi.syntax import edifact_datetime, segment, split_segments, text
from icd_tz.icd_tz.doctype.edi_partner.edi_partner import get_partner

MESSAGE_FUNCTIONS = {"cancellation": "1", "replace": "5", "original": "9"}

EQUIPMENT_STATUS_IMPORT = "3"
EQUIPMENT_STATUS_EXPORT = "2"
FULL_INDICATOR = "5"
EMPTY_INDICATOR = "4"


class MessageGenerator:
	"""Build the interchange of one message about one container"""

	edi_type = ""
	# what the event date is called on the document, for the error a missing one raises
	event_label = ""

	def __init__(self, movement, partner):
		self.movement = movement
		self.partner = partner
		self.settings = frappe.get_cached_doc("ICD TZ Settings")
		self.reference = self.get_interchange_reference()

	def get_context(self, message_function: str) -> dict:
		raise NotImplementedError

	def get_common_context(self, message_function: str) -> dict:
		"""The values every message type names, already uppercased, cut to length and escaped.

		A template never sees a document, so a service character in a vessel or
		haulier name cannot be read as structure however the template spells it.
		A value carries the tightest length of the segments that may use it, so
		no template can overflow an element by moving a value into another one.
		"""

		movement = self.movement

		return {
			"reference": self.reference,
			"message_function": message_function,
			"sender": text(self.partner.sender, 25),
			"shipping_line_code": text(self.partner.shipping_line_code, 17),
			"icd_un_locode": text(self.settings.icd_un_locode, 25),
			"container_no": text(movement.container_no, 17),
			"size": text(movement.iso_size_type, 10),
			"m_bl_no": text(movement.m_bl_no, 20),
			"event_datetime": edifact_datetime(movement.event_datetime, "203"),
			"seal_no": text(movement.seal_no, 18),
			"voyage_no": text(movement.voyage_no, 17),
			"vessel_name": text(movement.vessel_name, 35),
			"call_sign": text(movement.call_sign, 9),
		}

	def get_filename(self, message_function: str = "original") -> str:
		context = self.get_context(MESSAGE_FUNCTIONS.get(message_function, "9"))

		# the message and the interchange share one reference
		return self.partner.get_file_name(self.edi_type, self.reference, self.reference, context)

	def get_interchange_reference(self) -> str:
		"""Fourteen characters, timestamp shaped, unique even inside one second"""

		series = getseries(f"EDI-{self.edi_type}-", 2)

		return f"{now_datetime().strftime('%y%m%d%H%M%S')}{series[-2:]}"

	def generate(self, message_function: str = "original") -> str:
		body = split_segments(self.render(MESSAGE_FUNCTIONS.get(message_function, "9")))
		body.append(segment("UNT", str(len(body) + 1), self.reference))

		return "\n".join([self.get_unb_segment(), *body, self.get_unz_segment()])

	def render(self, message_function: str) -> str:
		"""The message body, UNH through CNT, as this partner spells it.

		The template is author-supplied, so it is validated on save against the
		names of its type and nothing else: `frappe`, `doc` and every other global
		the sandbox injects are refused there. Jinja runs sandboxed on top of that.
		"""

		template = self.partner.get_template(self.edi_type)

		# nosemgrep: frappe-semgrep-rules.rules.security.frappe-ssti
		return frappe.render_template(template, self.get_context(message_function))

	def get_unb_segment(self) -> str:
		prepared = now_datetime()

		return segment(
			"UNB",
			["UNOA", "2"],
			text(self.partner.sender, 35),
			text(self.partner.shipping_line_code, 35),
			[prepared.strftime("%y%m%d"), prepared.strftime("%H%M")],
			self.reference,
		)

	def get_unz_segment(self) -> str:
		return segment("UNZ", "1", self.reference)


def attach(document, movement, generator_class):
	"""Write the message and its recipients onto the document.

	Nothing happens when no message is owed: the unit is not a container, it is
	cargo on a house bill, the shipping line has no enabled EDI Partner, or EDI
	is switched off. Only a genuine data fault stops the document.
	"""

	# an amended document arrives carrying the file and the recipients of the one it replaces
	document.edi_file = None
	document.receiver_email = None
	document.receiver_cc_email = None

	if movement is None:
		return

	partner = get_partner(movement.shipping_line_code)
	if partner is None:
		return

	edi_type = generator_class.edi_type
	if not movement.iso_size_type:
		frappe.throw(
			f"Container <b>{movement.container_no}</b> has no size, so its {edi_type} message "
			f"cannot be built for shipping line <b>{partner.name}</b>. Please set the size first."
		)

	# the carriers make the event date mandatory, so a message without one must not go out
	if not movement.event_datetime:
		frappe.throw(
			f"Container <b>{movement.container_no}</b> has no {generator_class.event_label}, so its "
			f"{edi_type} message cannot be built for shipping line <b>{partner.name}</b>. "
			f"Please set the {generator_class.event_label} first."
		)

	if partner.is_smtp:
		document.receiver_email = partner.receiver_email
		document.receiver_cc_email = partner.receiver_cc_email

	generator = generator_class(movement, partner)
	document.edi_file = save_message(document, generator.get_filename(), generator.generate())


def save_message(document, filename: str, content: str) -> str:
	edi_file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": content,
			"attached_to_doctype": document.doctype,
			"attached_to_name": document.name,
			"is_private": 1,
		}
	)
	edi_file.insert(ignore_permissions=True)

	return edi_file.file_url


def preview(movement, generator_class, message_function: str, edi_partner: str | None = None) -> dict | None:
	"""The message a movement would send, to the given partner or to its shipping line's

	A named partner is previewed even while its EDI is switched off, so it can be
	checked before it goes live.
	"""

	if movement is None:
		return None

	partner = get_preview_partner(edi_partner) if edi_partner else get_partner(movement.shipping_line_code)
	if partner is None:
		return None

	generator = generator_class(movement, partner)

	return {
		"edi_type": generator.edi_type,
		"edi_content": generator.generate(message_function),
		"filename": generator.get_filename(message_function),
	}


def get_preview_partner(edi_partner: str):
	partner = frappe.get_doc("EDI Partner", edi_partner)
	partner.check_permission("read")

	return partner
