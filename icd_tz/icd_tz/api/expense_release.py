"""Move port expenses from work in progress to cost of goods sold once a container is billed."""

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import flt, nowdate

RELEASE_REMARK = "Port expenses released from WIP to COGS for Sales Invoice {0}"

# what the expenses were booked against, and what the release is booked back against
DIMENSIONS = ("icd_container", "icd_master_bl", "manifest")


def on_submit(doc, method):
	enqueue_release(doc.name, "release_expenses")


def on_cancel(doc, method):
	enqueue_release(doc.name, "reverse_release")


def before_journal_entry_cancel(doc, method):
	"""A release cannot be taken back while the invoice that caused it still stands

	The invoice is what recognised the revenue, so cancelling only the release would
	leave that revenue with no cost against it, which is the mismatch this exists to
	prevent. Cancelling the invoice reverses the release, in that order.
	"""

	if not doc.get("icd_sales_invoice"):
		return

	if frappe.db.get_value("Sales Invoice", doc.icd_sales_invoice, "docstatus") != 1:
		return

	frappe.throw(
		frappe._(
			"{0} released port expenses for Sales Invoice {1}, which is still submitted. "
			"Cancel the invoice instead, and this entry is reversed with it."
		).format(frappe.bold(doc.name), frappe.bold(doc.icd_sales_invoice)),
		title=frappe._("Release Still Has An Invoice"),
	)


def on_journal_entry_cancel(doc, method):
	"""Take a cancelled release off the containers it named

	The one place the list is maintained, whether the release was reversed with its
	invoice or cancelled by hand once that invoice had already gone.
	"""

	if not doc.get("icd_sales_invoice"):
		return

	for container in get_containers_of_entry(doc.name):
		unmark_released(container, doc.name)


def enqueue_release(sales_invoice: str, method: str):
	"""One invoice can carry every container of an M BL, so the work leaves the request

	After commit, or the worker could read the invoice before the submit it was queued
	by has landed. The job id names the method as well as the invoice, so a cancel is
	never dropped as a duplicate of the release it undoes.
	"""

	frappe.enqueue(
		f"icd_tz.icd_tz.api.expense_release.{method}",
		queue="long",
		timeout=1800,
		enqueue_after_commit=True,
		sales_invoice=sales_invoice,
		job_id=f"icd-{method.replace('_', '-')}-{sales_invoice}",
		deduplicate=True,
	)


def release_expenses(sales_invoice: str):
	"""Post one journal entry moving what this invoice's containers still hold in WIP

	What moves is the ledger balance, not what the purchase invoices once said, so a
	second run finds nothing left and posts nothing, and an expense booked after an
	earlier release is still picked up by the next invoice.
	"""

	invoice = frappe.get_doc("Sales Invoice", sales_invoice)
	if invoice.docstatus != 1 or invoice.is_return:
		return

	accounts = get_release_accounts(invoice.company, invoice.name)
	if not accounts:
		return

	try:
		balances = get_balances_to_release(sales_invoice, accounts["wip_account"])
		if not balances:
			return

		entry = post_release_entry(invoice, balances, accounts)
		for dimensions, _balance in balances:
			mark_released(dimensions["icd_container"], entry)

	except Exception:
		frappe.log_error(title=f"Releasing port expenses of {sales_invoice}", message=frappe.get_traceback())
		raise


def reverse_release(sales_invoice: str):
	"""Put the expenses back in WIP, so a cancelled invoice leaves no cost without revenue

	Only the entries this invoice posted are cancelled. A container can be released by
	one invoice and billed again by another, and that first entry is not this one's to
	take back.
	"""

	entries = frappe.get_all(
		"Journal Entry",
		filters={"icd_sales_invoice": sales_invoice, "docstatus": 1},
		pluck="name",
	)
	if not entries:
		return

	try:
		for entry in entries:
			for container in sorted(get_containers_of_entry(entry)):
				frappe.db.get_value("ICD Container", container, "name", for_update=True)

			cancel_release_entry(entry)

	except Exception:
		frappe.log_error(
			title=f"Reversing the port expense release of {sales_invoice}", message=frappe.get_traceback()
		)
		raise


