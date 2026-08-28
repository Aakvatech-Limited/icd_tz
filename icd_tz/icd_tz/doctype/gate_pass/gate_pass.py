# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.model.workflow import apply_workflow
from frappe.utils import (
	add_to_date,
	get_datetime,
	get_fullname,
	get_url_to_form,
	getdate,
	now_datetime,
	nowdate,
	nowtime,
)

from icd_tz.icd_tz.api.edi_codeco import generate_codeco_gate_out
from icd_tz.icd_tz.api.utils import validate_cf_agent, validate_draft_doc


class GatePass(Document):
	def validate(self):
		validate_cf_agent(self)

	def before_submit(self):
		self.validate_pending_payments()
		self.validate_mandatory_fields()
		self.update_submitted_info()

		edi_settings = frappe.get_single("EDI Settings")
		if edi_settings.enable_edi and edi_settings.connection_type == "SMTP":
			self.receiver_email = edi_settings.receiver_email
			self.receiver_cc_email = edi_settings.receiver_cc_email

		try:
			edi_data = generate_codeco_gate_out(self.name, file_type="txt")
			if edi_data and edi_data.get("edi_content"):
				file_doc = frappe.get_doc(
					{
						"doctype": "File",
						"file_name": edi_data.get("filename"),
						"content": edi_data.get("edi_content"),
						"attached_to_doctype": self.doctype,
						"attached_to_name": self.name,
						"is_private": 1,
					}
				)
				file_doc.insert(ignore_permissions=True)
				self.edi_file = file_doc.file_url
		except Exception as e:
			traceback = frappe.get_traceback()
			msg = f"Failed to generate Gate Out EDI: {e!s}\n\nTraceback: {traceback}"
			frappe.log_error(
				title="Failed to generate Gate Out EDI",
				message=msg,
				reference=self.name,
				reference_doctype=self.doctype,
			)

	def on_submit(self):
		edi_settings = frappe.get_single("EDI Settings")
		if edi_settings.enable_edi and not self.edi_file:
			frappe.throw("EDI File is missing. Cannot submit when EDI is enabled.")

		self.update_container_status("At Gate Confirmation")

	def on_update_after_submit(self):
		self.validate_pending_payments()

		if self.get("workflow_state") == "Gate Out Confirmed":
			self.set_gate_out_date()
			self.update_container_status("Delivered")

	def on_cancel(self):
		self.update_container_status("At Gatepass")
		self.flag_gatepass_cancellation_charge()

	def flag_gatepass_cancellation_charge(self):
		"""Mark the container as chargeable once its Gate Pass is cancelled."""

		if not self.container_id:
			return

		frappe.db.set_value("Container", self.container_id, "has_cancellation_charge", 1)

	def validate_pending_payments(self):
		"""Validate the pending payments for the Gate Pass"""

		if self.is_empty_container == 1:
			return

		charges = [
			self.validate_container_charges(),
			self.validate_in_yard_booking(),
			self.validate_reception_charges(),
			self.validate_inspection_charges(),
		]

		service_msg = ""
		invoices = []
		for charge_msg, charge_invoices in charges:
			service_msg += charge_msg
			invoices += charge_invoices

		msg = ""
		if service_msg:
			msg += (
				"<h4 class='text-center'>Pending Payments:</h4><hr>Payment is pending for the following services <ul> "
				+ service_msg
				+ " </ul>"
			)

		msg += self.get_unpaid_invoices_message(invoices)

		if not msg:
			return

		if self.meta.has_field("workflow_state"):
			if self.get("workflow_state") in ["Approved", "Gate Out Confirmed"]:
				frappe.throw(str(msg))
			else:
				frappe.msgprint(str(msg))
		else:
			frappe.throw(str(msg))

	def get_unpaid_invoices_message(self, invoices):
		"""Message section for the collected Sales Invoices that are not in Paid status"""

		unpaid_msg = ""
		invoices = set(invoices)

		for invoice_id in invoices:
			if not invoice_id:
				continue

			status = frappe.db.get_value("Sales Invoice", invoice_id, "status")
			if status == "Paid":
				continue

			url = get_url_to_form("Sales Invoice", invoice_id)
			unpaid_msg += f"<li><a href='{url}'><b>{invoice_id}</b></a>: {status or 'Not Found'}</li>"

		if not unpaid_msg:
			return ""

		return (
			"<h4 class='text-center'>Unpaid Invoices:</h4><hr>The following invoices are not paid yet, "
			"they must have <b>Paid</b> status, Inform Finance Department to look into this <ul> "
			+ unpaid_msg
			+ " </ul>"
		)

	def validate_container_charges(self):
		"""Validate the storage payments for the Gate Pass and return its linked invoices"""

		msg = ""
		invoices = []

		container_info = frappe.db.get_value(
			"Container",
			self.container_id,
			[
				"has_removal_charges",
				"r_sales_invoice",
				"has_corridor_levy_charges",
				"c_sales_invoice",
				"has_cancellation_charge",
				"g_sales_invoice",
				"days_to_be_billed",
			],
			as_dict=True,
		)

		if container_info.days_to_be_billed > 0:
			msg += f"<li>Storage Charges:  <b>{container_info.days_to_be_billed} Days</b></li>"

		if container_info.has_removal_charges == "Yes" and not container_info.r_sales_invoice:
			msg += "<li>Removal Charges</li>"

		if container_info.has_corridor_levy_charges == "Yes" and not container_info.c_sales_invoice:
			msg += "<li>Corridor Levy Charges</li>"

		if container_info.has_cancellation_charge == 1 and not container_info.g_sales_invoice:
			msg += "<li>Gate Pass Cancellation Charges</li>"

		invoices.append(container_info.r_sales_invoice)
		invoices.append(container_info.c_sales_invoice)
		invoices.append(container_info.g_sales_invoice)
		invoices.extend(
			frappe.db.get_all(
				"Container Service Detail",
				filters={"parent": self.container_id, "parenttype": "Container"},
				pluck="sales_invoice",
			)
		)

		return msg, invoices

	def validate_in_yard_booking(self):
		"""Validate the In Yard Container Booking for the Gate Pass and return its linked invoices"""

		msg = ""
		invoices = []

		booking_info = frappe.db.get_all(
			"In Yard Container Booking",
			{
				"container_id": self.container_id,
				"docstatus": ["!=", 2],  # Exclude cancelled bookings
			},
			[
				"has_stripping_charges",
				"s_sales_invoice",
				"has_custom_verification_charges",
				"cv_sales_invoice",
			],
		)
		cargo_type = frappe.get_cached_value("Container", self.container_id, "cargo_type")

		if (
			len(booking_info) == 0
			and cargo_type != "Transit"  # Transit containers are not required to have booking
			and self.action_for_missing_booking == "Stop"
		):
			frappe.throw(
				f"No Booking found for container: <b>{self.container_no}</b>, Cargo Type: <b>{cargo_type}</b><br>If you want to proceed, Please inform relevant person to Approve this Gate Pass"
			)

		for row in booking_info:
			if row.has_stripping_charges == "Yes" and not row.s_sales_invoice:
				msg += "<li>Stripping Charges</li>"

			if row.has_custom_verification_charges == "Yes" and not row.cv_sales_invoice:
				msg += "<li>Custom Verification Charges</li>"

			invoices.append(row.s_sales_invoice)
			invoices.append(row.cv_sales_invoice)

		return msg, invoices

	def validate_reception_charges(self):
		"""Validate the Reception Charges for the Gate Pass and return its linked invoices"""

		msg = ""
		invoices = []

		container_reception = frappe.db.get_value("Container", self.container_id, "container_reception")
		if not container_reception:
			return "", []

		reception_info = frappe.db.get_value(
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

		if (
			reception_info.has_transport_charges == "Yes"
			and not reception_info.t_sales_invoice
			# Transport is not mandatory service for Transit container
			and reception_info.cargo_type != "Transit"
		):
			msg += "<li>Transport Charges</li>"

		if reception_info.has_shore_handling_charges == "Yes" and not reception_info.s_sales_invoice:
			msg += "<li>Shore Handling Charges</li>"

		invoices.append(reception_info.t_sales_invoice)
		invoices.append(reception_info.s_sales_invoice)

		return msg, invoices

	def validate_inspection_charges(self):
		"""Validate the Inspection Charges for the Gate Pass and return its linked invoices"""

		msg = ""
		invoices = []

		inspection_info = frappe.db.get_all(
			"Container Inspection", {"container_id": self.container_id}, pluck="name"
		)
		if len(inspection_info) == 0:
			return "", []

		for inspection in inspection_info:
			inspection_doc = frappe.get_doc("Container Inspection", inspection)

			for d in inspection_doc.get("services"):
				service = str(d.get("service")).lower()
				if ("off" in service or "status" in service) and not d.get("sales_invoice"):
					msg += f"<li>{d.get('service')}</li>"

				invoices.append(d.get("sales_invoice"))

		return msg, invoices

	def update_container_status(self, status="Delivered"):
		if not self.container_id:
			return

		container_doc = frappe.get_doc("Container", self.container_id)
		container_doc.status = status
		container_doc.save(ignore_permissions=True)
		container_doc.reload()

	def set_gate_out_date(self):
		"""Stamp the gate out datetime once the workflow is confirmed."""

		if self.gate_out_date:
			return

		gate_out_datetime = now_datetime()
		self.db_set("gate_out_date", gate_out_datetime)

		if self.container_id:
			frappe.db.set_value("Container", self.container_id, "gate_out_date", getdate(gate_out_datetime))

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
			frappe.throw(
				f"Please ensure the following fields are filled before submitting this document: <b>{fields_str}</b>"
			)


@frappe.whitelist()
def create_getpass_for_empty_container(container_id):
	"""
	Create a Get pass document for an empty container
	"""

	exist_gate_pass = frappe.db.get_all("Gate Pass", filters={"container_id": container_id})

	if len(exist_gate_pass) > 0:
		url = get_url_to_form("Gate Pass", exist_gate_pass[0].name)
		frappe.throw(
			f"Gate Pass already exists for this Empty Container ID: <a href='{url}'>{exist_gate_pass[0].name}</a>"
		)

	getpass = frappe.new_doc("Gate Pass")
	getpass.update({"container_id": container_id, "is_empty_container": 1})
	getpass.save(ignore_permissions=True)
	getpass.reload()

	getpass.transporter = ""
	getpass.save()

	return True


@frappe.whitelist()
def auto_expire_gate_passes():
	"""Auto-expire and cancel Gate Passes that have exceeded their expiry time"""

	current_datetime = now_datetime()
	has_workflow_state = frappe.get_meta("Gate Pass").has_field("workflow_state")

	filters = [
		["docstatus", "=", 1],
		["expiry_date", "not in", ["", None]],
		["expiry_date", "<=", current_datetime],
	]
	fields = ["name", "container_no", "expiry_date"]

	if has_workflow_state:
		filters.append(["workflow_state", "!=", "Gate Out Confirmed"])
		fields.append("workflow_state")

	# Find submitted gate passes that have expired and are not confirmed
	expired_gate_passes = frappe.get_all("Gate Pass", filters=filters, fields=fields)

	for gp in expired_gate_passes:
		if not gp.expiry_date:
			continue

		try:
			doc = frappe.get_doc("Gate Pass", gp.name)
			doc.flags.ignore_links = True

			# Cancel the document
			if has_workflow_state:
				apply_workflow(doc, "Cancel")
			else:
				doc.cancel()

			doc.reload()

			# Add a comment after cancelling
			doc.add_comment(
				"Comment",
				f"Auto-cancelled due to expiry. Gate Pass expired on <b>{gp.expiry_date}</b>. Container was not moved out within the agreed time settled in ICD TZsettings.",
			)
		except Exception as e:
			traceback = frappe.get_traceback()
			msg = f"Failed to auto-cancel Gate Pass {gp.name}: \n<br>{e!s}\n\n<br>Traceback:\n<br>{traceback}"
			frappe.log_error(
				title=f"GatePass: <b>{gp.name}</b>Auto Expire Error",
				message=msg,
				reference_doctype="Gate Pass",
				reference_name=gp.name,
			)
