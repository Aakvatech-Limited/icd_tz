from dataclasses import dataclass

import frappe

from icd_tz.icd_tz.api.utils import (
	get_invoice_refs,
	get_service_item,
	get_service_items,
	throw_missing_criteria,
)

# Services charged at reception, once per booking, or once on the Container
RECEPTION = "Reception"
BOOKING = "Booking"
CONTAINER = "Container"


@dataclass(frozen=True)
class ContainerService:
	"""A service a Container is flagged for and invoiced on, through its own Container fields"""

	label: str
	service_type: str | None
	flag_field: str
	invoice_field: str
	scope: str
	settings_item_field: str | None = None
	on_service_order: bool = True
	show_criteria: bool = False
	exempt_cargo_type: str | None = None

	def get_items(self, settings_doc) -> list:
		"""Every item this service is charged on in ICD TZ Settings"""

		if self.settings_item_field:
			item_code = settings_doc.get(self.settings_item_field)
			return [item_code] if item_code else []

		return get_service_items(settings_doc, self.service_type)

	def get_invoices(self, container) -> list:
		return get_invoice_refs(container.get(self.invoice_field))

	def is_payment_pending(self, container, cargo_type: str | None = None) -> bool:
		"""Flagged and not invoiced, unless the Gate Pass lets this cargo type out without it"""

		if cargo_type and cargo_type == self.exempt_cargo_type:
			return False

		return bool(container.get(self.flag_field)) and not container.get(self.invoice_field)

	def find_item(self, settings_doc, key: dict, is_loose_cargo: bool) -> str:
		"""Item from the criteria row that best fits the container"""

		item_code = get_service_item(settings_doc, self.service_type, key, is_loose_cargo=is_loose_cargo)
		if not item_code:
			throw_missing_criteria(self.label, key)

		return item_code

	def get_order_item(self, container, settings_doc, key: dict, is_loose_cargo: bool) -> str | None:
		"""Item the Service Order adds for this service, or None when nothing is owed"""

		if not self.is_payment_pending(container):
			return None

		return self.find_item(settings_doc, key, is_loose_cargo)

	def get_unbilled_qty(self, container, settings_doc, booked_qty: float) -> float:
		"""Booked quantity of a repeated service, less what its invoices already billed"""

		if not container.get(self.flag_field):
			return 0

		return booked_qty - container.get_billed_qty(self.invoice_field, self.get_items(settings_doc))

	def set_invoice(self, container_id: str, doc):
		"""Write a submitted Sales Invoice to the Container, or drop it when doc is its return"""

		if self.scope == BOOKING:
			self.set_booking_invoice(container_id, doc)
			return

		invoice_id = None if doc.is_return else doc.name
		if self.scope == RECEPTION:
			frappe.db.set_value("Container", container_id, self.invoice_field, invoice_id)
		else:
			self.set_container_invoice(container_id, invoice_id)

	def set_booking_invoice(self, container_id: str, doc):
		"""Keep every invoice of a repeated booking service, a return drops the invoice it reverses"""

		invoices = get_invoice_refs(frappe.db.get_value("Container", container_id, self.invoice_field))

		# TODO: a partial return drops the whole invoice, so its unreturned qty is charged again
		if doc.is_return:
			invoices = [name for name in invoices if name != doc.return_against]
		elif doc.name not in invoices:
			invoices.append(doc.name)

		frappe.db.set_value("Container", container_id, self.invoice_field, ",".join(invoices) or None)

	def set_container_invoice(self, container_id: str, invoice_id: str | None):
		container_doc = frappe.get_doc("Container", container_id)
		container_doc.set(self.invoice_field, invoice_id)
		container_doc.status = "At Gatepass"
		container_doc.save(ignore_permissions=True)


TRANSPORT = ContainerService(
	"Transport",
	"Transport",
	"has_transport_charges",
	"t_sales_invoice",
	RECEPTION,
	exempt_cargo_type="Transit",
)
SHORE_HANDLING = ContainerService(
	"Shore Handling",
	"Shore",
	"has_shore_handling_charges",
	"sh_sales_invoice",
	RECEPTION,
	show_criteria=True,
)
ICD_HANDLING = ContainerService(
	"ICD Handling", "ICD Handling", "has_icd_handling_charge", "ih_sales_invoice", RECEPTION
)
STRIPPING = ContainerService("Stripping", "Stripping", "has_stripping_charges", "st_sales_invoice", BOOKING)
CUSTOM_VERIFICATION = ContainerService(
	"Custom Verification", "Verification", "has_custom_verification_charges", "cv_sales_invoice", BOOKING
)
REMOVAL = ContainerService(
	"Removal", "Removal", "has_removal_charges", "r_sales_invoice", CONTAINER, on_service_order=False
)
CORRIDOR_LEVY = ContainerService(
	"Corridor Levy", "Levy", "has_corridor_levy_charges", "c_sales_invoice", CONTAINER
)
GATE_PASS_CANCELLATION = ContainerService(
	"Gate Pass Cancellation",
	None,
	"has_cancellation_charge",
	"g_sales_invoice",
	CONTAINER,
	settings_item_field="gatepass_cancellation_item",
	on_service_order=False,
)

# Order matters: an item set on two services goes to the first, and Service Order lines follow it
SERVICES = (
	TRANSPORT,
	SHORE_HANDLING,
	ICD_HANDLING,
	STRIPPING,
	CUSTOM_VERIFICATION,
	REMOVAL,
	CORRIDOR_LEVY,
	GATE_PASS_CANCELLATION,
)

SERVICE_FIELDS = [field for service in SERVICES for field in (service.flag_field, service.invoice_field)]


def get_scope_services(scope: str) -> list:
	return [service for service in SERVICES if service.scope == scope]


def get_item_services(settings_doc) -> dict:
	"""Service each item is charged for, the first service wins an item set on two"""

	item_services = {}
	for service in SERVICES:
		for item_code in service.get_items(settings_doc):
			item_services.setdefault(item_code, service)

	return item_services
