import frappe
from frappe import _
from frappe.utils import cint

from icd_tz.icd_tz.api.expense_release import DIMENSIONS
from icd_tz.icd_tz.api.item_accounts import get_required_wip_accounts, get_wip_cogs_map
from icd_tz.icd_tz.api.purchase_order import get_expense_items_by_type
from icd_tz.icd_tz.api.transport_charges import get_transport_items


def before_validate(doc, method=None):
	"""Keep container expense orders and invoices apart from office expenses

	Runs before validate, so ERPNext checks the accounts this sets. The flag rules apply
	always, the account rules only while the company holds expenses in WIP.
	"""

	if doc.doctype == "Purchase Invoice":
		set_flag_from_orders(doc)

	if doc.is_icd_container_expense:
		validate_container_expense_lines(doc)

	# read raw, not with get_icd_setting, so an office expense of a company without one saves
	if not cint(
		frappe.db.get_value("ICD Setting", {"company": doc.company}, "enable_wip_and_cogs_for_expenses")
	):
		return

	if doc.is_icd_container_expense:
		set_item_wip_accounts(doc)
	else:
		validate_office_wip_lines(doc)


def get_container_expense_items(company: str) -> set:
	"""Port expense and transport items, the items a line with a container is a container expense for"""

	return {*get_expense_items_by_type(company), *get_transport_items(company)}


def set_flag_from_orders(doc):
	"""An invoice made from orders is a container expense when its orders are"""

	orders = {item.purchase_order for item in doc.items if item.get("purchase_order")}
	if not orders:
		return

	flags = set(
		frappe.get_all("Purchase Order", {"name": ("in", list(orders))}, pluck="is_icd_container_expense")
	)
	if len(flags) > 1:
		frappe.throw(
			_(
				"This invoice mixes container expense orders with other orders. Make one invoice for each kind."
			),
			title=_("Mixed Purchase Orders"),
		)

	doc.is_icd_container_expense = flags.pop()


def validate_container_expense_lines(doc):
	"""Every line of a container expense document is a container expense with all its dimensions"""

	expense_items = get_container_expense_items(doc.company)
	for item in doc.items:
		missing = get_missing_dimensions(item)
		if missing:
			frappe.throw(
				_("At Row#: {0}, a container expense line needs {1}").format(item.idx, ", ".join(missing)),
				title=_("Container Expense Line"),
			)

		if item.item_code not in expense_items:
			frappe.throw(
				_("At Row#: {0}, {1} is not a container expense. Put it on another {2}.").format(
					item.idx, frappe.bold(item.item_code), _(doc.doctype)
				),
				title=_("Container Expense Line"),
			)


def set_item_wip_accounts(doc):
	"""Each line takes the WIP Account of its item, over any account the user chose"""

	wip_accounts = get_required_wip_accounts({item.item_code for item in doc.items}, doc.company)
	for item in doc.items:
		item.expense_account = wip_accounts[item.item_code]


def validate_office_wip_lines(doc):
	"""An office expense keeps the account the user chose, but a WIP Account needs the dimensions"""

	# the release reads a WIP balance by its dimensions, so only lines missing one matter
	incomplete = [item for item in doc.items if get_missing_dimensions(item)]
	if not incomplete:
		return

	wip_accounts = set(get_wip_cogs_map(doc.company))
	for item in incomplete:
		if item.expense_account in wip_accounts:
			frappe.throw(
				_("At Row#: {0}, {1} is a WIP Account, so the line needs {2}").format(
					item.idx, frappe.bold(item.expense_account), ", ".join(get_missing_dimensions(item))
				),
				title=_("WIP Account Without a Container"),
			)


def get_missing_dimensions(item) -> list:
	meta = frappe.get_meta(item.doctype)

	return [_(meta.get_label(field)) for field in DIMENSIONS if not item.get(field)]
