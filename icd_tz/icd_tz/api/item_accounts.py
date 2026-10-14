import frappe
from erpnext import get_company_currency
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.stock.doctype.item.item import get_item_defaults
from frappe import _
from frappe.query_builder.functions import Abs, Sum

from icd_tz.icd_tz.api.utils import get_icd_setting

# the Item Default table of each parent that holds container expense accounts
DEFAULT_TABLES = {"Item": "item_defaults", "Item Group": "item_group_defaults"}

# WIP holds the expense until the container is invoiced, then COGS takes it
ACCOUNT_ROOT_TYPES = {"wip_account": "Asset", "cogs_account": "Expense"}

# money accounts: posting container expenses here would distort cash, bank or party balances
EXCLUDED_ACCOUNT_TYPES = ("Receivable", "Payable", "Bank", "Cash")


def validate(doc, method=None):
	"""Check the WIP and COGS accounts of each company row of an Item or Item Group"""

	rows = doc.get(DEFAULT_TABLES[doc.doctype])
	saved_pairs = get_saved_pairs(doc)
	for row in rows:
		# a pair saved before was checked then, so an ordinary save runs no query
		if saved_pairs.get(row.company) == (row.wip_account, row.cogs_account):
			continue

		validate_account_pair(row)
		validate_wip_pairing(doc, row)

	validate_no_change_with_open_balance(saved_pairs, rows)


def get_saved_pairs(doc) -> dict:
	"""Company to the saved WIP and COGS Account pair, empty for a new document"""

	doc_before_save = doc.get_doc_before_save()
	if not doc_before_save:
		return {}

	return {
		row.company: (row.wip_account, row.cogs_account)
		for row in doc_before_save.get(DEFAULT_TABLES[doc.doctype])
	}


def validate_account_pair(row):
	"""Both accounts or neither, two different ledger accounts of the row company in its currency"""

	if not row.wip_account and not row.cogs_account:
		return

	if not row.wip_account or not row.cogs_account:
		frappe.throw(
			_("At Row#: {0}, set both the WIP Account and the COGS Account of {1}, or neither").format(
				row.idx, frappe.bold(row.company)
			),
			title=_("WIP and COGS Accounts"),
		)

	if row.wip_account == row.cogs_account:
		frappe.throw(
			_("At Row#: {0}, the WIP Account and the COGS Account must be different").format(row.idx),
			title=_("WIP and COGS Accounts"),
		)

	for field, root_type in ACCOUNT_ROOT_TYPES.items():
		validate_account(row, row.get(field), root_type)


def validate_account(row, account: str, root_type: str):
	details = frappe.get_cached_value(
		"Account",
		account,
		["company", "is_group", "root_type", "account_type", "account_currency"],
		as_dict=True,
	)
	if details.company != row.company:
		frappe.throw(
			_("At Row#: {0}, account {1} belongs to {2}, not {3}").format(
				row.idx, frappe.bold(account), frappe.bold(details.company), frappe.bold(row.company)
			),
			title=_("WIP and COGS Accounts"),
		)

	if details.is_group or details.root_type != root_type:
		frappe.throw(
			_("At Row#: {0}, account {1} must be a ledger {2} account").format(
				row.idx, frappe.bold(account), _(root_type)
			),
			title=_("WIP and COGS Accounts"),
		)

	if details.account_type in EXCLUDED_ACCOUNT_TYPES:
		frappe.throw(
			_("At Row#: {0}, account {1} is a {2} account and cannot hold container expenses").format(
				row.idx, frappe.bold(account), _(details.account_type)
			),
			title=_("WIP and COGS Accounts"),
		)

	# the balance moves in company currency, so another currency has no rate to move it back with
	company_currency = get_company_currency(row.company)
	if details.account_currency and details.account_currency != company_currency:
		frappe.throw(
			_("At Row#: {0}, account {1} must be in the company currency {2}").format(
				row.idx, frappe.bold(account), frappe.bold(company_currency)
			),
			title=_("WIP and COGS Accounts"),
		)