def get_release_accounts(company: str, sales_invoice: str | None = None) -> dict:
	"""The two accounts an expense moves between, or nothing while they cannot be used

	Anything that stops a release is written to the error log rather than passed over,
	so a setting that quietly holds expenses in WIP can be found and corrected.
	"""

	settings_doc = frappe.get_cached_doc("ICD TZ Settings")
	if not settings_doc.enable_wip_for_expenses:
		return {}

	accounts = {"wip_account": settings_doc.wip_account, "cogs_account": settings_doc.cogs_account}
	if not all(accounts.values()):
		return log_release_blocked(
			company, sales_invoice, "WIP Account and COGS Account must both be set in ICD TZ Settings"
		)

	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	for account in accounts.values():
		details = frappe.get_cached_value("Account", account, ["company", "account_currency"], as_dict=True)
		if details.company != company:
			return log_release_blocked(company, sales_invoice, f"{account} belongs to {details.company}")

		# the balance is read in company currency, and a journal entry derives that from
		# the account currency, so another currency needs a rate this cannot invent
		if details.account_currency and details.account_currency != company_currency:
			return log_release_blocked(
				company,
				sales_invoice,
				f"{account} is in {details.account_currency}, not {company_currency}",
			)

	return accounts


def log_release_blocked(company: str, sales_invoice: str | None, reason: str) -> dict:
	"""Record why expenses are staying in WIP, and release nothing

	The invoice is named so the log can be traced back to what was being billed.
	"""

	frappe.log_error(
		title=f"Port expenses cannot be released for {company}",
		message=(
			f"Sales Invoice: {sales_invoice or 'not raised from an invoice'}\n"
			f"{reason}.\nPort expenses will stay in WIP until ICD TZ Settings is corrected."
		),
		reference_doctype="Sales Invoice" if sales_invoice else None,
		reference_name=sales_invoice,
	)

	return {}


def get_balances_to_release(sales_invoice: str, wip_account: str) -> list:
	"""What each container of this invoice still holds in WIP, locked while it is read

	The row is locked in a settled order, so two invoices billing the same container at
	the same time queue behind one another instead of both posting the same balance.
	"""

	balances = []
	for dimensions in get_invoice_dimensions(sales_invoice):
		frappe.db.get_value("ICD Container", dimensions["icd_container"], "name", for_update=True)
		balance = get_wip_balance(dimensions, wip_account)
		if balance > 0:
			balances.append((dimensions, balance))

	return balances


def get_invoice_dimensions(sales_invoice: str) -> list:
	"""The dimensions an invoice bills, read from its own lines

	The lines carry all three, so they say what the release is booked against without
	resolving anything a second time.
	"""

	rows = frappe.get_all(
		"Sales Invoice Item",
		filters={"parent": sales_invoice, "icd_container": ("is", "set")},
		fields=list(DIMENSIONS),
	)

	# one entry per container: a line that names only the container would otherwise
	# come back beside a fuller one and its balance would be released twice
	dimensions = {}
	for row in rows:
		held = dimensions.setdefault(row.icd_container, {field: None for field in DIMENSIONS})
		for field in DIMENSIONS:
			held[field] = held[field] or row.get(field)

	return [dimensions[container] for container in sorted(dimensions)]


