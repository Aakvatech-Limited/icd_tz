# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from icd_tz.icd_tz.api.icd_services import BOOKING, SERVICES
from icd_tz.icd_tz.api.utils import (
	DELIVERED_CONTAINER_STATUSES,
	get_service_key,
	set_container_cf_company,
	validate_cf_agent,
	validate_delivered_container,
	validate_no_draft_container_records,
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
		validate_no_draft_container_records(self.container_id, self.container_no)
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

	def get_criteria_key(self, container) -> dict:
		"""Criteria this container is matched on when a service is priced"""

		return get_service_key(size=self.container_size, cargo_type=container.cargo_type, port=self.port)

	@property
	def unit_qty(self) -> float:
		"""Quantity of one service line: the volume for loose cargo, else one container"""

		return flt(self.gross_volume) if self.is_loose_cargo else 1

	def get_services(self):
		self.add_container_services(frappe.get_cached_doc("ICD TZ Settings"))
		self.get_other_charges()

	def add_container_services(self, settings_doc):
		"""Add a line for each flagged service the Container still owes"""

		if not self.container_id:
			return

		container = frappe.get_doc("Container", self.container_id)
		booked_qty = container.booking_count * self.unit_qty
		for service in SERVICES:
			if service.scope == BOOKING:
				self.add_booking_service(settings_doc, container, service, booked_qty)
			elif service.on_service_order:
				self.add_charged_service(settings_doc, container, service)

	def add_charged_service(self, settings_doc, container, service):
		"""Add a service charged once on the Container"""

		key = self.get_criteria_key(container)
		service_item = service.get_order_item(container, settings_doc, key, self.is_loose_cargo)
		if not service_item or service_item in [row.service for row in self.services]:
			return

		row = {"service": service_item, "qty": self.unit_qty}
		if service.show_criteria:
			row["remarks"] = (
				f"Size: <b>{self.container_size}</b>, Cargo Type: <b>{container.cargo_type}</b>, Port: <b>{self.port}</b>"
			)

		self.append("services", row)

	def add_booking_service(self, settings_doc, container, service, booked_qty):
		"""Each submitted booking is stripped and verified once, less what was already billed"""

		qty = flt(
			service.get_unbilled_qty(container, settings_doc, booked_qty),
			self.precision("qty", "services"),
		)
		if qty <= 0:
			return

		service_item = service.find_item(settings_doc, self.get_criteria_key(container), self.is_loose_cargo)
		self.append("services", {"service": service_item, "qty": qty})

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

				qty_to_add = self.unit_qty
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
