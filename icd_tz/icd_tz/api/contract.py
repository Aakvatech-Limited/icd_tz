import frappe
from frappe import _
from frappe.utils import cint, nowdate

CF_PARTY_TYPE = "Clearing and Forwarding Company"
STORAGE_CHARGES = ("Free", "Single", "Double")


def before_validate(doc, method):
	"""Fill the party name the way only the client script used to

	ERPNext resolves it from a "<party type>_emgani@aakvatech.comname" field, which does not exist on a
	Clearing and Forwarding Company, so a server side contract would fail without this.
	"""

	if doc.party_type != CF_PARTY_TYPE or not doc.party_name or doc.party_full_name:
		return

	doc.party_full_name = frappe.db.get_value(CF_PARTY_TYPE, doc.party_name, "company_name")


def validate(doc, method):
	clear_unused_billing_basis(doc)

	if doc.party_type != CF_PARTY_TYPE or not doc.party_name:
		return

	validate_contract_period(doc)
	validate_storage_days(doc)

	if doc.is_rate_based and not doc.price_list:
		frappe.throw(_("Price List is mandatory on a Rate Based contract"))


def before_submit(doc, method):
	if doc.party_type != CF_PARTY_TYPE:
		return

	if not doc.is_rate_based and not doc.is_storage_days_based:
		frappe.throw(
			_("Tick either Rate Based or Storage Days Based before submitting a {0} contract").format(
				CF_PARTY_TYPE
			)
		)


@frappe.whitelist()
def get_storage_destinations() -> list:
	"""Places of destination a Storage Days row can use"""

	return sorted(get_settings_destinations())


def get_active_contract(c_and_f_company: str) -> dict:
	"""Submitted contract of a C&F company that covers today"""

	if not c_and_f_company:
		return {}

	contract = frappe.db.get_value(
		"Contract",
		{
			"party_type": CF_PARTY_TYPE,
			"party_name": c_and_f_company,
			"start_date": ("<=", nowdate()),
			"end_date": (">=", nowdate()),
			"docstatus": 1,
		},
		["name", "is_rate_based", "is_storage_days_based", "price_list"],
		as_dict=True,
	)
	return contract or {}


def get_selling_price_list(c_and_f_company: str) -> str:
	"""Price list of a rate based contract, else the ICD TZ Settings default"""

	contract = get_active_contract(c_and_f_company)
	if contract.get("is_rate_based") and contract.get("price_list"):
		return contract["price_list"]

	return frappe.get_cached_doc("ICD TZ Settings").get("default_price_list")


def get_storage_day_counts(container_doc) -> dict:
	"""Free, Single and Double day counts for the container place of destination

	An active storage days based contract of the container C&F company wins over ICD TZ Settings.
	"""

	contract = get_active_contract(container_doc.get("c_and_f_company"))
	if contract.get("is_storage_days_based"):
		source = frappe.get_cached_doc("Contract", contract["name"])
	else:
		source = frappe.get_cached_doc("ICD TZ Settings")

	counts = dict.fromkeys(STORAGE_CHARGES, 0)
	for row in source.storage_days:
		if row.destination == container_doc.place_of_destination and row.charge in counts:
			counts[row.charge] = row.get("to") - row.get("from") + 1

	return counts


def validate_contract_period(doc):
	if not doc.start_date or not doc.end_date:
		frappe.throw(_("Start Date and End Date are mandatory for {0} Contracts").format(CF_PARTY_TYPE))

	contract = frappe.qb.DocType("Contract")
	query = (
		frappe.qb.from_(contract)
		.select(contract.name)
		.where(
			(contract.party_type == CF_PARTY_TYPE)
			& (contract.party_name == doc.party_name)
			& (contract.name != (doc.name or ""))
			& (contract.docstatus != 2)
			& (contract.start_date <= doc.end_date)
			& (contract.end_date >= doc.start_date)
		)
	)
	overlapping_contracts = query.run()

	if overlapping_contracts:
		frappe.throw(
			_("There is already a contract for this company overlapping with this period: <b>{0}</b>").format(
				overlapping_contracts[0][0]
			)
		)


def clear_unused_billing_basis(doc):
	"""Drop the inputs of a billing basis that is not ticked so they cannot drift

	Only a C&F contract has a billing basis, so switching the party type away
	from it must also clear the two checkboxes.
	"""

	if doc.party_type != CF_PARTY_TYPE:
		doc.is_rate_based = 0
		doc.is_storage_days_based = 0

	if not doc.is_rate_based:
		doc.price_list = None

	if not doc.is_storage_days_based:
		doc.storage_days = []


def validate_storage_days(doc):
	if not doc.is_storage_days_based:
		return

	destinations = get_settings_destinations()
	if not destinations:
		frappe.throw(
			_("No Place of Destination is set in ICD TZ Settings, Please set it to continue"),
			title=_("Storage Days Not Configured"),
		)

	defined_rows = set()
	for row in doc.storage_days:
		# this runs before the framework mandatory check, so report an empty row plainly
		if not row.destination or not row.charge:
			frappe.throw(_("At Row#: {0}, Place of Destination and Charge are mandatory").format(row.idx))

		if row.destination not in destinations:
			frappe.throw(
				_("At Row#: {0}, Place of Destination {1} is not set in ICD TZ Settings").format(
					row.idx, frappe.bold(row.destination)
				)
			)

		if cint(row.get("from")) < 1 or cint(row.get("to")) < cint(row.get("from")):
			frappe.throw(
				_("At Row#: {0}, From must be 1 or more and To must not be less than From").format(row.idx)
			)

		if (row.destination, row.charge) in defined_rows:
			frappe.throw(
				_("At Row#: {0}, {1} with charge {2} already exists").format(
					row.idx, frappe.bold(row.destination), frappe.bold(row.charge)
				)
			)

		defined_rows.add((row.destination, row.charge))

	missing_rows = [
		f"{destination} ({charge})"
		for destination in sorted(destinations)
		for charge in STORAGE_CHARGES
		if (destination, charge) not in defined_rows
	]
	if missing_rows:
		frappe.throw(
			_("Storage Days is missing a row for: {0}").format(frappe.bold(", ".join(missing_rows))),
			title=_("Incomplete Storage Days"),
		)


def get_settings_destinations() -> set:
	settings_doc = frappe.get_cached_doc("ICD TZ Settings")

	return {row.destination for row in settings_doc.storage_days if row.destination}
