# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from icd_tz.icd_tz.api.sales_order import get_container_days_to_be_billed
from icd_tz.icd_tz.api.utils import (
	DELIVERED_CONTAINER_STATUSES,
	validate_cf_agent,
	validate_delivered_container,
	validate_draft_doc,
)


class ServiceOrder(Document):
	def before_insert(self):
		validate_delivered_container(self.container_id, self.container_no)
		self.set_missing_values()
		self.validate_draft_references()
		self.get_services()

	def after_insert(self):
		frappe.db.set_value("Container", self.container_id, "status", "At Payments")

	def before_save(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company")

	def validate(self):
		validate_cf_agent(self)

	def before_submit(self):
		self.validate_mandatory_fields()

	def on_submit(self):
		self.create_getpass()

	def before_cancel(self):
		validate_delivered_container(self.container_id, self.container_no, action="cancelled")
		self.check_for_gate_pass()

	def check_for_gate_pass(self):
		orders = frappe.db.get_all(
			"Service Order",
			filters={"container_id": self.container_id, "docstatus": 1, "name": ["!=", self.name]},
		)
		if len(orders) > 0:
			return

		if not self.get_pass:
			return

		get_pass = frappe.get_cached_doc("Gate Pass", self.get_pass)

		self.gate_pass = ""

		if get_pass.docstatus == 1:
			get_pass.cancel()

		get_pass.delete(ignore_permissions=True, force=True)
		self.db_set("get_pass", "")

	def set_missing_values(self):
		if self.container_id:
			container_doc = frappe.get_doc("Container", self.container_id)

			self.manifest = container_doc.manifest
			self.vessel_name = container_doc.ship
			self.port = container_doc.port_of_destination
			self.place_of_destination = container_doc.place_of_destination
			self.country_of_destination = container_doc.country_of_destination
			self.consignee = container_doc.consignee
			if not self.m_bl_no:
				self.m_bl_no = container_doc.m_bl_no
			if not self.h_bl_no and container_doc.has_hbl == 1:
				self.h_bl_no = container_doc.h_bl_no

			inspection_info = frappe.get_cached_value(
				"Container Inspection",
				{"container_id": self.container_id},
				["name", "c_and_f_company", "clearing_agent"],
				as_dict=True,
			)

			if inspection_info:
				self.c_and_f_company = inspection_info.c_and_f_company
				self.clearing_agent = inspection_info.clearing_agent

			if not self.c_and_f_company or not self.clearing_agent:
				booking_info = frappe.get_cached_value(
					"In Yard Container Booking",
					{"container_id": self.container_id},
					["name", "c_and_f_company", "clearing_agent"],
					as_dict=True,
				)
				if booking_info:
					self.c_and_f_company = booking_info.c_and_f_company
					self.clearing_agent = booking_info.clearing_agent

	def validate_draft_references(self):
		draft_inspections = frappe.db.get_all(
			"Container Inspection", filters={"container_id": self.container_id, "docstatus": 0}
		)
		if len(draft_inspections) > 0:
			frappe.throw(
				f"There are <b>{len(draft_inspections)}</b> draft Container Inspection(s) for Container: {self.container_no}, Please submit them to continue"
			)

		draft_bookings = frappe.db.get_all(
			"In Yard Container Booking", filters={"container_id": self.container_id, "docstatus": 0}
		)
		if len(draft_bookings) > 0:
			frappe.throw(
				f"There are <b>{len(draft_bookings)}</b> draft In Yard Container Booking(s) for Container: {self.container_no}, Please submit them to continue"
			)

	def get_services(self):
		settings_doc = frappe.get_cached_doc("ICD TZ Settings")

		self.get_reception_services(settings_doc)
		self.get_booking_services(settings_doc)
		self.get_corridor_services(settings_doc)
		self.get_other_charges()

	def get_reception_services(self, settings_doc):
		if not self.container_id:
			return

		container_reception = frappe.db.get_value("Container", self.container_id, "container_reception")
		reception_details = frappe.get_cached_value(
			"Container Reception",
			container_reception,
			[
				"cargo_type",
				"has_transport_charges",
				"t_sales_invoice",
				"has_shore_handling_charges",
				"s_sales_invoice",
			],
			as_dict=True,
		)
		if not reception_details:
			return

		service_names = [row.get("service") for row in self.get("services")]
		if reception_details.has_transport_charges == "Yes":
			transport_item = None
			transport_paid = True if reception_details.t_sales_invoice else False

			if self.container_status == "LCL":
				for row in settings_doc.loose_types:
					if row.service_type == "Transport":
						transport_paid = False
						transport_item = row.service_name
						break
			elif not reception_details.t_sales_invoice and self.container_status != "LCL":
				for row in settings_doc.service_types:
					if row.service_type == "Transport" and row.cargo_type == reception_details.cargo_type:
						transport_item = row.service_name
						transport_paid = False
						break

			if not transport_item and not transport_paid:
				frappe.throw(
					"Transport Pricing Criteria is not set in ICD TZ Settings, Please set it to continue"
				)

			if transport_item and transport_item not in service_names:
				self.append(
					"services",
					{
						"service": transport_item,
						"qty": self.gross_volume if self.container_status == "LCL" else 1,
					},
				)

		if reception_details.has_shore_handling_charges == "Yes":
			shore_handling_item = None
			shore_handling_paid = True if reception_details.s_sales_invoice else False

			if self.container_status == "LCL":
				for row in settings_doc.loose_types:
					if row.service_type == "Shore" and row.cargo_type == reception_details.cargo_type:
						shore_handling_paid = False
						shore_handling_item = row.service_name
						break
			elif not reception_details.s_sales_invoice and self.container_status != "LCL":
				for row in settings_doc.service_types:
					if (
						row.service_type == "Shore"
						and row.cargo_type == reception_details.cargo_type
						and row.port == self.port
					):
						if "2" in str(row.size)[0] and "2" in str(self.container_size)[0]:
							shore_handling_paid = False
							shore_handling_item = row.service_name
							break

						elif "4" in str(row.size)[0] and "4" in str(self.container_size)[0]:
							shore_handling_paid = False
							shore_handling_item = row.service_name
							break

						else:
							continue

			if not shore_handling_item and not shore_handling_paid:
				frappe.throw(
					f"Shore Handling Pricing Criteria for Size: {self.container_size}, Port: {self.port} and Cargo Type: {reception_details.cargo_type} is not set in ICD TZ Settings, Please set it to continue"
				)

			if shore_handling_item and shore_handling_item not in service_names:
				self.append(
					"services",
					{
						"service": shore_handling_item,
						"qty": self.gross_volume if self.container_status == "LCL" else 1,
						"remarks": f"Size: <b>{self.container_size}</b>, Cargo Type: <b>{reception_details.cargo_type}</b>, Port: <b>{self.port}</b>",
					},
				)

	def get_booking_services(self, settings_doc):
		if not self.container_id:
			return

		booking_details = frappe.db.get_all(
			"In Yard Container Booking",
			{"container_id": self.container_id, "docstatus": 1},
			[
				"has_stripping_charges",
				"s_sales_invoice",
				"has_custom_verification_charges",
				"cv_sales_invoice",
			],
		)
		if len(booking_details) == 0:
			return

		strips = []
		verifications = []
		for booking in booking_details:
			stripping_paid = True if booking.s_sales_invoice else False
			verification_paid = True if booking.cv_sales_invoice else False

			if not booking.s_sales_invoice and booking.has_stripping_charges == "Yes":
				stripping_item = None

				if self.container_status == "LCL":
					for row in settings_doc.loose_types:
						if row.service_type == "Stripping":
							stripping_paid = False
							stripping_item = row.service_name
							break
				else:
					for row in settings_doc.service_types:
						if row.service_type == "Stripping":
							if "2" in str(row.size)[0] and "2" in str(self.container_size)[0]:
								stripping_paid = False
								stripping_item = row.service_name
								break

							elif "4" in str(row.size)[0] and "4" in str(self.container_size)[0]:
								stripping_paid = False
								stripping_item = row.service_name
								break

							else:
								continue

				if not stripping_item and not stripping_paid:
					frappe.throw(
						f"Stripping Pricing Criteria for Size: {self.container_size} is not set in ICD TZ Settings, Please set it to continue"
					)

				strips.append(stripping_item)

			if not booking.cv_sales_invoice and booking.has_custom_verification_charges == "Yes":
				verification_item = None
				if self.container_status == "LCL":
					for row in settings_doc.loose_types:
						if row.service_type == "Verification":
							verification_paid = False
							verification_item = row.service_name
							break
				else:
					for row in settings_doc.service_types:
						if row.service_type == "Verification":
							if "2" in str(row.size)[0] and "2" in str(self.container_size)[0]:
								verification_paid = False
								verification_item = row.service_name
								break

							elif "4" in str(row.size)[0] and "4" in str(self.container_size)[0]:
								verification_paid = False
								verification_item = row.service_name
								break

							else:
								continue

				if not verification_item and not verification_paid:
					frappe.throw(
						f"Custom Verification Pricing criteria for Size: {self.container_size} is not set in ICD TZ Settings, Please set it to continue"
					)

				verifications.append(verification_item)

		if len(strips) > 0:
			self.append(
				"services",
				{
					"service": strips[0],
					"qty": len(strips) * self.gross_volume if self.container_status == "LCL" else len(strips),
					"remarks": "<b>Having multiple bookings</b>" if len(strips) > 1 else "",
				},
			)

		if len(verifications) > 0:
			self.append(
				"services",
				{
					"service": verifications[0],
					"qty": len(verifications) * self.gross_volume
					if self.container_status == "LCL"
					else len(verifications),
					"remarks": "<b>Having multiple bookings</b>" if len(verifications) > 1 else "",
				},
			)

	def get_corridor_services(self, settings_doc):
		if not self.container_id:
			return

		container_doc = frappe.get_doc("Container", self.container_id)
		if container_doc.has_corridor_levy_charges != "Yes":
			return

		if container_doc.c_sales_invoice:
			return

		corridor_item = None
		service_names = [row.get("service") for row in self.get("services")]

		if self.container_status == "LCL":
			for row in settings_doc.loose_types:
				if row.service_type == "Levy":
					corridor_item = row.service_name
					break
		else:
			for row in settings_doc.service_types:
				if row.service_type == "Levy":
					if "2" in str(row.size)[0] and "2" in str(self.container_size)[0]:
						corridor_item = row.service_name
						break

					elif "4" in str(row.size)[0] and "4" in str(self.container_size)[0]:
						corridor_item = row.service_name
						break

					else:
						continue

		if not corridor_item:
			frappe.throw(
				f"Corridor Levy Pricing Criteria for Size: {self.container_size} is not set in ICD TZ Settings, Please set it to continue"
			)

		if corridor_item and corridor_item not in service_names:
			self.append(
				"services",
				{"service": corridor_item, "qty": self.gross_volume if self.container_status == "LCL" else 1},
			)

	def get_other_charges(self):
		if not self.container_id:
			return

		inspeactions = frappe.db.get_all(
			"Container Inspection", {"container_id": self.container_id, "docstatus": 1}, ["name"]
		)
		if len(inspeactions) == 0:
			return

		insp_service_dict = {}
		for inspection in inspeactions:
			inspection_doc = frappe.get_doc("Container Inspection", inspection.name)

			for d in inspection_doc.get("services"):
				if d.get("sales_invoice"):
					continue

				if "verification" in str(d.get("service")).lower():
					continue

				if not d.get("service"):
					continue

				qty_to_add = self.gross_volume if self.container_status == "LCL" else 1
				if d.get("service") in insp_service_dict:
					insp_service_dict[d.get("service")]["qty"] += qty_to_add
					insp_service_dict[d.get("service")]["remarks"] = "<b>Having Multiple Inspections</b>"
				else:
					new_row = {"service": d.get("service"), "qty": qty_to_add}
					insp_service_dict[d.get("service")] = new_row

		for item in insp_service_dict.values():
			self.append("services", item)

	def create_getpass(self):
		"""
		Create a Get pass document
		"""
		exist_gate_pass = frappe.db.get_all(
			"Gate Pass", filters={"manifest": self.manifest, "container_id": self.container_id}
		)
		if len(exist_gate_pass) > 0:
			self.db_set("get_pass", exist_gate_pass[0].name)
			self.reload()
			return

		inspection_location = frappe.db.get_value(
			"In Yard Container Booking", {"container_id": self.container_id}, "inspection_location"
		)

		getpass = frappe.new_doc("Gate Pass")
		getpass.update(
			{
				"manifest": self.manifest,
				"c_and_f_company": self.c_and_f_company,
				"clearing_agent": self.clearing_agent,
				"consignee": self.consignee,
				"container_id": self.container_id,
				"container_no": self.container_no,
				"inspection_location": inspection_location,
			}
		)
		getpass.save(ignore_permissions=True)
		getpass.reload()

		self.db_set("get_pass", getpass.name)
		self.reload()

	def validate_mandatory_fields(self):
		fields = ["c_and_f_company", "clearing_agent", "consignee"]

		fields_str = ""
		for field in fields:
			if not self.get(field):
				fields_str += f"{self.meta.get_label(field)}, "

		if fields_str:
			frappe.throw(
				f"Please ensure the following fields are filled before submitting this document: <b>{fields_str}</b>"
			)


@frappe.whitelist()
def create_bulk_service_orders(data):
	data = frappe.parse_json(data)

	filters = {
		"status": ["not in", DELIVERED_CONTAINER_STATUSES],
	}

	if data.get("m_bl_no"):
		filters["m_bl_no"] = data.get("m_bl_no")
		filters["has_hbl"] = 0
	elif data.get("h_bl_no"):
		filters["h_bl_no"] = data.get("h_bl_no")
		filters["has_hbl"] = 1

	containers = frappe.db.get_all("Container", filters=filters, fields=["name"])

	msg = ""
	if data.get("m_bl_no"):
		msg = f"M BL No: <b>{data.get('m_bl_no')}</b>"
	elif data.get("h_bl_no"):
		msg = f"H BL No: <b>{data.get('h_bl_no')}</b>"

	if len(containers) == 0:
		frappe.msgprint(f"No Containers found for {msg}, or their containers have already been delivered")
		return

	count = 0
	for container in containers:
		doc = frappe.new_doc("Service Order")
		doc.container_id = container.name
		doc.m_bl_no = data.get("m_bl_no")
		doc.h_bl_no = data.get("h_bl_no")

		doc.flags.ignore_permissions = True
		doc.save()
		doc.reload()

		if doc.get("name"):
			count += 1

	return count
