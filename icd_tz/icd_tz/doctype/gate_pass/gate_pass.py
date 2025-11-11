# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.model.workflow import apply_workflow
from icd_tz.icd_tz.api.utils import validate_cf_agent, validate_draft_doc
from frappe.utils import (
    get_fullname,
	nowdate,
	nowtime,
	now_datetime,
	get_url_to_form,
	add_to_date,
	get_datetime,
)


class GatePass(Document):
	def validate(self):
		validate_cf_agent(self)
	
	def before_submit(self):
		self.validate_pending_payments()
		self.validate_mandatory_fields()
		self.update_submitted_info()
	
	def on_submit(self):
		self.update_container_status("At Gate Confirmation")

	def on_update_after_submit(self):
		self.validate_pending_payments()

		if self.workflow_state == "Gate Out Confirmed":
			self.update_container_status("Delivered")

	def on_cancel(self):
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

			if self.workflow_state in ["Approved", "Gate Out Confirmed"]:
				frappe.throw(str(msg))
			else:
				frappe.msgprint(str(msg))

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
		settings = frappe.get_single("ICD TZ Settings")
		if not settings.gate_pass_expiry_hours:
			return

		expiry_hours = settings.gate_pass_expiry_hours

		# Calculate expiry datetime from current datetime
		submission_datetime = get_datetime(f"{self.submitted_date} {self.submitted_time}")
		expiry_datetime = add_to_date(submission_datetime, hours=expiry_hours)

		# Set expiry date as datetime
		self.expiry_date = expiry_datetime
		
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


@frappe.whitelist()
def auto_expire_gate_passes():
	"""Auto-expire and cancel Gate Passes that have exceeded their expiry time"""

	current_datetime = now_datetime()

	# Find submitted gate passes that have expired and are not confirmed
	expired_gate_passes = frappe.get_all("Gate Pass",
		filters={
			"docstatus": 1,
			"workflow_state": ["!=", ["Gate Out Confirmed"]],
			"expiry_date": ["not in ", ["", None]],
			"expiry_date": ["<=", current_datetime]
		},
		fields=["name", "container_no", "expiry_date", "workflow_state"]
	)


	for gp in expired_gate_passes:
		if not gp.expiry_date:
			continue

		try:
			doc = frappe.get_doc("Gate Pass", gp.name)

			# Cancel the document
			if hasattr(doc, 'workflow_state'):
				apply_workflow(doc, 'Cancel')
			else:
				doc.cancel()
			
			doc.reload()

			# Add a comment after cancelling
			doc.add_comment(
				"Comment",
				f"Auto-cancelled due to expiry. Gate Pass expired on <b>{gp.expiry_date}</b>. Container was not moved out within the agreed time settled in ICD TZsettings."
			)
		except Exception as e:
			traceback = frappe.get_traceback()
			msg = f"Failed to auto-cancel Gate Pass {gp.name}: \n<br>{str(e)}\n\n<br>Traceback:\n<br>{traceback}"
			frappe.log_error(
				title=f"GatePass: <b>{gp.name}</b>Auto Expire Error",
				message=msg,
				reference_doctype="Gate Pass",
				reference_name=gp.name
			)
