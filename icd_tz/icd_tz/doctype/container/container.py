# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from time import sleep
from frappe.model.document import Document
from frappe.utils import nowdate, getdate, add_days

class Container(Document):
	def before_insert(self):
		if self.container_no and self.container_reception:
			self.update_m_bl_based_container_details()
			self.update_hbl_based_container_details()

			self.validate_place_of_destination()
			
			self.posting_date = nowdate()
	
	def before_save(self):
		self.validate_place_of_destination()
		self.update_container_reception()
		self.update_billed_days()
		self.update_billed_details()
		self.check_corridor_levy_eligibility()
		self.check_removal_charges_elibility()

	def update_m_bl_based_container_details(self):
		"""Update the container details from the Container Reception, Containers Detail and Container Movement Order"""

		if self.status == "Delivered":
			return
		
		container_reception = frappe.get_cached_doc("Container Reception", self.container_reception)

		if not self.status:
			self.status = "In Yard"
		if not self.size:
			self.size = container_reception.size
		if not self.volume:
			self.volume = container_reception.volume
		if not self.weight:
			self.weight = container_reception.weight
		if not self.seal_no_1:
			self.seal_no_1 = container_reception.seal_no_1
		if not self.seal_no_2:
			self.seal_no_2 = container_reception.seal_no_2
		if not self.seal_no_3:
			self.seal_no_3 = container_reception.seal_no_3
		if not self.port_of_destination:
			self.port_of_destination = container_reception.port
		if not self.original_location:
			self.original_location = container_reception.container_location
		if not self.current_location:
			self.current_location = container_reception.container_location
		if not self.abbr_for_destination:
			self.abbr_for_destination = container_reception.abbr_for_destination
		if not self.place_of_destination:
			self.place_of_destination = container_reception.place_of_destination
		if not self.country_of_destination:
			self.country_of_destination = container_reception.country_of_destination
		if not self.company:
			self.company = container_reception.company
		if not self.cargo_type:
			self.cargo_type = container_reception.cargo_type

		container_info = frappe.db.get_value(
			"Containers Detail", 
			{"parent": self.manifest, "container_no": self.container_no}, 
			["type_of_container", "m_bl_no", "freight_indicator", "no_of_packages", "package_unit", "volume_unit", "weight_unit"],
			as_dict=True
		)

		if container_info:
			if not self.type_of_container:
				self.type_of_container = container_info.type_of_container
			if not self.m_bl_no:
				self.m_bl_no = container_info.m_bl_no
			if not self.freight_indicator:
				self.freight_indicator = container_info.freight_indicator
			if not self.no_of_packages:
				self.no_of_packages = container_info.no_of_packages
			if not self.package_unit:
				self.package_unit = container_info.package_unit
			if not self.freight_indicator:
				self.freight_indicator = container_info.freight_indicator
			if not self.volume_unit:
				self.volume_unit = container_info.volume_unit
			if not self.weight_unit:
				self.weight_unit = container_info.weight_unit
		
		if self.m_bl_no:
			master_bl_info = frappe.db.get_value(
				"Master BL", 
				{"parent": self.manifest, "m_bl_no": self.m_bl_no}, 
				["*"],
				as_dict=True
			)
			
			# ["place_of_destination", "place_of_delivery", "port_of_loading", "consignee_name", "shipping_agent_code",
			# "shipping_agent_name", "cargo_description"],

			if master_bl_info:
				del master_bl_info["name"]
				del master_bl_info["parent"]
				del master_bl_info["parentfield"]
				del master_bl_info["parenttype"]
				del master_bl_info["idx"]
				del master_bl_info["docstatus"]
				del master_bl_info["owner"]
				del master_bl_info["creation"]
				del master_bl_info["modified"]
				del master_bl_info["modified_by"]

				place_of_destination = self.place_of_destination

				self.update(master_bl_info)

				self.abbr_for_destination = master_bl_info.place_of_destination
				self.place_of_destination = place_of_destination
				self.place_of_delivery = master_bl_info.place_of_delivery
				self.port_of_loading = master_bl_info.port_of_loading
				if not self.consignee:
					self.consignee = master_bl_info.consignee_name
				if not self.cargo_description:
					self.cargo_description = master_bl_info.cargo_description
				if not self.sline_code:
					self.sline_code = master_bl_info.shipping_agent_code
				if not self.sline:
					self.sline = master_bl_info.shipping_agent_name

		if len(self.container_dates) == 0:
			self.append("container_dates", {
				"date": self.recieved_date,
			})

	def update_hbl_based_container_details(self):
		"""Update the container details from the HBL Container"""
		if self.has_hbl == 0:
			return

		if self.status == "Delivered":
			return
		
		if not self.status:
			self.status = "In Yard"

		hbl_container_info = frappe.db.get_value(
			"HBL Container", 
			{"parent": self.manifest, "container_no": self.container_no, "h_bl_no": self.h_bl_no},
			[
				"type_of_container", "m_bl_no", "freight_indicator", "container_size", 
				"seal_no1", "seal_no2", "seal_no3", "no_of_packages", "package_unit", "volume",
				"volume_unit", "weight_unit", "plug_type_of_reefer", "minimum_temperature", "maximum_temperature"
			],
			as_dict=True
		)

		if hbl_container_info:
			if not self.type_of_container:
				self.type_of_container = hbl_container_info.type_of_container
			if not self.m_bl_no:
				self.m_bl_no = hbl_container_info.m_bl_no
			if not self.freight_indicator:
				self.freight_indicator = hbl_container_info.freight_indicator
			if not self.size:
				self.size = hbl_container_info.container_size
			if not self.no_of_packages:
				self.no_of_packages = hbl_container_info.no_of_packages
			if not self.package_unit:
				self.package_unit = hbl_container_info.package_unit
			if not self.volume:
				self.volume = hbl_container_info.volume
			if not self.volume_unit:
				self.volume_unit = hbl_container_info.volume_unit
			if not self.weight:
				self.weight = hbl_container_info.weight
			if not self.weight_unit:
				self.weight_unit = hbl_container_info.weight_unit
			if not self.seal_no_1:
				self.seal_no_1 = hbl_container_info.seal_no1
			if not self.seal_no_2:
				self.seal_no_2 = hbl_container_info.seal_no2
			if not self.seal_no_3:
				self.seal_no_3 = hbl_container_info.seal_no3
			if not self.plug_type_of_reefer:
				self.plug_type_of_reefer = hbl_container_info.plug_type_of_reefer
			if not self.minimum_temperature:
				self.minimum_temperature = hbl_container_info.minimum_temperature
			if not self.maximum_temperature:
				self.maximum_temperature = hbl_container_info.maximum_temperature
		
		if self.h_bl_no:
			house_bl_info = frappe.db.get_value(
				"House BL", 
				{"parent": self.manifest, "m_bl_no": self.h_bl_no}, 
				["*"],
				as_dict=True
			)
			# [
			# 	"cargo_classification", "place_of_destination", "place_of_delivery", "port_of_loading", "consignee_name",
			# 	"shipping_agent_code", "shipping_agent_name", "cargo_description", "net_weight", "net_weight_unit", "number_of_containers",
			# 	"description_of_goods", "number_of_package", "package_unit", "gross_weight", "gross_weight_unit", "gross_volume", "gross_volume_unit",
			# 	"shipping_agent_code", "shipping_agent_name"
			# ]

			if house_bl_info:
				del house_bl_info["name"]
				del house_bl_info["parent"]
				del house_bl_info["parentfield"]
				del house_bl_info["parenttype"]
				del house_bl_info["idx"]
				del house_bl_info["docstatus"]
				del house_bl_info["owner"]
				del house_bl_info["creation"]
				del house_bl_info["modified"]
				del house_bl_info["modified_by"]

				self.update(house_bl_info)

				country_code = str(house_bl_info.place_of_destination)[:2]
				country_of_destination = frappe.db.get_value(
					"Country", {"code": country_code.lower()}, "name"
				)
				place_of_destination = ""
				if country_code == "TZ":
					place_of_destination = "Local"
				elif country_code == "CD":
					place_of_destination = "DRC"
				else:
					place_of_destination = "Other"
				
				self.abbr_for_destination = house_bl_info.place_of_destination
				self.country_of_destination = country_of_destination
				self.place_of_destination = place_of_destination

				cargo_type = ""
				if house_bl_info.cargo_classification == "IM":
					cargo_type = "Local"
				elif house_bl_info.cargo_classification == "TR":
					cargo_type = "Transit"
				
				self.cargo_type = cargo_type

				if not self.container_count:
					self.container_count = "1/1"
				if not self.sline_code:
					self.sline_code = house_bl_info.shipping_agent_code
				if not self.sline:
					self.sline = house_bl_info.shipping_agent_name
				if not self.consignee:
					self.consignee = house_bl_info.consignee_name
				if not self.cargo_description:
					self.cargo_description = house_bl_info.cargo_description

		if len(self.container_dates) == 0:
			self.append("container_dates", {
				"date": self.recieved_date,
			})

	def update_billed_days(self):
		setting_doc = frappe.get_doc("ICD TZ Settings")

		no_of_free_days = 0
		no_of_single_days = 0
		no_of_double_days = 0
		for d in setting_doc.storage_days:
			if d.destination == self.place_of_destination:
				if d.charge == "Free":
					no_of_free_days = d.get("to") - d.get("from") + 1

				elif d.charge == "Single":
					no_of_single_days = d.get("to") - d.get("from") + 1

				elif d.charge == "Double":
					no_of_double_days = d.get("to") - d.get("from") + 1
		
		free_count = 0
		charge_count = 0
		for row in self.container_dates:
			if free_count < no_of_free_days:
				row.is_free = 1
				row.is_billable = 0
				free_count += 1
			
			elif row.is_billable == 1  and row.is_free == 0:
				charge_count += 1
		
		if charge_count == 0:
			self.has_single_charge = 0
			self.has_double_charge = 0
		
		elif charge_count > 0 and charge_count <= no_of_single_days:
			self.has_single_charge = 1
			self.has_double_charge = 0
		
		elif charge_count > no_of_single_days:
			self.has_single_charge = 1
			self.has_double_charge = 1
		
	def update_billed_details(self):
		"""Update the billed days of the container"""
		
		if self.status == "Delivered":
			return
		
		if len(self.container_dates) > 0:
			no_of_free_days = 0
			no_of_billable_days = 0
			no_of_writeoff_days = 0
			no_of_billed_days = 0

			for row in self.container_dates:
				if row.is_billable == 0 and row.is_free == 1:
					no_of_free_days += 1
					
				if row.is_billable == 1 and row.is_free == 0:
					no_of_billable_days += 1
				
				if row.is_billable == 0 and row.is_free == 0:
					no_of_writeoff_days += 1
				
				if row.sales_invoice:
					no_of_billed_days += 1

			
			self.total_days = len(self.container_dates)
			self.no_of_free_days = no_of_free_days
			self.no_of_billable_days = no_of_billable_days
			self.no_of_writeoff_days = no_of_writeoff_days
			self.no_of_billed_days = no_of_billed_days
			self.days_to_be_billed = no_of_billable_days - no_of_billed_days	

	def check_removal_charges_elibility(self):
		"""Check if the container is eligible to remove charges"""

		if self.r_sales_invoice:
			self.has_removal_charges = "No"
		elif self.days_to_be_billed > 0:
			self.has_removal_charges = "Yes"
		elif self.days_to_be_billed <= 0:
			if self.has_single_charge == 1 or self.has_double_charge == 1:
				self.has_removal_charges = "Yes"
			else:
				self.has_removal_charges = "No"

	def check_corridor_levy_eligibility(self):
		"""Check if the container is eligible for Corridor Levy payments"""

		if not self.country_of_destination:
			self.has_corridor_levy_charges = "No"
			return
		
		is_eligible_for_corridor_levy_payments = False
		icd_settings = frappe.get_doc("ICD TZ Settings")
		for row in icd_settings.countries:
			if row.country == self.country_of_destination:
				is_eligible_for_corridor_levy_payments = True
				break
		
		if is_eligible_for_corridor_levy_payments:
			if self.c_sales_invoice:
				self.has_corridor_levy_charges = "No"
			else:
				self.has_corridor_levy_charges = "Yes"

			# corridor levy does not depend on storage days (2025-04-19)
			# elif self.days_to_be_billed > 0:
			# 	self.has_corridor_levy_charges = "Yes"
			# elif self.days_to_be_billed <= 0:
			# 	if self.has_single_charge == 1 or self.has_double_charge == 1:
			# 		self.has_corridor_levy_charges = "Yes"
			# 	else:
			# 		self.has_corridor_levy_charges = "No"
		else:
			self.has_corridor_levy_charges = "No"
	
	def update_container_reception(self):
		container_reception = frappe.get_cached_doc("Container Reception", self.container_reception)
	
		if self.place_of_destination and self.place_of_destination != container_reception.place_of_destination:
			container_reception.db_set("place_of_destination", self.place_of_destination)
		
		if self.country_of_destination and self.country_of_destination != container_reception.country_of_destination:
			container_reception.db_set("country_of_destination", self.country_of_destination)
		
	def validate_place_of_destination(self):
		if not self.place_of_destination:
			return
		
		places = get_place_of_destination()
		places_str = ", ".join(places)
		if self.place_of_destination not in places:
			frappe.throw(f"Invalid Place of Destination <b>{self.place_of_destination}</b>, valid places are: <b>{places_str}</b>")

	def update_container_stay(self, up_to_date=None):
		current_date = getdate(nowdate())
		if up_to_date:
			current_date = getdate(up_to_date)

		container_dates_len = len(self.container_dates)

		if container_dates_len > 0:
			last_row = self.container_dates[container_dates_len - 1]
			last_date = getdate(last_row.date)

			while last_date < current_date:
				new_row = self.append("container_dates", {})
				last_date = add_days(last_date, 1)
				new_row.date = last_date

		elif container_dates_len == 0:
			start_date = self.received_date
			if start_date:
				while getdate(start_date) <= current_date:
					new_row = self.append("container_dates", {})
					new_row.date = start_date
					start_date = add_days(start_date, 1)

		self.save(ignore_permissions=True)


@frappe.whitelist()
def get_place_of_destination():
	destinations = []

	icd_doc = frappe.get_doc("ICD TZ Settings")

	for row in icd_doc.storage_days:
		destinations.append(row.destination)

	return set(destinations)


def daily_update_date_container_stay(container_id=None):
	sleep(20)
	containers = []
	if container_id:
		containers.append(container_id)
	else:
		containers = frappe.get_all("Container", filters={"status": ["!=", "Delivered"]}, pluck="name")
	
	for container_id in containers:
		try:
			doc = frappe.get_doc("Container", container_id)
			doc.update_container_stay()
		
		except Exception:
			frappe.log_error(
                str(f"<b>{container_id}</b> Daily Update Container Dates"),
                frappe.get_traceback()
            )
			continue

