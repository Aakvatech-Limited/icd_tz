# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_url_to_form, nowdate

from icd_tz.icd_tz.api.utils import (
	get_delivered_containers,
	validate_cf_agent,
	validate_delivered_container,
	validate_draft_doc,
)


class ContainerInspection(Document):
	def before_insert(self):
		self.get_custom_verification_services()

	def before_cancel(self):
		validate_delivered_container(self.container_id, self.container_no, action="cancelled")

	def after_insert(self):
		self.update_in_yard_booking(value=self.name)
		self.update_container_status("At Inspection")

	def before_save(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company")

	def validate(self):
		validate_draft_doc("In Yard Container Booking", self.in_yard_container_booking)
		validate_cf_agent(self)
		self.set_additional_inspection()

		# container_id is fetched from the booking, so check only after it is resolved
		if self.is_new():
			validate_delivered_container(self.container_id, self.container_no)

		self.validate_duplicate_inspection()

	def set_additional_inspection(self):
		"""An inspection raised from an additional booking is itself an additional inspection"""

		if not self.in_yard_container_booking:
			return

		booking = frappe.db.get_value(
			"In Yard Container Booking",
			self.in_yard_container_booking,
			["container_id", "is_additional_booking"],
			as_dict=True,
		)

		self.is_additional_inspection = booking.is_additional_booking
		if not self.container_id:
			self.container_id = booking.container_id

	def validate_duplicate_inspection(self):
		"""Allow one inspection per container, a repeat one must come from an additional booking"""

		if self.is_additional_inspection == 1:
			return

		existing_inspections = frappe.db.get_all(
			"Container Inspection",
			filters={
				"container_id": self.container_id,
				"docstatus": ["!=", 2],
				"name": ["!=", self.name],
			},
			pluck="name",
		)
		if len(existing_inspections) == 0:
			return

		url = get_url_to_form("Container Inspection", existing_inspections[0])
		frappe.throw(
			f"Inspection <a href='{url}'><b>{existing_inspections[0]}</b></a> already exists for Container: "
			f"<b>{self.container_no}</b>.<br>If another inspection is needed, create an additional Booking "
			"from that Container Inspection record first."
		)

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
		"In Yard Container Booking",
		filters=filters,
		fields=[
			"name",
			"container_id",
			"inspection_date",
			"container_inspection",
			"is_additional_booking",
		],
	)
	if len(bookings) == 0:
		msg = ""
		if data.get("m_bl_no"):
			msg = f"M BL No: <b>{data.get('m_bl_no')}</b>"
		elif data.get("h_bl_no"):
			msg = f"H BL No: <b>{data.get('h_bl_no')}</b>"

		frappe.msgprint(f"No submitted Container Bookings found for {msg}")
		return

	container_ids = [booking.container_id for booking in bookings]
	inspected_containers = set(
		frappe.db.get_all(
			"Container Inspection",
			filters={"container_id": ["in", container_ids], "docstatus": ["!=", 2]},
			fields=["container_id"],
			pluck="container_id",
		)
	)
	delivered_containers = set(get_delivered_containers(container_ids))

	count = 0
	skipped = 0
	for booking in bookings:
		if booking.container_id in delivered_containers:
			skipped += 1
			continue

		if booking.container_inspection:
			skipped += 1
			continue

		# an additional booking always needs its own inspection
		if booking.is_additional_booking != 1 and booking.container_id in inspected_containers:
			skipped += 1
			continue

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

	if skipped > 0:
		frappe.msgprint(
			f"Skipped <b>{skipped}</b> of <b>{len(bookings)}</b> Booking(s), they already have an Inspection "
			"or their containers have already been delivered"
		)

	return count
