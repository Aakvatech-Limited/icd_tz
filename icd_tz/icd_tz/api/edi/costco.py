"""COSTCO D95B container stripping report.

One message reports one LCL container stripped inside the ICD on a Container
Unpacking. The box does not cross the gate, so CODECO cannot carry the event.
"""

import frappe

from icd_tz.icd_tz.api.edi.interchange import (
	EMPTY_INDICATOR,
	EQUIPMENT_STATUS_IMPORT,
	MessageGenerator,
	attach,
	preview,
)
from icd_tz.icd_tz.api.edi.movement import from_container_unpacking

# UN/EDIFACT 1001: transport equipment unpacking report
UNPACKING_REPORT = "113"


class COSTCOGenerator(MessageGenerator):
	"""Build the COSTCO interchange of a single stripped container."""

	edi_type = "COSTCO"
	event_label = "unpacking end time"

	def get_context(self, message_function: str) -> dict:
		"""The box is reported empty and on import: its cargo has just been counted out,
		and only an imported LCL box is stripped here."""

		return {
			**self.get_common_context(message_function),
			"message_code": UNPACKING_REPORT,
			"equipment_status": EQUIPMENT_STATUS_IMPORT,
			"full_empty_indicator": EMPTY_INDICATOR,
		}


def attach_unpacking(unpacking):
	"""Attach the stripping COSTCO to a Container Unpacking, when one is owed"""

	attach(unpacking, from_container_unpacking(unpacking), COSTCOGenerator)


@frappe.whitelist()
def generate_costco_unpacking(
	container_unpacking: str, message_function: str = "original", edi_partner: str | None = None
) -> dict | None:
	"""Preview the stripping message of a Container Unpacking without attaching it"""

	unpacking = frappe.get_doc("Container Unpacking", container_unpacking)
	unpacking.check_permission("read")

	return preview(from_container_unpacking(unpacking), COSTCOGenerator, message_function, edi_partner)
