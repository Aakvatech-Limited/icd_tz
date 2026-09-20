import frappe

from icd_tz.icd_tz.api.purchase_order import get_expense_coverage, set_rows


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
