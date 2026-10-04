"""CODECO D95B container gate-in / gate-out report.

One message reports one container crossing the ICD gate: gate-in on a
Container Reception, gate-out on a Gate Pass.
"""

import frappe

from icd_tz.icd_tz.api.edi.interchange import (
	EMPTY_INDICATOR,
	EQUIPMENT_STATUS_EXPORT,
	EQUIPMENT_STATUS_IMPORT,
	FULL_INDICATOR,
	MessageGenerator,
	attach,
	preview,
)
from icd_tz.icd_tz.api.edi.movement import from_container_reception, from_gate_pass
from icd_tz.icd_tz.api.edi.syntax import text, whole_number

MESSAGE_CODES = {"gate_in": "34", "gate_out": "36"}


class CODECOGenerator(MessageGenerator):
	"""Build the CODECO interchange of a single gate movement."""

	edi_type = "CODECO"
	event_label = "gate date"

	@property
	def message_code(self) -> str:
		return MESSAGE_CODES["gate_in" if self.movement.is_gate_in else "gate_out"]

	def get_context(self, message_function: str) -> dict:
		movement = self.movement
		transporter = movement.transporter or ""

		return {
			**self.get_common_context(message_function),
			"message_code": self.message_code,
			"equipment_status": self.equipment_status,
			"full_empty_indicator": EMPTY_INDICATOR if movement.is_empty else FULL_INDICATOR,
			# flags, not data: a template asks with them and gets "1" or nothing
			"is_empty": "1" if movement.is_empty else "",
			"is_gate_in": "1" if movement.is_gate_in else "",
			"weight": whole_number(movement.weight) if movement.has_weight_in_kilograms else "",
			"transporter": text(transporter, 35),
			# sliced before it is escaped, so a released character is never cut in half
			"transporter_code": text(transporter[:2], 17),
			"truck": text(movement.truck, 9),
		}

	@property
	def equipment_status(self) -> str:
		"""An empty box leaving the yard is going back to the line, so it is an export"""

		if not self.movement.is_gate_in and self.movement.is_empty:
			return EQUIPMENT_STATUS_EXPORT

		return EQUIPMENT_STATUS_IMPORT


def attach_gate_in(reception):
	"""Attach the gate-in CODECO to a Container Reception, when one is owed"""

	attach(reception, from_container_reception(reception), CODECOGenerator)


def attach_gate_out(gate_pass):
	"""Attach the gate-out CODECO to a Gate Pass, when one is owed"""

	attach(gate_pass, from_gate_pass(gate_pass), CODECOGenerator)


@frappe.whitelist()
def generate_codeco_gate_in(
	container_reception: str, message_function: str = "original", edi_partner: str | None = None
) -> dict | None:
	"""Preview the gate-in message of a Container Reception without attaching it"""

	reception = frappe.get_doc("Container Reception", container_reception)
	reception.check_permission("read")

	return preview(from_container_reception(reception), CODECOGenerator, message_function, edi_partner)


@frappe.whitelist()
def generate_codeco_gate_out(
	gate_pass: str, message_function: str = "original", edi_partner: str | None = None
) -> dict | None:
	"""Preview the gate-out message of a Gate Pass without attaching it"""

	document = frappe.get_doc("Gate Pass", gate_pass)
	document.check_permission("read")

	return preview(from_gate_pass(document), CODECOGenerator, message_function, edi_partner)
