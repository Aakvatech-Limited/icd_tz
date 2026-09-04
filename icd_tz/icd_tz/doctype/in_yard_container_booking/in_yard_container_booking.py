# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_url_to_form, now_datetime, nowdate

from icd_tz.icd_tz.api.utils import (
	DELIVERED_CONTAINER_STATUSES,
	set_container_cf_company,
	validate_delivered_container,
)


class InYardContainerBooking(Document):
	def before_insert(self):
		validate_delivered_container(self.container_id, self.container_no)
		self.posting_datetime = now_datetime()

	def before_cancel(self):
		validate_delivered_container(self.container_id, self.container_no, action="cancelled")

	def after_insert(self):
		frappe.db.set_value("Container", self.container_id, "status", "At Booking")

	def before_save(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company")

	def validate(self):
		validate_cf_agent(self.c_and_f_company, self.clearing_agent)
		self.validate_duplicate_booking()

	def validate_duplicate_booking(self):
		"""Allow one booking per container, a repeat one must come from a Container Inspection"""

		if self.is_additional_booking == 1:
			return

		existing_bookings = frappe.db.get_all(
			"In Yard Container Booking",
			filters={
				"container_id": self.container_id,
				"docstatus": ["!=", 2],
				"name": ["!=", self.name],
			},
			pluck="name",
		)
		if len(existing_bookings) == 0:
			return

		url = get_url_to_form("In Yard Container Booking", existing_bookings[0])
		frappe.throw(
			f"Booking <a href='{url}'><b>{existing_bookings[0]}</b></a> already exists for Container: "
			f"<b>{self.container_no}</b>.<br>If another booking is needed, create it from the Container "
			"Inspection record of this container."
		)

	def before_submit(self):
		self.posting_datetime = now_datetime()

	def on_submit(self):
		frappe.db.set_value("Container", self.container_id, {"booking_date": nowdate()})
		set_container_cf_company(self)


def validate_cf_agent(c_and_f_company, clearing_agent):
	if c_and_f_company and clearing_agent:
		cf_company = frappe.get_cached_value("Clearing Agent", clearing_agent, "c_and_f_company")

		if c_and_f_company != cf_company:
			frappe.throw(
				f"The selected Clearing Agent: <b>{clearing_agent}</b> does not belong to the selected Clearing and Forwarding Company: <b>{c_and_f_company}</b>"
			)


@frappe.whitelist()
def create_bulk_bookings(data):
	data = frappe.parse_json(data)
	validate_cf_agent(data.get("c_and_f_company"), data.get("clearing_agent"))

	filters = {
		"status": ["not in", DELIVERED_CONTAINER_STATUSES],
	}

	if data.get("m_bl_no"):
		filters["m_bl_no"] = data.get("m_bl_no")
		filters["has_hbl"] = 0
	elif data.get("h_bl_no"):
		filters["h_bl_no"] = data.get("h_bl_no")
		filters["has_hbl"] = 1

	containers = frappe.db.get_all("Container", filters=filters, pluck="name")
	msg = ""
	if data.get("m_bl_no"):
		msg = f"M BL No: <b>{data.get('m_bl_no')}</b>"
	elif data.get("h_bl_no"):
		msg = f"H BL No: <b>{data.get('h_bl_no')}</b>"

	if len(containers) == 0:
		frappe.msgprint(f"No Containers found for {msg} or they have already been delivered")
		return

	booked_containers = set(
		frappe.db.get_all(
			"In Yard Container Booking",
			filters={"container_id": ["in", containers], "docstatus": ["!=", 2]},
			pluck="container_id",
		)
	)

	count = 0
	skipped = 0
	for container_id in containers:
		if container_id in booked_containers:
			skipped += 1
			continue

		doc = frappe.new_doc("In Yard Container Booking")
		doc.c_and_f_company = data.get("c_and_f_company")
		doc.clearing_agent = data.get("clearing_agent")
		doc.container_id = container_id
		doc.m_bl_no = data.get("m_bl_no")
		doc.h_bl_no = data.get("h_bl_no")
		doc.inspection_date = data.get("inspection_date")
		doc.inspection_location = data.get("inspection_location")

		doc.flags.ignore_permissions = True
		doc.insert()
		doc.reload()

		if doc.get("name"):
			count += 1

	if skipped > 0:
		frappe.msgprint(
			f"Skipped <b>{skipped}</b> of <b>{len(containers)}</b> container(s) for {msg}, "
			"they already have a Booking"
		)

	return count


@frappe.whitelist()
def create_additional_booking(container_inspection, inspection_date, inspection_location):
	"""Create a repeat booking for a container whose inspection was not satisfactory"""

	inspection = frappe.get_cached_doc("Container Inspection", container_inspection)
	source_booking = frappe.get_cached_doc("In Yard Container Booking", inspection.in_yard_container_booking)

	doc = frappe.new_doc("In Yard Container Booking")
	doc.update(
		{
			"c_and_f_company": source_booking.c_and_f_company,
			"clearing_agent": source_booking.clearing_agent,
			"consignee": source_booking.consignee,
			"container_id": source_booking.container_id,
			"m_bl_no": source_booking.m_bl_no,
			"h_bl_no": source_booking.h_bl_no,
			"inspection_date": inspection_date,
			"inspection_location": inspection_location,
			"is_additional_booking": 1,
			"source_container_inspection": inspection.name,
		}
	)

	doc.flags.ignore_permissions = True
	doc.insert()

	doc.add_comment(
		"Comment",
		f"Additional booking created from Container Inspection: <b>{inspection.name}</b>",
	)

	return doc.name
