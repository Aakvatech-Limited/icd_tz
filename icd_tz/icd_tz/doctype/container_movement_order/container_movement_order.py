# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.utils import cint, get_url_to_form

from icd_tz.icd_tz.api.tanesw import get_discharge_date

mf = DocType("Manifest")
mb = DocType("Master BL")
cd = DocType("Containers Detail")
cmo = DocType("Container Movement Order")


class ContainerMovementOrder(Document):
	def before_insert(self):
		self.update_container_count()
		self.set_ship_dc_date()

	def before_save(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company")

		self.set_ship_dc_date()

	def validate(self):
		if self.container_no:
			self.validate_container_is_in_manifest()
			self.validate_duplicate_cmo_per_container_number()

	def before_submit(self):
		self.validate_signature()
		self.validate_ship_dc_date()

		self.status = "Pending"

	def set_ship_dc_date(self):
		"""Fetch the discharge date from TANeSW, a date already on the document is kept"""

		if self.ship_dc_date:
			return

		self.ship_dc_date = get_discharge_date(self.container_no, self.m_bl_no)

	def validate_ship_dc_date(self):
		if not self.ship_dc_date:
			frappe.throw(
				"Ship D/C Date could not be fetched from TANeSW for Container: "
				f"<b>{self.container_no}</b>, Please fill it before submitting this document"
			)

	def on_submit(self):
		self.update_container_has_order()

	def before_cancel(self):
		self.validate_cmo_links()

	def on_cancel(self):
		self.update_container_has_order(value=0)

	def validate_container_is_in_manifest(self):
		"""Validate that the container number is in the selected manifest"""

		if not frappe.db.exists(
			"Containers Detail", {"parent": self.manifest, "container_no": self.container_no}
		):
			frappe.throw(
				f"Container: {self.container_no} does not belong to the this Manifest: {self.manifest}"
			)

	def validate_duplicate_cmo_per_container_number(self):
		"""Validate the duplicate of cmo per container number"""
		duplicates = (
			frappe.qb.from_(cmo)
			.select(cmo.name.as_("cmo_id"))
			.where(
				(cmo.manifest == self.manifest)
				& (cmo.container_no == self.container_no)
				& (cmo.name != self.name)
			)
		).run(as_dict=True)
		if duplicates:
			url = get_url_to_form("Container Movement Order", duplicates[0].cmo_id)
			frappe.throw(
				f"Container: {self.container_no} already has a Movement Order: <a href='{url}'>{duplicates[0].cmo_id}</a>"
			)

	def update_container_has_order(self, value=1):
		"""Update the status of the container to Has Order"""
		if self.container_no:
			frappe.db.set_value(
				"Containers Detail",
				{"parent": self.manifest, "container_no": self.container_no},
				"has_order",
				value,
			)

	def validate_signature(self):
		settings_doc = frappe.get_doc("ICD TZ Settings")
		if settings_doc.enable_signature_validation == 1:
			if not self.driver_signature or not self.gate_no_signature:
				frappe.throw("Please ensure all signatures are provided before submitting this document.")

	def update_container_count(self):
		"""Update the container count based on the manifest and m_bl_no"""

		if self.manifest and self.m_bl_no and not self.container_count:
			total_count = frappe.db.get_value(
				"Master BL", {"parent": self.manifest, "m_bl_no": self.m_bl_no}, "number_of_containers"
			)

			current_count = frappe.db.count(
				"Container Movement Order", {"manifest": self.manifest, "m_bl_no": self.m_bl_no}
			)

			self.container_count = f"{current_count + 1}/{total_count}"

	def validate_cmo_links(self):
		reception_records = frappe.db.get_all(
			"Container Reception",
			{"movement_order": self.name},
		)
		if len(reception_records) == 0:
			return

		frappe.throw(
			f"Do not cancel this Movement Order: {self.name}, It is linked with Container Reception: {reception_records[0].name}"
		)


@frappe.whitelist()
def get_manifest_details(manifest, m_bl_no=None):
	"""Get details of a manifest and container information"""

	query = (
		frappe.qb.from_(mf)
		.inner_join(cd)
		.on(mf.name == cd.parent)
		.inner_join(mb)
		.on(cd.m_bl_no == mb.m_bl_no)
		.select(
			mf.mrn,
			mf.vessel_name,
			mf.tpa_uid,
			mf.voyage_no,
			mf.arrival_date,
			mf.call_sign,
			mf.company,
			cd.container_no,
			cd.m_bl_no,
			cd.container_size,
			cd.freight_indicator,
			mb.cargo_classification.as_("cargo_type"),
		)
		.where(
			(mf.name == manifest) & (cd.has_order == 0) & (cd.parent == manifest) & (mb.parent == manifest)
		)
	)

	if m_bl_no:
		query = query.where((mb.m_bl_no == m_bl_no) & (cd.m_bl_no == m_bl_no))

	details = query.run(as_dict=True)

	return details
