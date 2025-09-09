# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_fullname, nowdate, nowtime, get_url_to_form, add_to_date, get_datetime
from icd_tz.icd_tz.api.utils import validate_cf_agent, validate_draft_doc


class GatePass(Document):
	def validate(self):
		validate_cf_agent(self)
	
	def before_submit(self):
		self.validate_pending_payments()
		self.validate_mandatory_fields()
		self.update_submitted_info()
	
	def on_submit(self):
		self.update_container_status()

	def before_cancel(self):
		self.update_container_status("At Gatepass")

	def validate_pending_payments(self):
		"""Validate the pending payments for the Gate Pass"""

		if self.is_empty_container == 1:
			return

		service_msg = ""
		service_msg += self.validate_container_charges()
		service_msg += self.validate_in_yard_booking()
		service_msg += self.validate_reception_charges()
		service_msg += self.validate_inspection_charges()
		
		if service_msg:
			msg = "<h4 class='text-center'>Pending Payments:</h4><hr>Payment is pending for the following services <ul> " + service_msg + " </ul>"

			frappe.throw(str(msg))

	def validate_container_charges(self):
		"""Validate the storage payments for the Gate Pass"""

		msg=""

		container_info = frappe.db.get_value(
			"Container",
			self.container_id,
			["has_removal_charges", "r_sales_invoice", "has_corridor_levy_charges", "c_sales_invoice", "days_to_be_billed"],
			as_dict=True
		)

		if container_info.days_to_be_billed > 0:
			msg += f"<li>Storage Charges:  <b>{container_info.days_to_be_billed} Days</b></li>"
		
		if container_info.has_removal_charges == "Yes" and not container_info.r_sales_invoice:
			msg += "<li>Removal Charges</li>"
		
		if container_info.has_corridor_levy_charges == "Yes" and not container_info.c_sales_invoice:
			msg += "<li>Corridor Levy Charges</li>"
		
		return msg
	
	def validate_in_yard_booking(self):
		"""Validate the In Yard Container Booking for the Gate Pass"""

		msg = ""

		booking_info = frappe.db.get_all(
			"In Yard Container Booking",
			{
				"container_id": self.container_id,
				"docstatus": ["!=", 2],  # Exclude cancelled bookings
			},
			["has_stripping_charges", "s_sales_invoice", "has_custom_verification_charges", "cv_sales_invoice"],
		)
		cargo_type = frappe.get_cached_value(
			"Container",
			self.container_id,
			"cargo_type"
		)
		
		if (
			len(booking_info) == 0 and
			cargo_type != "Transit" and # Transit containers are not required to have booking
			self.action_for_missing_booking == 'Stop'
		):
			frappe.throw(
				f"No Booking found for container: <b>{self.container_no}</b>, Cargo Type: <b>{cargo_type}</b><br>If you want to proceed, Please inform relevant person to Approve this Gate Pass"
			)

		for row in booking_info:
			if row.has_stripping_charges == "Yes" and not row.s_sales_invoice:
				msg += "<li>Stripping Charges</li>"
			
			if row.has_custom_verification_charges == "Yes" and not row.cv_sales_invoice:
				msg += "<li>Custom Verification Charges</li>"
				
		return msg
	
	def validate_reception_charges(self):
		"""Validate the Reception Charges for the Gate Pass"""

		msg = ""
		
		container_reception = frappe.db.get_value(
			"Container",
			self.container_id,
			"container_reception"
		)
		if not container_reception:
			return ""
		
		reception_info = frappe.db.get_value(
			"Container Reception",
			container_reception,
			["cargo_type", "has_transport_charges", "t_sales_invoice", "has_shore_handling_charges", "s_sales_invoice"],
			as_dict=True
		)

		if (
			reception_info.has_transport_charges == "Yes"
			and not reception_info.t_sales_invoice
			# Transport is not mandatory service for Transit container
			and reception_info.cargo_type != "Transit"
		):
			msg += "<li>Transport Charges</li>"
		
		if reception_info.has_shore_handling_charges == "Yes" and not reception_info.s_sales_invoice:
			msg += "<li>Shore Handling Charges</li>"

		return msg

	def validate_inspection_charges(self):
		"""Validate the Inspection Charges for the Gate Pass"""

		msg = ""

		inspection_info = frappe.db.get_all(
			"Container Inspection",
			{"container_id": self.container_id},
			pluck="name"
		)
		if len(inspection_info) == 0:
			return ""
		
		for inspection in inspection_info:
			inspection_doc = frappe.get_doc("Container Inspection", inspection)
			
			for d in inspection_doc.get("services"):
				if "off" in str(d.get("service")).lower() and not d.get("sales_invoice"):
					msg += f"<li>{d.get('service')}</li>"
				
				if "status" in str(d.get("service")).lower() and not d.get("sales_invoice"):
					msg += f"<li>{d.get('service')}</li>"
		
		return msg

	def update_container_status(self, status="Delivered"):
		if not self.container_id:
			return
		
		container_doc = frappe.get_cached_doc("Container", self.container_id)
		container_doc.status = status
		container_doc.save(ignore_permissions=True)
		container_doc.reload()

	def update_submitted_info(self):
		self.submitted_by = get_fullname(frappe.session.user)
		self.submitted_date = nowdate()
		self.submitted_time = nowtime()
		self.set_expiry_datetime()

	def set_expiry_datetime(self):
		"""Calculate and set expiry date/time based on ICD TZ Settings"""
		try:
			# Get expiry hours from ICD TZ Settings
			settings = frappe.get_single("ICD TZ Settings")
			expiry_hours = int(settings.expiry_hours or 72)  # Default to 72 hours if not set

			# Calculate expiry datetime from submission datetime
			submission_datetime = get_datetime(f"{self.submitted_date} {self.submitted_time}")
			expiry_datetime = add_to_date(submission_datetime, hours=expiry_hours)

			# Set expiry date and time
			self.expiry_date = expiry_datetime.date()
			self.expiry_time = expiry_datetime.time()

		except Exception as e:
			frappe.logger().error(f"Error setting expiry datetime for Gate Pass {self.name}: {str(e)}")
			# Set default expiry (72 hours from now) if there's an error
			default_expiry = add_to_date(get_datetime(f"{self.submitted_date} {self.submitted_time}"), hours=72)
			self.expiry_date = default_expiry.date()
			self.expiry_time = default_expiry.time()

	@frappe.whitelist()
	def gate_out_confirm(self):
		"""Confirm gate out by Gate Person with payment validation"""
		# Validate payments same as submission
		self.validate_pending_payments()

		# Update workflow state to 'Gate Out Confirmed'
		self.workflow_state = 'Gate Out Confirmed'
		self.save(ignore_permissions=True)

		frappe.msgprint("Gate Out confirmed successfully!", indicator="green")
		return True
	
	def validate_mandatory_fields(self):
		fields_str = ""
		fields = ["transporter", "truck", "trailer", "driver", "license_no"]
		for field in fields:
			if not self.get(field):
				fields_str += f"{self.meta.get_label(field)}, "
		
		if fields_str:
			frappe.throw(f"Please ensure the following fields are filled before submitting this document: <b>{fields_str}</b>")


@frappe.whitelist()
def create_getpass_for_empty_container(container_id):
	"""
	Create a Get pass document for an empty container
	"""

	exist_gate_pass = frappe.db.get_all(
		"Gate Pass", filters={"container_id": container_id}
	)

	if len(exist_gate_pass) > 0:
		url = get_url_to_form("Gate Pass", exist_gate_pass[0].name)
		frappe.throw(
			f"Gate Pass already exists for this Empty Container ID: <a href='{url}'>{exist_gate_pass[0].name}</a>"
		)
	
	getpass = frappe.new_doc("Gate Pass")
	getpass.update({
		"container_id": container_id,
		"is_empty_container": 1
	})
	getpass.save(ignore_permissions=True)
	getpass.reload()

	getpass.transporter = ""
	getpass.save()

	return True

