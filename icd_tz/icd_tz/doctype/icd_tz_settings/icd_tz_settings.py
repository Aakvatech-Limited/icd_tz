# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

from itertools import pairwise

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from icd_tz.icd_tz.api.port_expenses import (
	CRITERIA_FIELDS,
	STORAGE_EXPENSE_TYPES,
	is_band_configured,
)


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
			# a seeded row carries only the charge until its days are confirmed, and
			# must not hold every other setting on this page hostage meanwhile
			if not row.get("from") and not row.get("to"):
				defined_bands.add(row.charge)
				continue

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

		self.validate_port_storage_bands_cover_every_day()

	def validate_port_storage_bands_cover_every_day(self):
		"""The bands must run from day one without a gap or an overlap

		A day two bands cover would be charged whichever was read first, and a day
		no band covers is never recorded at all, so the stay would quietly lose it.
		"""

		bands = sorted(
			(row for row in self.port_storage_days if is_band_configured(row)),
			key=lambda row: cint(row.get("from")),
		)
		if not bands:
			return

		if cint(bands[0].get("from")) != 1:
			frappe.throw(
				_("Port Storage Days must start at day 1, {0} starts at day {1}").format(
					frappe.bold(bands[0].charge), frappe.bold(bands[0].get("from"))
				),
				title=_("Incomplete Port Storage Days"),
			)

		for earlier, later in pairwise(bands):
			if cint(later.get("from")) == cint(earlier.get("to")) + 1:
				continue

			frappe.throw(
				_("Port Storage Days {0} ends on day {1} and {2} starts on day {3}").format(
					frappe.bold(earlier.charge),
					frappe.bold(earlier.get("to")),
					frappe.bold(later.charge),
					frappe.bold(later.get("from")),
				),
				title=_("Overlapping Port Storage Days")
				if cint(later.get("from")) <= cint(earlier.get("to"))
				else _("Gap In Port Storage Days"),
			)
