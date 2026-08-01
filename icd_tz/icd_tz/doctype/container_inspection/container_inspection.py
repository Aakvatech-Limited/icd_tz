# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate

from icd_tz.icd_tz.api.utils import validate_cf_agent, validate_draft_doc


class ContainerInspection(Document):
	def before_insert(self):
		self.get_custom_verification_services()

	def after_insert(self):
		self.update_in_yard_booking(value=self.name)
		self.update_container_status("At Inspection")

	def before_save(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company")

	def validate(self):
		validate_draft_doc("In Yard Container Booking", self.in_yard_container_booking)
		validate_cf_agent(self)

	def on_submit(self):
		self.update_container_doc()

	def on_trash(self):
		self.update_in_yard_booking()
		self.update_container_status("At Booking")

	def update_container_status(self, status):
		if not self.container_id:
			return

		frappe.db.set_value("Container", self.container_id, "status", status)

	def update_in_yard_booking(self, value=None):
		if not self.in_yard_container_booking:
			return

		frappe.db.set_value(
			"In Yard Container Booking", self.in_yard_container_booking, "container_inspection", value
		)

	def update_container_doc(self):
		if not self.container_id:
			return

		container_doc = frappe.get_doc("Container", self.container_id)
		if self.new_container_location:
			container_doc.current_location = self.new_container_location

		for row in self.services:
			if row.status_changed_to and row.status_changed_to != container_doc.freight_indicator:
				container_doc.freight_indicator = row.status_changed_to
				container_doc.gross_volume = row.volume

		container_doc.last_inspection_date = nowdate()
		container_doc.save(ignore_permissions=True)

	@frappe.whitelist()
	def get_custom_verification_services(self, caller=None):
		if caller == "Front End" and isinstance(self, str):
			self = frappe.parse_json(self)

		if not self.get("in_yard_container_booking"):
			return

		has_custom_verification_charges = frappe.db.get_value(
			"In Yard Container Booking",
			self.get("in_yard_container_booking"),
			"has_custom_verification_charges",
		)

		if has_custom_verification_charges != "Yes":
			return

		verification_item = ""
		settings_doc = frappe.get_cached_doc("ICD TZ Settings")

		for row in settings_doc.get("service_types"):
			if row.service_type == "Verification":
				if "2" in str(row.size)[0] and "2" in str(self.container_size)[0]:
					verification_item = row.service_name
					break

				elif "4" in str(row.size)[0] and "4" in str(self.container_size)[0]:
					verification_item = row.service_name
					break

				else:
					continue

		if not verification_item:
			frappe.throw(
				"Verification Pricing Criteria is not set in ICD TZ Settings, Please set it to continue"
			)

		service_names = [row.get("service") for row in self.get("services")]
		if verification_item not in service_names:
			if caller == "Front End":
				return verification_item
			else:
				self.append("services", {"service": verification_item})


@frappe.whitelist()
def create_bulk_inspections(data):
	data = frappe.parse_json(data)

	filters = {"docstatus": 1}

	if data.get("m_bl_no"):
		filters["m_bl_no"] = data.get("m_bl_no")
		filters["h_bl_no"] = ["is", "not set"]
	elif data.get("h_bl_no"):
		filters["h_bl_no"] = data.get("h_bl_no")

	bookings = frappe.db.get_all(
		"In Yard Container Booking", filters=filters, fields=["name", "container_id", "inspection_date"]
	)
	if len(bookings) == 0:
		msg = ""
		if data.get("m_bl_no"):
			msg = f"M BL No: <b>{data.get('m_bl_no')}</b>"
		elif data.get("h_bl_no"):
			msg = f"H BL No: <b>{data.get('h_bl_no')}</b>"

		frappe.msgprint(f"No submitted Container Bookings found for {msg}")
		return

	count = 0
	for booking in bookings:
		doc = frappe.new_doc("Container Inspection")
		doc.in_yard_container_booking = booking.name
		doc.container_id = booking.container_id
		doc.inspector_name = data.get("inspector_name")
		doc.inspection_date = booking.inspection_date

		doc.flags.ignore_permissions = True
		doc.insert()
		doc.reload()

		if doc.get("name"):
			count += 1

	return count
