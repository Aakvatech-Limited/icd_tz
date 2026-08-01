import frappe
from frappe.model.document import Document
from frappe.utils import get_fullname, get_url_to_form, nowdate, nowtime


class WaiverRequest(Document):
	def before_insert(self):
		self.posting_date = nowdate()
		self.posting_time = nowtime()
		self.requested_by = get_fullname(frappe.session.user)

	def validate(self):
		self.validate_sales_order()

	def validate_sales_order(self):
		sales_order = frappe.get_cached_doc("Sales Order", self.sales_order)
		if sales_order.docstatus != 0:
			frappe.throw(
				f"Sales Order <b>{self.sales_order}</b> is not a draft, a waiver cannot be requested on it"
			)

		if self.is_new() and sales_order.waiver_status == "Pending":
			frappe.throw(f"A Waiver Request is already pending for Sales Order <b>{self.sales_order}</b>")

	def after_insert(self):
		frappe.db.set_value("Sales Order", self.sales_order, "waiver_status", "Pending")

		url = get_url_to_form("Waiver Request", self.name)
		sales_order = frappe.get_doc("Sales Order", self.sales_order)
		sales_order.add_comment(
			comment_type="Comment",
			text=f"Waiver Request <a href='{url}'><b>{self.name}</b></a> was created and is pending approval.",
		)

	def before_submit(self):
		if not self.decision:
			frappe.throw("Please set a Decision (Approved or Rejected) before submitting this Waiver Request")

		if (
			self.decision == "Approved"
			and not self.additional_discount_percentage
			and not self.discount_amount
		):
			frappe.throw("Please set a Discount (%) or Discount Amount before approving this Waiver Request")

		self.decided_by = get_fullname(frappe.session.user)

	def on_submit(self):
		if self.decision == "Approved":
			self.apply_waiver_discount()
		else:
			self.reject_waiver()

	def apply_waiver_discount(self):
		sales_order = frappe.get_doc("Sales Order", self.sales_order)
		sales_order.apply_discount_on = self.apply_discount_on
		sales_order.additional_discount_percentage = self.additional_discount_percentage or 0
		sales_order.discount_amount = self.discount_amount or 0
		sales_order.waiver_status = "Approved"
		sales_order.save(ignore_permissions=True)

		url = get_url_to_form("Waiver Request", self.name)
		sales_order.add_comment(
			comment_type="Comment",
			text=f"Waiver Request <a href='{url}'><b>{self.name}</b></a> was approved. Discount applied on this Sales Order.",
		)

	def reject_waiver(self):
		frappe.db.set_value("Sales Order", self.sales_order, "waiver_status", "Rejected")

		url = get_url_to_form("Waiver Request", self.name)
		sales_order = frappe.get_doc("Sales Order", self.sales_order)
		sales_order.add_comment(
			comment_type="Comment",
			text=f"Waiver Request <a href='{url}'><b>{self.name}</b></a> was rejected.",
		)


@frappe.whitelist()
def create_waiver_request(
	sales_order, apply_discount_on, waiver_reason, additional_discount_percentage=0, discount_amount=0
):
	waiver_request = frappe.new_doc("Waiver Request")
	waiver_request.sales_order = sales_order
	waiver_request.apply_discount_on = apply_discount_on
	waiver_request.additional_discount_percentage = additional_discount_percentage
	waiver_request.discount_amount = discount_amount
	waiver_request.waiver_reason = waiver_reason
	waiver_request.insert()
	return waiver_request.name
