import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import Max
from pypika.terms import Tuple


def execute():
	"""Copy the income service flags and invoices to Container in a background job"""

	frappe.enqueue(
		"icd_tz.patches.move_income_refs_to_container.move_income_refs",
		queue="long",
		timeout=3600,
		job_id="move_income_refs_to_container",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def move_income_refs():
	move_reception_refs()
	move_booking_refs()
	frappe.db.commit()


def move_reception_refs():
	"""Transport and shore handling go to every Container of the reception, HBL containers included"""

	container = frappe.qb.DocType("Container")
	reception = frappe.qb.DocType("Container Reception")

	def from_reception(value):
		return as_subquery(
			frappe.qb.from_(reception).select(value).where(reception.name == container.container_reception)
		)

	(
		frappe.qb.update(container)
		.set(container.has_transport_charges, from_reception(is_yes(reception.has_transport_charges)))
		.set(container.t_sales_invoice, from_reception(reception.t_sales_invoice))
		.set(
			container.has_shore_handling_charges, from_reception(is_yes(reception.has_shore_handling_charges))
		)
		.set(container.sh_sales_invoice, from_reception(reception.s_sales_invoice))
		.where(container.container_reception.isin(frappe.qb.from_(reception).select(reception.name)))
	).run()


def move_booking_refs():
	"""A container with several bookings is charged if any booking is, and keeps the latest invoice"""

	container = frappe.qb.DocType("Container")
	booking = frappe.qb.DocType("In Yard Container Booking")
	active_bookings = frappe.qb.from_(booking).where(booking.docstatus != 2)

	def from_bookings(value):
		return as_subquery(active_bookings.select(Max(value)).where(booking.container_id == container.name))

	(
		frappe.qb.update(container)
		.set(container.has_stripping_charges, from_bookings(is_yes(booking.has_stripping_charges)))
		.set(container.st_sales_invoice, from_bookings(booking.s_sales_invoice))
		.set(
			container.has_custom_verification_charges,
			from_bookings(is_yes(booking.has_custom_verification_charges)),
		)
		.set(container.cv_sales_invoice, from_bookings(booking.cv_sales_invoice))
		.where(container.name.isin(active_bookings.select(booking.container_id)))
	).run()


def is_yes(column):
	return Case().when(column == "Yes", 1).else_(0)


def as_subquery(query):
	# pypika renders a SET value without parentheses, a one item Tuple adds them
	return Tuple(query)
