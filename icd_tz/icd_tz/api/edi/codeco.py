"""CODECO D95B container gate-in / gate-out report.

One message reports one container crossing the ICD gate. The envelope and the
delivery channel come from the EDI Partner of the container shipping line; the
message body is the same for every line.
"""

import frappe
from frappe.model.naming import getseries
from frappe.utils import now_datetime

from icd_tz.icd_tz.api.edi.movement import from_container_reception, from_gate_pass
from icd_tz.icd_tz.api.edi.syntax import edifact_datetime, segment, text, whole_number
from icd_tz.icd_tz.doctype.edi_partner.edi_partner import get_partner

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

	@property
	def filename(self) -> str:
		"""Partner naming convention: sender, receiver, message type, timestamp"""

		return f"{self.partner.sender}_{self.partner.shipping_line_code}_CODECO_{self.reference}.edi"

	def get_interchange_reference(self) -> str:
		"""Fourteen characters, timestamp shaped, unique even inside one second"""

		return f"{now_datetime().strftime('%y%m%d%H%M%S')}{getseries(SERIES_KEY, 2)[-2:]}"

	def generate(self, message_function: str = "original") -> str:
		body = self.get_body_segments(MESSAGE_FUNCTIONS.get(message_function, "9"))
		body.append(segment("UNT", str(len(body) + 1), self.reference))

		return "\n".join([self.get_unb_segment(), *body, self.get_unz_segment()])

	def get_body_segments(self, message_function: str) -> list[str]:
		"""Every segment from UNH up to CNT, in the order the guides define"""

		segments = [
			segment("UNH", self.reference, ["CODECO", "D", "95B", "UN", "ITG14"]),
			segment("BGM", self.message_code, text(self.movement.document, 35), message_function),
			self.get_tdt_main_carriage(),
			segment("NAD", "CF", text(self.partner.shipping_line_code, 35)),
			self.get_eqd_segment(),
		]

		segments += [
			candidate
			for candidate in (
				self.get_rff_segment(),
				self.get_dtm_segment(),
				self.get_loc_segment(),
				self.get_mea_segment(),
				self.get_sel_segment(),
				self.get_tdt_inland_carriage(),
			)
			if candidate
		]
		segments.append(segment("CNT", ["16", "1"]))

		return segments

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

	def get_tdt_main_carriage(self) -> str:
		"""Ocean leg. The carrier matches the gate event to this vessel and voyage.

		The code list owner is left out on purpose: the shipping line code comes
		from TANeSW, not from BIC or any other list the guides name.
		"""

		return segment(
			"TDT",
			"20",
			text(self.movement.voyage_no, 17),
			"1",
			"",
			[text(self.partner.shipping_line_code, 17), "172"],
			"",
			"",
			[text(self.movement.call_sign, 9), "103", "", text(self.movement.vessel_name, 35)],
		)

	def get_eqd_segment(self) -> str:
		status = EQUIPMENT_STATUS_IMPORT
		if not self.movement.is_gate_in and self.movement.is_empty:
			status = EQUIPMENT_STATUS_EXPORT

		return segment(
			"EQD",
			"CN",
			text(self.movement.container_no, 17),
			[text(self.movement.iso_size_type, 10), "102", "5"],
			"",
			status,
			EMPTY_INDICATOR if self.movement.is_empty else FULL_INDICATOR,
		)

	def get_rff_segment(self) -> str | None:
		"""Bill of lading. BM is the qualifier for a B/L, BN is for a booking."""

		if not self.movement.m_bl_no:
			return None

		return segment("RFF", ["BM", text(self.movement.m_bl_no, 20)])

	def get_dtm_segment(self) -> str | None:
		moment = edifact_datetime(self.movement.event_datetime, "203")
		if not moment:
			return None

		return segment("DTM", ["7", moment, "203"])

	def get_loc_segment(self) -> str | None:
		"""Where the gate movement happened, which is this ICD and not the seaport.

		The facility carries the same code as the interchange sender, so the
		shipping line reads a depot code it issued itself. Our own code means
		nothing to a line that addresses us by another one.
		"""

		un_locode = text(self.settings.icd_un_locode, 25)
		if not un_locode:
			return None

		return segment(
			"LOC",
			"165",
			[un_locode, "139", "6"],
			[text(self.partner.sender, 25), "TER", "ZZZ"],
		)

	def get_mea_segment(self) -> str | None:
		if not self.movement.has_weight_in_kilograms:
			return None

		return segment("MEA", "AAE", "G", ["KGM", whole_number(self.movement.weight)])

	def get_sel_segment(self) -> str | None:
		seal_no = text(self.movement.seal_no, 18)
		if not seal_no:
			return None

		return segment("SEL", seal_no, "CA")

	def get_tdt_inland_carriage(self) -> str | None:
		"""Road leg, the truck that brought the box in or took it away"""

		transporter = self.movement.transporter or ""
		truck = text(self.movement.truck, 9)
		if not transporter and not truck:
			return None

		# slice before escaping, so a released character is never cut in half or released twice
		haulier_code = text(transporter[:2], 17)

		return segment(
			"TDT", "1", "", "3", "", [haulier_code, "172", "", text(transporter, 35)], "", "", truck
		)


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
	document.edi_file = save_message(document, generator.filename, generator.generate())


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
def generate_codeco_gate_in(container_reception: str, message_function: str = "original") -> dict | None:
	"""Preview the gate-in message of a Container Reception without attaching it"""

	reception = frappe.get_doc("Container Reception", container_reception)
	reception.check_permission("read")

	return preview(from_container_reception(reception), message_function)


@frappe.whitelist()
def generate_codeco_gate_out(gate_pass: str, message_function: str = "original") -> dict | None:
	"""Preview the gate-out message of a Gate Pass without attaching it"""

	document = frappe.get_doc("Gate Pass", gate_pass)
	document.check_permission("read")

	return preview(from_gate_pass(document), message_function)


def preview(movement, message_function: str) -> dict | None:
	if movement is None:
		return None

	partner = get_partner(movement.shipping_line_code)
	if partner is None:
		return None

	generator = CODECOGenerator(movement, partner)

	return {
		"edi_content": generator.generate(message_function),
		"filename": generator.filename,
		"movement_type": "gate_in" if movement.is_gate_in else "gate_out",
	}
