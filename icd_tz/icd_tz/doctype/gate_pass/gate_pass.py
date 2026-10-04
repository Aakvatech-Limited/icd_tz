# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

from functools import cached_property

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

from icd_tz.icd_tz.api.edi.codeco import attach_gate_out
from icd_tz.icd_tz.api.icd_services import (
	BOOKING,
	CONTAINER,
	GATE_PASS_CANCELLATION,
	RECEPTION,
	SERVICE_FIELDS,
	get_scope_services,
)
from icd_tz.icd_tz.api.utils import validate_cf_agent, validate_no_draft_container_records


class GatePass(Document):
	def validate(self):
		validate_cf_agent(self)

	def before_submit(self):
		validate_no_draft_container_records(self.container_id, self.container_no)
		self.validate_pending_payments()
		self.validate_mandatory_fields()
		self.update_submitted_info()

		attach_gate_out(self)

	def on_submit(self):
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

		frappe.db.set_value("Container", self.container_id, GATE_PASS_CANCELLATION.flag_field, 1)

	def validate_pending_payments(self):
		"""Validate the pending payments for the Gate Pass"""

		charges = [self.validate_storage_charges()]
		if not self.is_empty_container:
			charges += [
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

	@cached_property
	def container_charges(self):
		"""Payment flags and invoices of the Container, read once for every charge validation"""

		return frappe.db.get_value(
			"Container",
			self.container_id,
			["cargo_type", "days_to_be_billed", *SERVICE_FIELDS],
			as_dict=True,
		)

	def validate_storage_charges(self):
		"""Validate the storage days for the Gate Pass and return their linked invoices"""

		msg = ""
		days_to_be_billed = self.container_charges.days_to_be_billed
		if days_to_be_billed > 0:
			msg = f"<li>Storage Charges:  <b>{days_to_be_billed} Days</b></li>"

		invoices = frappe.db.get_all(
			"Container Service Detail",
			filters={"parent": self.container_id, "parenttype": "Container"},
			pluck="sales_invoice",
		)

		return msg, invoices

	def validate_container_charges(self):
		"""Validate the removal, corridor levy and cancellation payments and return their linked invoices"""

		return self.get_pending_services(CONTAINER)

	def validate_in_yard_booking(self):
		"""Validate the stripping and custom verification payments and return their linked invoices"""

		has_booking = frappe.db.exists(
			"In Yard Container Booking",
			{"container_id": self.container_id, "docstatus": ["!=", 2]},
		)
		cargo_type = self.container_charges.cargo_type

		if (
			not has_booking
			and cargo_type != "Transit"  # Transit containers are not required to have booking
			and self.action_for_missing_booking == "Stop"
		):
			frappe.throw(
				f"No Booking found for container: <b>{self.container_no}</b>, Cargo Type: <b>{cargo_type}</b><br>If you want to proceed, Please inform relevant person to Approve this Gate Pass"
			)

		# TODO: compare booking count with billed qty, any invoice now passes every repeated booking
		return self.get_pending_services(BOOKING)

	def validate_reception_charges(self):
		"""Validate the transport, shore handling and ICD handling payments and return their linked invoices"""

		return self.get_pending_services(RECEPTION, self.container_charges.cargo_type)

	def get_pending_services(self, scope, cargo_type=None):
		"""Unpaid services of one scope as message rows, and the invoices already raised for them"""

		msg = ""
		invoices = []
		for service in get_scope_services(scope):
			if service.is_payment_pending(self.container_charges, cargo_type):
				msg += f"<li>{service.label} Charges</li>"

			invoices += service.get_invoices(self.container_charges)

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
