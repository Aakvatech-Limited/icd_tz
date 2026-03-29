# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.query_builder import DocType
from frappe.model.document import Document
from frappe.utils.background_jobs import enqueue
from frappe.utils import get_link_to_form, nowdate, getdate, add_days
from icd_tz.icd_tz.doctype.container.container import daily_update_date_container_stay
from icd_tz.icd_tz.api.edi_codeco import generate_codeco_gate_in

cr = DocType("Container Reception")

class ContainerReception(Document):
	def before_save(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company")
		
		if not self.posting_date:
			self.posting_date = nowdate()

	def validate(self):
		self.validate_duplicate_cr()

	def before_submit(self):
		if not self.clerk:
			frappe.throw("Clerk is missing, Please select clerk to proceed..!")
			
		edi_settings = frappe.get_single("EDI Settings")
		if edi_settings.enable_edi and edi_settings.connection_type == "SMTP":
			self.receiver_email = edi_settings.receiver_email
			self.receiver_cc_email = edi_settings.receiver_cc_email

		try:
			edi_data = generate_codeco_gate_in(self.name, file_type="txt")
			if edi_data and edi_data.get("edi_content"):
				file_doc = frappe.get_doc({
					"doctype": "File",
					"file_name": edi_data.get("filename"),
					"content": edi_data.get("edi_content"),
					"attached_to_doctype": self.doctype,
					"attached_to_name": self.name,
					"is_private": 1
				})
				file_doc.insert(ignore_permissions=True)
				self.edi_file = file_doc.file_url
		except Exception as e:
			traceback = frappe.get_traceback()
			msg = f"Failed to generate Gate In EDI: {str(e)}\n\nTraceback: {traceback}"
			frappe.log_error(title="Failed to generate Gate In EDI", message=msg, reference=self.name, reference_doctype=self.doctype)

	def on_submit(self):
		edi_settings = frappe.get_single("EDI Settings")
		if edi_settings.enable_edi and not self.edi_file:
			frappe.throw("EDI File is missing. Cannot submit when EDI is enabled.")

		self.create_mbl_container()
		self.create_hbl_container()
		self.update_container_storage_days()
		self.update_cmo_status("Received")

	def before_cancel(self):
		self.cancel_linked_docs()
	
	def on_cancel(self):
		self.update_cmo_status()

	def validate_duplicate_cr(self):
		"""Validate that there is no duplicate Container Reception based on Container Movement Order (CMO)"""
		if self.movement_order:
			duplicates = (
				frappe.qb.from_(cr)
				.select(
					cr.name
				)
				.where(
					(cr.movement_order == self.movement_order)
					& (cr.name != self.name)
				)
			).run(as_dict=True)

			if len(duplicates) > 0:
				url = get_link_to_form("Container Reception", duplicates[0].name)
				frappe.throw(
					f"Another Container Reception with the same Movement Order already exists: <a href='{url}'><b>{duplicates[0].name}</b></a>"
				)

	def create_mbl_container(self):
		"""Create a Container record from the Container Reception"""

		container = frappe.new_doc("Container")
		container.container_reception = self.name
		container.container_no = self.container_no
		container.size = self.size
		container.volume = self.volume
		container.weght = self.weight
		container.seal_no_1 = self.seal_no_1
		container.seal_no_2 = self.seal_no_2
		container.seal_no_3 = self.seal_no_3
		container.port_of_destination = self.port
		container.arrival_date = self.ship_dc_date
		container.received_date = self.received_date
		container.original_location = self.container_location
		container.current_location = self.container_location
		container.abbr_for_destination = self.abbr_for_destination
		container.place_of_destination = self.place_of_destination
		container.country_of_destination = self.country_of_destination
		container.manifest = self.manifest
		container.movement_order = self.movement_order
		container.m_bl_no = self.m_bl_no
		container.container_count = self.container_count
		container.status = "In Yard"

		if self.freight_indicator == "LCL":
			container.is_empty_container = 1

		container.append("container_dates", {
			"date": self.received_date,
		})
		container.save(ignore_permissions=True)

		enqueue(
			method=daily_update_date_container_stay,
			container_id=container.name
		)

		return container.name

	def create_hbl_container(self):
		"""Create a HBL Container record based on freight indicator on container reception"""
		
		if self.freight_indicator != "LCL":
			return

		# Find all records from 'HBL Container' doctypes using filters of container_no and manifest
		hbl_containers = frappe.db.get_all(
			"HBL Container",
			filters={
				"container_no": self.container_no,
				"parent": self.manifest
			},
			fields=["*"]
		)

		if len(hbl_containers) == 0:
			frappe.msgprint(f"No HBL Container records found for Container No: <b>{self.container_no}</b> in Manifest: <b>{self.manifest}</b>")
			return

		# Create containers based on the information found
		count = 0
		for hbl_container in hbl_containers:
			container = frappe.new_doc("Container")
			container.container_reception = self.name
			container.container_no = hbl_container.container_no
			container.size = hbl_container.container_size
			container.volume = hbl_container.volume
			container.volume_unit = hbl_container.volume_unit
			container.weight = hbl_container.weight
			container.weight_unit = hbl_container.weight_unit
			container.seal_no_1 = hbl_container.seal_no1
			container.seal_no_2 = hbl_container.seal_no2
			container.seal_no_3 = hbl_container.seal_no3
			container.port_of_destination = self.port
			container.arrival_date = self.ship_dc_date
			container.received_date = self.received_date
			container.original_location = self.container_location
			container.current_location = self.container_location
			# container.place_of_destination = self.place_of_destination
			# container.country_of_destination = self.country_of_destination
			container.manifest = self.manifest
			container.movement_order = self.movement_order
			container.m_bl_no = hbl_container.m_bl_no
			container.h_bl_no = hbl_container.h_bl_no
			container.status = "In Yard"
			container.has_hbl = 1
			container.type_of_container = hbl_container.type_of_container
			container.plug_type_of_reefer = hbl_container.plug_type_of_reefer
			container.minimum_temperature = hbl_container.minimum_temperature
			container.maximum_temperature = hbl_container.maximum_temperature
			container.container_count = 1

			container.append("container_dates", {
				"date": self.received_date,
			})

			container.save(ignore_permissions=True)
			container.reload()
			count += 1

			enqueue(
				method=daily_update_date_container_stay,
				container_id=container.name
			)
		
		if count > 0:
			frappe.msgprint(f"HBL records: {count} were created for container {self.container_no}", alert=True)

	def update_container_storage_days(self):
		"""Update the storage days of the containers based on the current received date and m_bl_no"""

		records = (
			frappe.qb.from_(cr)
			.select(
				cr.name
			)
			.where(
				(cr.name != self.name)
				& (cr.m_bl_no == self.m_bl_no)
				& (cr.manifest == self.manifest)
				& (cr.received_date != self.received_date)
			)
		).run(as_dict=True)

		if len(records) == 0:
			return

		for record in records:
			frappe.db.set_value(
				"Container Reception",
				record.name,
				"received_date",
				self.received_date,
				update_modified=False
			)

			container_ids = frappe.db.get_all(
				"Container",
				{"container_reception": record.name},
				["name"]
			)
			if len(container_ids) == 0:
				continue
			
			for container_id in container_ids:
				container_doc = frappe.get_doc("Container", container_id)
				container_doc.container_dates = []
				container_doc.arrival_date = self.ship_dc_date
				container_doc.received_date = self.received_date
				container_doc.append("container_dates", {
					"date": self.received_date,
				})
				container_doc.save(ignore_permissions=True)

				enqueue(
					method=daily_update_date_container_stay,
					container_id=container_doc.name
				)

	def cancel_linked_docs(self):
		container_id = frappe.db.get_value(
			"Container",
			{"container_reception": self.name},
			["name"]
		)

		if not container_id:
			return

		# Check for related documents and their invoice status
		error_messages = []
		docs_to_cancel = []

		# Check Service Order
		service_orders = frappe.db.get_all(
			"Service Order",
			filters={"container_id": container_id},
			fields=["name", "sales_invoice",  "sales_order"]
		)

		sales_order_ids = []
		for service_order in service_orders:
			if service_order.sales_invoice:
				service_order_url = get_link_to_form("Service Order", service_order.name)
				invoice_url = get_link_to_form("Sales Invoice", service_order.sales_invoice)
				error_messages.append(f"Service Order <a href='{service_order_url}'>{service_order.name}</a> has invoice: <a href='{invoice_url}'>{service_order.sales_invoice}</a>")
			else:
				if (
					not service_order.sales_invoice and
					service_order.sales_order and
					service_order.sales_order not in sales_order_ids
				):
					sales_order_ids.append(service_order.sales_order)

				docs_to_cancel.append({"doc_type": "Service Order", "doc_name": service_order.name})

		# Check Container Inspection
		inspections = frappe.db.get_all(
			"Container Inspection",
			filters={"container_id": container_id},
			fields=["name"]
		)

		for inspection in inspections:
			inspection_doc = frappe.get_doc("Container Inspection", inspection.name)
			invoice_links = []

			for row in inspection_doc.services:
				if "verification" in str(row.service).lower():
					continue

				if row.sales_invoice:
					invoice_links.append((row.service, row.sales_invoice))

			if len(invoice_links) > 0:
				inspection_url = get_link_to_form("Container Inspection", inspection.name)
				error_messages.append(f"Container Inspection <a href='{inspection_url}'>{inspection.name}</a> has the following invoices:")
				for service_name, invoice_id in invoice_links:
					invoice_url = get_link_to_form("Sales Invoice", invoice_id)
					error_messages.append(f"- {service_name}: <a href='{invoice_url}'>{invoice_id}</a>")
			else:
				docs_to_cancel.append({"doc_type": "Container Inspection", "doc_name": inspection.name})

		# Check In Yard Container Booking
		bookings = frappe.db.get_all(
			"In Yard Container Booking",
			filters={"container_id": container_id},
			fields=["name", "s_sales_invoice", "cv_sales_invoice"]
		)

		for booking in bookings:
			invoice_links = []
			if booking.s_sales_invoice:
				invoice_links.append(("Stripping Charges", booking.s_sales_invoice))
			if booking.cv_sales_invoice:
				invoice_links.append(("Custom Verification Charges", booking.cv_sales_invoice))

			if len(invoice_links) > 0:
				booking_url = get_link_to_form("In Yard Container Booking", booking.name)
				error_messages.append(f"In Yard Container Booking <a href='{booking_url}'>{booking.name}</a> has the following invoices:")
				for charge_type, invoice_id in invoice_links:
					invoice_url = get_link_to_form("Sales Invoice", invoice_id)
					error_messages.append(f"- {charge_type}: <a href='{invoice_url}'>{invoice_id}</a>")

			else:
				docs_to_cancel.append({"doc_type": "In Yard Container Booking", "doc_name": booking.name})

		# Check Gate Pass
		gate_passes = frappe.db.get_all(
			"Gate Pass",
			filters={"container_id": container_id},
			fields=["name"]
		)

		if gate_passes:
			for gate_pass in gate_passes:
				docs_to_cancel.append({"doc_type": "Gate Pass", "doc_name": gate_pass.name})


		# Check Sales Orders and Sales Invoices using m_bl_no
		if self.m_bl_no:
			# Check Sales Invoices
			sales_invoices = frappe.db.get_all(
				"Sales Invoice",
				filters={"m_bl_no": self.m_bl_no, "docstatus": 0},
				fields=["name"]
			)

			if sales_invoices:
				for sales_invoice in sales_invoices:
					docs_to_cancel.append({"doc_type": "Sales Invoice", "doc_name": sales_invoice.name})

			# Check and delete draft Sales Orders
			# TODO: finding a better way to handle sales order linked with sales invoices
			# sales_orders = frappe.db.get_all(
			# 	"Sales Order",
			# 	filters={"m_bl_no": self.m_bl_no, "name": ["in", sales_order_ids]},
			# 	fields=["name"]
			# )

			# for sales_order in sales_orders:
			# 	docs_to_cancel.append({"doc_type": "Sales Order", "doc_name": sales_order.name})



		# If there are any error messages, throw them to prevent cancellation
		if error_messages:
			error_html = "<br>".join(error_messages)
			error_message = f"<div>Cannot cancel Container Reception due to the following linked documents with invoices:</div><br>{error_html}<br><br><div>Please cancel these documents manually before proceeding.</div>"
			frappe.throw(error_message)

		# Cancel the linked documents
		count = 0
		for record in docs_to_cancel:
			frappe.publish_progress(count * 100 / len(docs_to_cancel), title="Canceling linked documents...")
			doc = frappe.get_doc(record["doc_type"], record["doc_name"])
			doc.flags.ignore_permissions = True

			if doc.doctype != "Sales Order":
				doc.flags.ignore_links = True

			if doc.docstatus == 1:
				try:
					doc.cancel()
					doc.reload()
				except Exception as e:
					frappe.log_error(
						title=f"Error while canceling {doc.doctype} {doc.name}",
						message=str(e)
					)
					if doc.doctype == "Sales Order":
						doc.db_set("status", "Closed")
						continue
					else:
						raise e

			doc.delete()
			count += 1

		frappe.delete_doc(
			"Container",
			container_id,
			ignore_permissions=True
		)

	def update_cmo_status(self, status="Pending"):
		if not self.movement_order:
			return
		
		doc = frappe.get_cached_doc("Container Movement Order", self.movement_order)
		doc.status = status
		doc.save(ignore_permissions=True)

@frappe.whitelist()
def get_container_details(manifest, container_no):
	"""Get the details of a container based on the container no and manifest"""

	container = frappe.db.get_all(
		"Containers Detail",
		filters={"parent": manifest, "container_no": container_no},
		fields=["*"]
	)

	if len(container) > 0:
		container_row = container[0]
		abbr_for_destination = frappe.db.get_value(
			"Master BL",
			{"parent": manifest, "m_bl_no": container_row.m_bl_no},
			"place_of_destination"
		)
		container_row["abbr_for_destination"] = abbr_for_destination

		country_code = str(abbr_for_destination)[:2]
		country_of_destination = frappe.get_cached_value(
			"Country", {"code": country_code.lower()}, "name"
		)
		container_row["country_of_destination"] = country_of_destination

		place_of_destination = ""
		if country_code == "TZ":
			place_of_destination = "Local"
		elif country_code == "CD":
			place_of_destination = "DRC"
		else:
			place_of_destination = "Other"

		container_row["place_of_destination"] = place_of_destination

		return container_row
