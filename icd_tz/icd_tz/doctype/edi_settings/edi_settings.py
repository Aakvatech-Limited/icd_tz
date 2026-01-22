# Copyright (c) 2025, Administrator and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class EDISettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		authentication_key: DF.Code | None
		authentication_method: DF.Literal["Password", "Key"]
		directory: DF.Data | None
		ip_behind_dns: DF.Data | None
		password: DF.Password | None
		port: DF.Int
		source_ip: DF.Data | None
		url: DF.Data
		user: DF.Data
	# end: auto-generated types
