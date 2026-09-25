# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from icd_tz.icd_tz.api.utils import (
	DELIVERED_CONTAINER_STATUSES,
	get_service_item,
	get_service_key,
	set_container_cf_company,
	throw_missing_criteria,
	validate_cf_agent,
	validate_delivered_container,
	validate_draft_doc,
)


class ServiceOrder(Document):
	def before_insert(self):
		self.validate_not_an_empty_container()
		validate_delivered_container(self.container_id, self.container_no)
		self.set_missing_values()
		self.set_gross_volume()
		self.validate_draft_references()
		self.get_services()

	def after_insert(self):
		frappe.db.set_value("Container", self.container_id, "status", "At Payments")

	def before_save(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company")

		self.set_gross_volume()

	def validate(self):
		validate_cf_agent(self)

	def before_submit(self):
		self.validate_mandatory_fields()
		self.set_gross_volume()

	def on_submit(self):
		self.create_getpass()
		set_container_cf_company(self)

	def before_cancel(self):
		validate_delivered_container(self.container_id, self.container_no, action="cancelled")
		self.check_for_gate_pass()

	def validate_not_an_empty_container(self):
		"""An empty box is owed by the shipping line, for storage and nothing else

		It carries no cargo, so shore handling, corridor levy, stripping, verification
		and removal cannot arise on it. Its storage is billed straight from the Sales
		Order dialog instead.
		"""

		if not self.container_id:
			return

		if not frappe.get_cached_value("Container", self.container_id, "is_empty_container"):
			return

		frappe.throw(
			_("Container {0} is an empty container, create sales order for this container direct").format(
				frappe.bold(self.container_no or self.container_id)
			),
			title=_("Empty Container"),
		)

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

	@property
	def is_loose_cargo(self) -> bool:
		"""Loose cargo is priced on its own table, where a container size does not apply"""

		return self.container_status == "LCL"

	def set_gross_volume(self):
		"""LCL services are charged by volume, so an order without one would bill nothing

		The Container is where a missing volume is corrected, so it is read again here.
		"""

		if not self.is_loose_cargo or flt(self.gross_volume):
			return

		self.gross_volume = frappe.db.get_value("Container", self.container_id, "gross_volume")
		if flt(self.gross_volume):
			return

		frappe.throw(
			_("Container {0} is LCL and has no Gross Volume, set it on the container to continue").format(
				frappe.bold(self.container_no)
			),
			title=_("Gross Volume Missing"),
		)

	def get_criteria_key(self, cargo_type: str | None = None) -> dict:
		"""Criteria this container is matched on when a service is priced

		The reception carries its own cargo type, which the Container overwrites from the
		house bill, so a caller holding the reception value passes it rather than losing it.
		"""

		if not cargo_type:
			cargo_type = frappe.get_cached_value("Container", self.container_id, "cargo_type")

		return get_service_key(size=self.container_size, cargo_type=cargo_type, port=self.port)

	def find_service_item(self, settings_doc, service_type: str, key: dict) -> str | None:
		"""Item this container is charged for a service, or None when no criteria row fits"""

		return get_service_item(settings_doc, service_type, key, is_loose_cargo=self.is_loose_cargo)

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

			if self.is_loose_cargo or not reception_details.t_sales_invoice:
				key = self.get_criteria_key(reception_details.cargo_type)
				transport_item = self.find_service_item(settings_doc, "Transport", key)

				if not transport_item and not reception_details.t_sales_invoice:
					throw_missing_criteria("Transport", key)

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

			if self.is_loose_cargo or not reception_details.s_sales_invoice:
				key = self.get_criteria_key(reception_details.cargo_type)
				shore_handling_item = self.find_service_item(settings_doc, "Shore", key)

				if not shore_handling_item and not reception_details.s_sales_invoice:
					throw_missing_criteria("Shore Handling", key)

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
		key = self.get_criteria_key()
		for booking in booking_details:
			if not booking.s_sales_invoice and booking.has_stripping_charges == "Yes":
				stripping_item = self.find_service_item(settings_doc, "Stripping", key)
				if not stripping_item:
					throw_missing_criteria("Stripping", key)

				strips.append(stripping_item)

			if not booking.cv_sales_invoice and booking.has_custom_verification_charges == "Yes":
				verification_item = self.find_service_item(settings_doc, "Verification", key)
				if not verification_item:
					throw_missing_criteria("Custom Verification", key)

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

		service_names = [row.get("service") for row in self.get("services")]

		key = self.get_criteria_key(container_doc.cargo_type)
		corridor_item = self.find_service_item(settings_doc, "Levy", key)
		if not corridor_item:
			throw_missing_criteria("Corridor Levy", key)

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

				# only inspections made before it stopped being added carry a verification row
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
		filters["is_empty_container"] = 0
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