def validate_wip_pairing(doc, row):
	"""In a company, one WIP Account pairs with one COGS Account on every Item and Item Group"""

	if not row.wip_account:
		return

	item_default = frappe.qb.DocType("Item Default")
	other = (
		frappe.qb.from_(item_default)
		.select(item_default.parenttype, item_default.parent, item_default.cogs_account)
		.where(
			(item_default.parenttype.isin(list(DEFAULT_TABLES)))
			& (item_default.company == row.company)
			& (item_default.wip_account == row.wip_account)
			& (item_default.cogs_account != row.cogs_account)
			& ~((item_default.parenttype == doc.doctype) & (item_default.parent == doc.name))
		)
		.limit(1)
	).run(as_dict=True)
	if not other:
		return

	paired = other[0]
	frappe.throw(
		_("At Row#: {0}, WIP Account {1} is paired with COGS Account {2} on {3} {4}").format(
			row.idx,
			frappe.bold(row.wip_account),
			frappe.bold(paired.cogs_account),
			_(paired.parenttype),
			frappe.bold(paired.parent),
		),
		title=_("WIP Account Paired Already"),
	)


def validate_no_change_with_open_balance(saved_pairs: dict, rows):
	"""A WIP Account that still holds container expenses keeps its pair until they are released"""

	current = {row.company: (row.wip_account, row.cogs_account) for row in rows}
	for company, (wip_account, cogs_account) in saved_pairs.items():
		if not wip_account or current.get(company) == (wip_account, cogs_account):
			continue

		if has_open_container_balance(wip_account):
			frappe.throw(
				_(
					"The accounts of {0} cannot change, because WIP Account {1} still holds container expenses. Release them first."
				).format(frappe.bold(company), frappe.bold(wip_account)),
				title=_("WIP Account Has an Open Balance"),
			)


def has_open_container_balance(wip_account: str) -> bool:
	"""Whether any container still has a balance on the account, from submitted ledger entries"""

	gl_entry = frappe.qb.DocType("GL Entry")
	open_container = (
		frappe.qb.from_(gl_entry)
		.select(gl_entry.icd_container)
		.where(
			(gl_entry.account == wip_account) & (gl_entry.is_cancelled == 0) & (gl_entry.icd_container != "")
		)
		.groupby(gl_entry.icd_container)
		.having(Abs(Sum(gl_entry.debit) - Sum(gl_entry.credit)) > 0.005)
		.limit(1)
	).run()

	return bool(open_container)


def get_expense_accounts(item_code: str, company: str) -> dict:
	"""WIP and COGS Account of the item for the company, else of its Item Group, else empty"""

	for defaults in (get_item_defaults(item_code, company), get_item_group_defaults(item_code, company)):
		if defaults.get("wip_account"):
			return {"wip_account": defaults.wip_account, "cogs_account": defaults.cogs_account}

	return {}


def get_wip_cogs_map(company: str) -> dict:
	"""Each WIP Account of the company with the one COGS Account it pairs with

	A WIP Account that rows pair with two COGS Accounts, which only imported data can
	do, maps to None, so the release refuses it instead of picking one.
	"""

	rows = frappe.get_all(
		"Item Default",
		filters={
			"parenttype": ("in", list(DEFAULT_TABLES)),
			"company": company,
			"wip_account": ("is", "set"),
		},
		fields=["wip_account", "cogs_account"],
		distinct=True,
	)

	wip_cogs_map = {}
	for row in rows:
		paired = wip_cogs_map.get(row.wip_account, row.cogs_account)
		wip_cogs_map[row.wip_account] = row.cogs_account if paired == row.cogs_account else None

	return wip_cogs_map


def get_wip_accounts(item_codes, company: str) -> dict:
	"""WIP Account of each item, or None, while the company holds expenses in WIP"""

	if not get_icd_setting(company).enable_wip_and_cogs_for_expenses:
		return {}

	return {
		item_code: get_expense_accounts(item_code, company).get("wip_account") for item_code in item_codes
	}


def get_required_wip_accounts(item_codes, company: str) -> dict:
	"""WIP Account of each item while the company holds expenses in WIP, refusing an item without one"""

	wip_accounts = get_wip_accounts(item_codes, company)
	missing = sorted(item_code for item_code, wip_account in wip_accounts.items() if not wip_account)
	if missing:
		frappe.throw(
			_("Set the WIP and COGS Accounts of {0} for {1} on the Item or its Item Group").format(
				frappe.bold(", ".join(missing)), frappe.bold(company)
			),
			title=_("WIP Account Not Set"),
		)

	return wip_accounts