def get_wip_balance(dimensions: dict, wip_account: str) -> float:
	"""What a container still holds in work in progress, read from the ledger

	debit and credit are the company currency amounts. The account currency pair only
	matches them while the account is in the company currency, and the transaction
	currency pair is whatever each document was raised in, so neither can be added up
	across documents. An expense bought in one currency and billed in another still
	totals correctly here.
	"""

	gl_entry = frappe.qb.DocType("GL Entry")
	query = (
		frappe.qb.from_(gl_entry)
		.select(Sum(gl_entry.debit - gl_entry.credit))
		.where((gl_entry.account == wip_account) & (gl_entry.is_cancelled == 0))
		.for_update()
	)
	for field, value in dimensions.items():
		if not value:
			continue

		# a ledger row that leaves a dimension blank still belongs to the container it
		# does name, so it is released rather than left behind
		query = query.where(gl_entry[field].isnull() | (gl_entry[field] == value))

	balance = query.run()

	return flt(balance[0][0]) if balance else 0.0


def post_release_entry(invoice, balances: list, accounts: dict) -> str:
	"""One journal entry for the invoice, a debit and a credit per container it releases"""

	company_currency = frappe.get_cached_value("Company", invoice.company, "default_currency")

	journal_entry = frappe.new_doc("Journal Entry")
	journal_entry.update(
		{
			"voucher_type": "Journal Entry",
			"company": invoice.company,
			"posting_date": invoice.posting_date,
			"icd_sales_invoice": invoice.name,
			"user_remark": RELEASE_REMARK.format(invoice.name),
			"multi_currency": 0,
		}
	)

	# the balance came out of the ledger in company currency, and both accounts are held
	# to that currency, so the entry is posted at a rate of one and converts nothing
	posting = {"account_currency": company_currency, "exchange_rate": 1}

	for dimensions, balance in balances:
		journal_entry.append(
			"accounts",
			{
				"account": accounts["cogs_account"],
				"debit_in_account_currency": balance,
				"debit": balance,
				**posting,
				**dimensions,
			},
		)
		journal_entry.append(
			"accounts",
			{
				"account": accounts["wip_account"],
				"credit_in_account_currency": balance,
				"credit": balance,
				**posting,
				**dimensions,
			},
		)

	journal_entry.flags.ignore_permissions = True
	journal_entry.insert()
	journal_entry.submit()

	return journal_entry.name


def cancel_release_entry(entry: str):
	"""Cancel a release, unless it has already gone"""

	if not frappe.db.exists("Journal Entry", entry):
		return

	journal_entry = frappe.get_doc("Journal Entry", entry)
	if journal_entry.docstatus != 1:
		return

	journal_entry.flags.ignore_permissions = True
	journal_entry.cancel()


def get_containers_of_entry(entry: str) -> list:
	"""Containers whose release list names this entry"""

	candidates = frappe.get_all(
		"ICD Container",
		filters={"expense_release_entry": ("like", f"%{entry}%")},
		fields=["name", "expense_release_entry"],
	)

	return [row.name for row in candidates if entry in get_release_entries(row.expense_release_entry)]


def get_release_entries(value: str | None) -> list:
	"""The journal entries recorded on a container, in the order they were posted"""

	return [entry for entry in (value or "").split(",") if entry]


def mark_released(container: str, entry: str):
	"""Add a release to the container's record of them

	A container can be released more than once, when an expense reaches WIP after an
	earlier invoice, so the entries are kept rather than replaced.
	"""

	entries = get_release_entries(frappe.db.get_value("ICD Container", container, "expense_release_entry"))
	if entry not in entries:
		entries.append(entry)

	set_release(container, entries, nowdate())


def unmark_released(container: str, entry: str):
	"""Take one release back off, leaving any other release the container still has"""

	entries = [
		recorded
		for recorded in get_release_entries(
			frappe.db.get_value("ICD Container", container, "expense_release_entry")
		)
		if recorded != entry
	]

	set_release(container, entries, frappe.db.get_value("ICD Container", container, "expenses_released_on"))


def set_release(container: str, entries: list, released_on: str | None = None):
	frappe.db.set_value(
		"ICD Container",
		container,
		{
			"expenses_released": 1 if entries else 0,
			"expenses_released_on": released_on if entries else None,
			"expense_release_entry": ",".join(entries),
		},
		update_modified=False,
	)
