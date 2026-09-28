"""CODECO D95B container gate-in / gate-out report.

One message reports one container crossing the ICD gate. The envelope and the
delivery channel come from the EDI Partner of the container shipping line, and
so does the body: each partner renders its own template, which starts life as
the one shipped with the app.
"""

import frappe
from frappe.model.naming import getseries
from frappe.utils import now_datetime

from icd_tz.icd_tz.api.edi.movement import from_container_reception, from_gate_pass
from icd_tz.icd_tz.api.edi.syntax import edifact_datetime, segment, split_segments, text, whole_number
from icd_tz.icd_tz.doctype.edi_partner.edi_partner import get_partner

EDI_TYPE = "CODECO"

MESSAGE_CODES = {"gate_in": "34", "gate_out": "36"}
MESSAGE_FUNCTIONS = {"cancellation": "1", "replace": "5", "original": "9"}

SERIES_KEY = "EDI-CODECO-"

EQUIPMENT_STATUS_IMPORT = "3"
EQUIPMENT_STATUS_EXPORT = "2"
FULL_INDICATOR = "5"
EMPTY_INDICATOR = "4"


class CODECOGenerator:
	"""Build the CODECO interchange of a single container movement."""

	def __init__(self, movement, partner):
		self.movement = movement
		self.partner = partner
		self.settings = frappe.get_cached_doc("ICD TZ Settings")
		self.reference = self.get_interchange_reference()

	@property
	def message_code(self) -> str:
		return MESSAGE_CODES["gate_in" if self.movement.is_gate_in else "gate_out"]

	def get_filename(self, message_function: str = "original") -> str:
		context = self.get_context(MESSAGE_FUNCTIONS.get(message_function, "9"))

		# the message and the interchange share one reference
		return self.partner.get_file_name(EDI_TYPE, self.reference, self.reference, context)

	def get_interchange_reference(self) -> str:
		"""Fourteen characters, timestamp shaped, unique even inside one second"""

		return f"{now_datetime().strftime('%y%m%d%H%M%S')}{getseries(SERIES_KEY, 2)[-2:]}"

	def generate(self, message_function: str = "original") -> str:
		body = split_segments(self.render(MESSAGE_FUNCTIONS.get(message_function, "9")))
		body.append(segment("UNT", str(len(body) + 1), self.reference))

		return "\n".join([self.get_unb_segment(), *body, self.get_unz_segment()])

	def render(self, message_function: str) -> str:
		"""The message body, UNH through CNT, as this partner spells it.

		The template is author-supplied, so it is validated on save against the
		names below and nothing else: `frappe`, `doc` and every other global the
		sandbox injects are refused there. Jinja runs sandboxed on top of that.
		"""

		template = self.partner.get_template(EDI_TYPE)

		# nosemgrep: frappe-semgrep-rules.rules.security.frappe-ssti
		return frappe.render_template(template, self.get_context(message_function))

	def get_context(self, message_function: str) -> dict:
		"""Every value a template may name, already uppercased, cut to length and escaped.

		A template never sees a document, so a service character in a vessel or
		haulier name cannot be read as structure however the template spells it.
		A value carries the tightest length of the segments that may use it, so
		no template can overflow an element by moving a value into another one.
		"""

		movement = self.movement
		transporter = movement.transporter or ""

		return {
			"reference": self.reference,
			"message_code": self.message_code,
			"message_function": message_function,
			"sender": text(self.partner.sender, 25),
			"shipping_line_code": text(self.partner.shipping_line_code, 17),
			"icd_un_locode": text(self.settings.icd_un_locode, 25),
			"container_no": text(movement.container_no, 17),
			"size": text(movement.iso_size_type, 10),
			"equipment_status": self.equipment_status,
			"full_empty_indicator": EMPTY_INDICATOR if movement.is_empty else FULL_INDICATOR,
			# flags, not data: a template asks with them and gets "1" or nothing
			"is_empty": "1" if movement.is_empty else "",
			"is_gate_in": "1" if movement.is_gate_in else "",
			"m_bl_no": text(movement.m_bl_no, 20),
			"event_datetime": edifact_datetime(movement.event_datetime, "203"),
			"weight": whole_number(movement.weight) if movement.has_weight_in_kilograms else "",
			"seal_no": text(movement.seal_no, 18),
			"transporter": text(transporter, 35),
			# sliced before it is escaped, so a released character is never cut in half
			"transporter_code": text(transporter[:2], 17),
			"truck": text(movement.truck, 9),
			"voyage_no": text(movement.voyage_no, 17),
			"vessel_name": text(movement.vessel_name, 35),
			"call_sign": text(movement.call_sign, 9),
		}

	@property
	def equipment_status(self) -> str:
		"""An empty box leaving the yard is going back to the line, so it is an export"""

		if not self.movement.is_gate_in and self.movement.is_empty:
			return EQUIPMENT_STATUS_EXPORT

		return EQUIPMENT_STATUS_IMPORT

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


