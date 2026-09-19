# Copyright (c) 2026, elius mgani and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class EDIPartnerTemplate(Document):
	"""One EDIFACT message body this partner accepts, rendered as a Jinja template."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		edi_type: DF.Literal["CODECO", "COREOR", "COARRI", "COPARN", "COPRAR"]
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		template: DF.Code
	# end: auto-generated types
