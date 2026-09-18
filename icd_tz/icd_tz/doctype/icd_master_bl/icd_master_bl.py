# Copyright (c) 2026, elius mgani and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from icd_tz.icd_tz.api.accounting_dimensions import build_dimension_name


class ICDMasterBL(Document):
	"""Accounting dimension value for one master bill of lading, MAEU123456789:2026-00042"""

	def autoname(self):
		self.name = build_dimension_name(self.m_bl_no, self.manifest)
