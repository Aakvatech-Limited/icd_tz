# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ICDTZSettings(Document):
	def before_save(self):
		self.validate_storage_days()

	def validate_storage_days(self):
		storage_days = []
		for row in self.storage_days:
			d = {"destination": row.destination, "charge": row.charge}
			if d in storage_days:
				frappe.throw(f"At Row#: {row.idx}, {row.destination} with charge {row.charge} already exists")
			else:
				storage_days.append(d)
