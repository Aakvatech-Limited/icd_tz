# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from icd_tz.icd_tz.api.port_expenses import CRITERIA_FIELDS, STORAGE_EXPENSE_TYPES


class ICDTZSettings(Document):
	def before_save(self):
		self.validate_storage_days()
		self.validate_expense_types()
		self.validate_port_storage_days()

	def validate_storage_days(self):
		storage_days = []
		for row in self.storage_days:
			d = {"destination": row.destination, "charge": row.charge}
			if d in storage_days:
				frappe.throw(f"At Row#: {row.idx}, {row.destination} with charge {row.charge} already exists")
			else:
				storage_days.append(d)

	def validate_expense_types(self):
		"""Two criteria rows with the same key would make the winning row arbitrary"""

		defined_keys = set()
		for row in self.expense_types:
			key = (row.expense_type, *(row.get(field) or "" for field in CRITERIA_FIELDS))
			if key in defined_keys:
				frappe.throw(
					_("At Row#: {0}, {1} with the same criteria already exists").format(
						row.idx, frappe.bold(row.expense_type)
					)
				)

			defined_keys.add(key)

	def validate_port_storage_days(self):
		"""One band per charge, each covering a real range of days"""

		defined_bands = set()
		for row in self.port_storage_days:
			if cint(row.get("from")) < 1 or cint(row.get("to")) < cint(row.get("from")):
				frappe.throw(
					_("At Row#: {0}, From must be 1 or more and To must not be less than From").format(
						row.idx
					)
				)

			if row.charge in defined_bands:
				frappe.throw(
					_("At Row#: {0}, charge {1} already exists").format(row.idx, frappe.bold(row.charge))
				)

			defined_bands.add(row.charge)

		# only one band set would silently price the other charge at zero days
		missing = [charge for charge in STORAGE_EXPENSE_TYPES.values() if charge not in defined_bands]
		if defined_bands and missing:
			frappe.throw(
				_("Port Storage Days is missing a row for: {0}").format(frappe.bold(", ".join(missing))),
				title=_("Incomplete Port Storage Days"),
			)
