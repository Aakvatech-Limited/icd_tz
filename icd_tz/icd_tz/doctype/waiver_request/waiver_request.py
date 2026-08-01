import frappe
from frappe.model.document import Document
from frappe.utils import flt, get_fullname, get_url_to_form, nowdate, nowtime


class WaiverRequest(Document):
	def before_insert(self):
		self.posting_date = nowdate()
		self.posting_time = nowtime()
		self.requested_by = get_fullname(frappe.session.user)

	def validate(self):
		self.validate_sales_order()
		self.set_item_totals()

	def validate_sales_order(self):
		sales_order = frappe.get_cached_doc("Sales Order", self.sales_order)
		if sales_order.docstatus != 0:
			frappe.throw(
				f"Sales Order <b>{self.sales_order}</b> is not a draft, a waiver cannot be requested on it"
			)

		if self.is_new() and sales_order.waiver_status == "Pending":
			frappe.throw(f"A Waiver Request is already pending for Sales Order <b>{self.sales_order}</b>")

	def on_trash(self):
		frappe.db.set_value("Sales Order", self.sales_order, "waiver_status", "")

	def set_item_totals(self):
		if self.apply_discount_on != "Single Item":
			return

		self.total_actual_amount = 0
		self.total_discounted_amount = 0
		self.total_amount_after_discount = 0
		for item in self.items:
			self.total_actual_amount += flt(item.actual_price)
			self.total_discounted_amount += flt(item.discount_amount)
			self.total_amount_after_discount += flt(item.amount_after_discount)

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

		if self.decision == "Approved":
			self.validate_approval()

		self.decided_by = get_fullname(frappe.session.user)

	def validate_approval(self):
		if not self.additional_discount_percentage and not self.discount_amount:
			frappe.throw("Please set a Discount (%) or Discount Amount before approving this Waiver Request")

		if self.apply_discount_on == "Single Item" and not self.items:
			frappe.throw("Please add at least one Item before approving this Waiver Request")

	def on_submit(self):
		if self.decision == "Approved":
			self.apply_waiver_discount()
		else:
			self.reject_waiver()

	def apply_waiver_discount(self):
		sales_order = frappe.get_doc("Sales Order", self.sales_order)

		if self.apply_discount_on == "Single Item":
			self.apply_item_discount(sales_order)
		else:
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

	def apply_item_discount(self, sales_order):
		for waiver_item in self.items:
			for row in sales_order.items:
				if row.name != waiver_item.so_detail:
					continue

				row.discount_amount = waiver_item.discount_amount
				row.rate = waiver_item.amount_after_discount
				if self.discount_criteria == "Waiver Based on Percentage":
					row.discount_percentage = self.additional_discount_percentage
				break

	def reject_waiver(self):
		frappe.db.set_value("Sales Order", self.sales_order, "waiver_status", "Rejected")

		url = get_url_to_form("Waiver Request", self.name)
		sales_order = frappe.get_doc("Sales Order", self.sales_order)
		sales_order.add_comment(
			comment_type="Comment",
			text=f"Waiver Request <a href='{url}'><b>{self.name}</b></a> was rejected.",
		)


@frappe.whitelist()
def get_items(sales_order):
	sales_order_doc = frappe.get_cached_doc("Sales Order", sales_order)
	return [
		{
			"item_code": item.item_code,
			"item_name": item.item_name,
			"actual_price": item.amount,
			"so_detail": item.name,
		}
		for item in sales_order_doc.items
	]


@frappe.whitelist()
def get_item_details(sales_order, item_code):
	sales_order_doc = frappe.get_cached_doc("Sales Order", sales_order)
	return [
		{
			"item_code": item.item_code,
			"item_name": item.item_name,
			"actual_price": item.amount,
			"so_detail": item.name,
		}
		for item in sales_order_doc.items
		if item.item_code == item_code
	]


@frappe.whitelist()
def create_waiver_request(
	sales_order,
	apply_discount_on,
	discount_criteria,
	waiver_reason,
	additional_discount_percentage=0,
	discount_amount=0,
	items=None,
):
	waiver_request = frappe.new_doc("Waiver Request")
	waiver_request.sales_order = sales_order
	waiver_request.apply_discount_on = apply_discount_on
	waiver_request.discount_criteria = discount_criteria
	waiver_request.additional_discount_percentage = additional_discount_percentage
	waiver_request.discount_amount = discount_amount
	waiver_request.waiver_reason = waiver_reason

	if items:
		for item in frappe.parse_json(items):
			waiver_request.append(
				"items",
				{
					"item_code": item.get("item_code"),
					"item_name": item.get("item_name"),
					"actual_price": item.get("actual_price"),
					"discount_amount": item.get("discount_amount"),
					"amount_after_discount": item.get("amount_after_discount"),
					"so_detail": item.get("so_detail"),
				},
			)

	waiver_request.insert()
	return waiver_request.name