def attach_gate_in(reception):
	"""Attach the gate-in CODECO to a Container Reception, when one is owed"""

	attach(reception, from_container_reception(reception))


def attach_gate_out(gate_pass):
	"""Attach the gate-out CODECO to a Gate Pass, when one is owed"""

	attach(gate_pass, from_gate_pass(gate_pass))


def attach(document, movement):
	"""Write the message and its recipients onto the document.

	Nothing happens when no message is owed: the unit is not a container, it is
	cargo leaving on a house bill, the shipping line has no enabled EDI Partner,
	or EDI is switched off. Only a genuine data fault stops the document.
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

	if not movement.iso_size_type:
		frappe.throw(
			f"Container <b>{movement.container_no}</b> has no size, so its CODECO message "
			f"cannot be built for shipping line <b>{partner.name}</b>. Please set the size first."
		)

	# the carriers make the event date mandatory, so a message without one must not go out
	if not movement.event_datetime:
		frappe.throw(
			f"Container <b>{movement.container_no}</b> has no gate date, so its CODECO message "
			f"cannot be built for shipping line <b>{partner.name}</b>. Please set the date first."
		)

	if partner.is_smtp:
		document.receiver_email = partner.receiver_email
		document.receiver_cc_email = partner.receiver_cc_email

	generator = CODECOGenerator(movement, partner)
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


@frappe.whitelist()
def generate_codeco_gate_in(
	container_reception: str, message_function: str = "original", edi_partner: str | None = None
) -> dict | None:
	"""Preview the gate-in message of a Container Reception without attaching it"""

	reception = frappe.get_doc("Container Reception", container_reception)
	reception.check_permission("read")

	return preview(from_container_reception(reception), message_function, edi_partner)


@frappe.whitelist()
def generate_codeco_gate_out(
	gate_pass: str, message_function: str = "original", edi_partner: str | None = None
) -> dict | None:
	"""Preview the gate-out message of a Gate Pass without attaching it"""

	document = frappe.get_doc("Gate Pass", gate_pass)
	document.check_permission("read")

	return preview(from_gate_pass(document), message_function, edi_partner)


def preview(movement, message_function: str, edi_partner: str | None = None) -> dict | None:
	"""The message a movement would send, to the given partner or to its shipping line's

	A named partner is previewed even while its EDI is switched off, so it can be
	checked before it goes live.
	"""

	if movement is None:
		return None

	partner = get_preview_partner(edi_partner) if edi_partner else get_partner(movement.shipping_line_code)
	if partner is None:
		return None

	generator = CODECOGenerator(movement, partner)

	return {
		"edi_content": generator.generate(message_function),
		"filename": generator.get_filename(message_function),
		"movement_type": "gate_in" if movement.is_gate_in else "gate_out",
	}


def get_preview_partner(edi_partner: str):
	partner = frappe.get_doc("EDI Partner", edi_partner)
	partner.check_permission("read")

	return partner
