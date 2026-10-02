# Copyright (c) 2026, elius mgani and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import cint, flt


class ContainerUnpackingDetail(Document):
	@property
	def gross_volume(self) -> float:
		"""CBM the cargo is billed on, the consolidator's only when the manifest gives none"""

		return flt(self.manifest_gross_volume) or flt(self.consolidator_gross_volume)

	def set_package_difference(self):
		self.package_difference = cint(self.counted_packages) - cint(self.manifest_packages)
