import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import get_link_to_form

from icd_tz.icd_tz.api.purchase_invoice import get_container_expense_items
from icd_tz.icd_tz.api.purchase_order import set_rows
from icd_tz.patches.create_custom_fields import load_json

FIELD_FILES = {
	"Purchase Order": "12_icd_on_purchase_order.json",
	"Purchase Invoice": "13_icd_on_purchase_invoice.json",
}


def execute():
	"""Flag the draft orders and invoices that carry only container expenses

	A draft that mixes container expenses with other lines is not flagged. It goes
	to the Error Log, so that finance can split it. Submitted documents do not change.
	after_migrate creates the custom fields only after the patches run, so they are created here.
	"""

	create_custom_fields({doctype: load_json(file) for doctype, file in FIELD_FILES.items()}, update=True)

	mixed = []
	for company in frappe.get_all("ICD Setting", pluck="company"):
		container_expense_items = get_container_expense_items(company)
		for doctype in FIELD_FILES:
			mixed += flag_drafts(doctype, company, container_expense_items)

	if mixed:
		frappe.log_error(
			title="Draft container expenses to split",
			message="These drafts mix container expenses with other expenses. Split them, so that "
			"the container expenses are on their own document:<br>" + "<br>".join(mixed),
		)
		print(f"Container expense flag: {len(mixed)} mixed draft(s) are listed in the Error Log")


def flag_drafts(doctype: str, company: str, container_expense_items: set) -> list:
	"""Flag the drafts of the company whose every line is a container expense

	Returns a link to each draft that has container expense lines beside other lines.
	"""

	parent = frappe.qb.DocType(doctype)
	item = frappe.qb.DocType(f"{doctype} Item")
	lines = (
		frappe.qb.from_(item)
		.inner_join(parent)
		.on(item.parent == parent.name)
		.select(item.parent, item.item_code, item.icd_container)
		.where((parent.docstatus == 0) & (parent.company == company))
	).run(as_dict=True)

	container_expenses, other_expenses = set(), set()
	for line in lines:
		if line.icd_container and line.item_code in container_expense_items:
			container_expenses.add(line.parent)
		else:
			other_expenses.add(line.parent)

	set_rows(doctype, container_expenses - other_expenses, {"is_icd_container_expense": 1})

	return [get_link_to_form(doctype, name) for name in sorted(container_expenses & other_expenses)]
