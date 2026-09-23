import frappe

from icd_tz.icd_tz.api.purchase_order import (
	get_expense_coverage,
	get_expense_items_by_type,
	get_wip_account,
	set_rows,
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

	expense_items = get_expense_items_by_type()
	for item in doc.items:
		if item.get("icd_container") and item.item_code in expense_items:
			item.expense_account = wip_account


def on_submit(doc, method):
	stamp_expense_invoice(doc, doc.name)


def on_cancel(doc, method):
	"""Take the invoice stamp back off, or a cancelled invoice stays recorded for ever"""

	stamp_expense_invoice(doc, "")


def stamp_expense_invoice(doc, invoice: str):
	"""Record the invoice on the containers and storage days its own lines bill

	Read from the invoice lines rather than from the orders they reference, so a
	part invoice does not stamp the whole order.
	"""

	one_off, storage_day_rows = get_expense_coverage(doc)

	containers = {container for container_ids in one_off.values() for container in container_ids}
	set_rows("ICD Container", containers, {"purchase_invoice": invoice})
	set_rows("ICD Container Storage Date", storage_day_rows, {"purchase_invoice": invoice})
