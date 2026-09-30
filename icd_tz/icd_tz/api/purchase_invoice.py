import frappe
from frappe import _
from frappe.utils import flt

from icd_tz.icd_tz.api.port_expenses import ONE_OFF_BILLED_FIELDS
from icd_tz.icd_tz.api.purchase_order import (
	get_expense_coverage,
	get_expense_items_by_type,
	get_wip_account,
	set_rows,
	validate_not_already_claimed,
)
from icd_tz.icd_tz.api.transport_charges import (
	clear_transport_invoice,
	get_transport_charge_item,
	stamp_transport_invoice,
)


def set_wip_account(doc, method=None):
	"""Hold port expense lines on the work in progress account

	The mapper copies the account from the order the invoice was made from, but an
	invoice raised on its own has none, and an invoice can be edited after it is made.
	The expense is released to cost of goods sold when the container is invoiced, so a
	line that slipped onto another account would never be released.

	Only a configured port expense item on a container line is held: a container can be
	tagged on any purchase, and the rest of the invoice is ERPNext's to account for.
	Runs before validate so ERPNext still has its say on every other line.
	"""

	wip_account = get_wip_account(doc.company)
	if not wip_account:
		return

	held_items = {*get_expense_items_by_type(), get_transport_charge_item()}
	for item in doc.items:
		if item.get("icd_container") and item.item_code in held_items:
			item.expense_account = wip_account


def validate_no_zero_rate(doc, method=None):
	"""Every line of every purchase invoice must be priced before it is submitted"""

	unpriced = [str(item.idx) for item in doc.items if not flt(item.rate)]
	if unpriced:
		frappe.throw(
			_("Set a rate on row {0} before submitting").format(", ".join(unpriced)),
			title=_("Zero Rate"),
		)


def on_submit(doc, method):
	coverage = get_expense_coverage(doc)
	validate_not_already_claimed(coverage, doc.doctype)
	stamp_expense_invoice(coverage, doc.name)
	stamp_transport_invoice(doc)


def on_cancel(doc, method):
	"""Take the invoice back off, or a cancelled invoice stays recorded for ever"""

	stamp_expense_invoice(get_expense_coverage(doc), "")
	clear_transport_invoice(doc)


def stamp_expense_invoice(coverage: tuple, invoice: str):
	"""Record the invoice, and its billed flags, on the containers and storage days its own lines bill

	Read from the invoice lines rather than from the orders they reference, so a
	part invoice does not stamp the whole order. An empty invoice clears them.
	"""

	one_off, storage_day_rows = coverage
	billed = 1 if invoice else 0

	for expense_type, container_ids in one_off.items():
		set_rows(
			"ICD Container",
			container_ids,
			{ONE_OFF_BILLED_FIELDS[expense_type]: billed, "purchase_invoice": invoice},
		)

	set_rows("ICD Container Storage Date", storage_day_rows, {"purchase_invoice": invoice})
