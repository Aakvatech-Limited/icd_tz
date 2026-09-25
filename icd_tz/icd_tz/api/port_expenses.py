import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import date_diff, flt, getdate, nowdate

from icd_tz.icd_tz.api.accounting_dimensions import build_dimension_name
from icd_tz.icd_tz.api.utils import get_best_criteria, get_size_bucket

ONE_OFF_EXPENSE_TYPES = {
	"Shore": "is_shore_booked",
	"Levy": "is_levy_booked",
	"Removal": "is_removal_booked",
}
STORAGE_EXPENSE_TYPES = {"Storage-Single": "Single", "Storage-Double": "Double"}
# the contract against the ICD TZ Expense Detail select options, asserted by a test
EXPENSE_TYPES = (*ONE_OFF_EXPENSE_TYPES, *STORAGE_EXPENSE_TYPES)

# the terminal grants free days, which are recorded on the container so the stay is
# auditable but are never billed, so they carry no expense type
FREE_CHARGE = "Free"

# the storage charges answer as one, the day rows say which band each day is
STORAGE_CHARGE_LABEL = "Storage"

CRITERIA_FIELDS = ("size", "cargo_type", "destination", "port")
CARGO_TYPES = {"IM": "Local", "TR": "Transit"}


def get_cargo_type(cargo_classification: str | None) -> str | None:
	"""Local or Transit, from the bill of lading cargo classification"""

	return CARGO_TYPES.get((cargo_classification or "").strip().upper())


def get_container_key(container, master_bl: dict, port: str | None) -> dict:
	"""Criteria values a container is matched on"""

	return {
		"size": get_size_bucket(container.get("size")),
		"cargo_type": get_cargo_type(master_bl.get("cargo_classification")),
		"destination": master_bl.get("place_of_destination"),
		"port": port,
	}


def get_matching_criteria(criteria_rows, key: dict) -> dict:
	"""The winning criteria row per expense type, the most specific match"""

	rows_by_type = {}
	for row in criteria_rows:
		rows_by_type.setdefault(row.expense_type, []).append(row)

	winners = {}
	for expense_type, rows in rows_by_type.items():
		winner = get_best_criteria(rows, key)
		if winner:
			winners[expense_type] = winner

	return winners


def get_port_storage_bands(settings_doc) -> dict:
	"""Port storage day bands, as {charge: {"from": int, "to": int}}"""

	# a seeded row carries only the charge until the day range is confirmed
	return {
		row.charge: {"from": row.get("from"), "to": row.get("to")}
		for row in settings_doc.port_storage_days
		if is_band_configured(row)
	}


def is_band_configured(row) -> bool:
	"""Whether a storage band has had its day range confirmed"""

	return bool(row.get("from") and row.get("to"))


def get_charge_of_day(day, start_date, bands: dict) -> str | None:
	"""Band a single day of the stay falls in, counting the discharge day as day one"""

	day_number = date_diff(day, start_date) + 1
	for charge, band in bands.items():
		if band["from"] <= day_number <= band["to"]:
			return charge

	return None


def get_manifest_header(manifest: str) -> dict:
	"""Manifest a port expense run is for

	Its dimension records only exist once it is submitted, so an earlier run
	would silently price nothing.
	"""

	header = frappe.db.get_value(
		"Manifest", manifest, ["name", "port", "company", "vessel_name", "docstatus"], as_dict=True
	)
	if not header:
		frappe.throw(_("Manifest {0} not found").format(manifest))

	if header.docstatus != 1:
		frappe.throw(_("Manifest {0} is not submitted, so it has no containers to expense").format(manifest))

	return header


def get_expense_rows(manifest: str, buying_price_list: str, with_day_rows: bool = False) -> list:
	"""Every configured expense of a manifest, including the ones no container matches"""

	header = get_manifest_header(manifest)
	settings_doc = frappe.get_cached_doc("ICD TZ Settings")

	# a row naming another port must never show, a blank port matches any
	criteria_rows = [row for row in settings_doc.expense_types if not row.port or row.port == header.port]
	if not criteria_rows:
		frappe.throw(
			_("No Port Expense Pricing Criteria is set in ICD TZ Settings, Please set it to continue"),
			title=_("Port Expenses Not Configured"),
		)

	validate_storage_bands_configured(settings_doc, criteria_rows)

	master_bls = get_manifest_master_bls(manifest)
	unbilled_days = get_unbilled_storage_days(manifest, with_day_rows)

	# seeded before any container is read, so a charge no container matches still shows
	buckets = {row.name: get_expense_bucket(row) for row in criteria_rows}

	shared_bills = get_shared_container_bills(manifest)
	for container in get_manifest_containers(manifest):
		charge_keys = get_container_charge_keys(
			container, shared_bills.get(container.container_no, []), master_bls, header.port
		)
		add_container_charges(buckets, criteria_rows, charge_keys, unbilled_days)

	return price_expense_rows(list(buckets.values()), buying_price_list)


def get_container_charge_keys(container, other_bills: list, master_bls: dict, port: str | None) -> list:
	"""The container on its own bill, then on the first bill of each further cargo type
	the bills sharing an LCL box carry, as (container tagged with that bill, criteria key)
	"""

	key = get_container_key(container, master_bls.get(container.master_bl) or {}, port)
	keys = [(container, key)]

	cargo_types = {key["cargo_type"]}
	for bill in other_bills:
		bill_key = get_container_key(container, master_bls.get(bill) or {}, port)
		if bill_key["cargo_type"] in cargo_types:
			continue

		cargo_types.add(bill_key["cargo_type"])
		keys.append((frappe._dict(container, master_bl=bill), bill_key))

	return keys


def add_container_charges(buckets: dict, criteria_rows: list, charge_keys: list, unbilled_days: dict):
	"""Every charge of the first key, then each one off charge a further cargo type
	prices on another criteria row

	The port charges a shared box once per cargo type only where the rate differs, and
	storage stays on the first bill, its day rows belong to the box.
	"""

	charged_rows = set()
	for index, (container, key) in enumerate(charge_keys):
		for expense_type, criteria_row in get_matching_criteria(criteria_rows, key).items():
			if index and (expense_type not in ONE_OFF_EXPENSE_TYPES or criteria_row.name in charged_rows):
				continue

			charged_rows.add(criteria_row.name)
			add_container_to_bucket(buckets[criteria_row.name], container, expense_type, unbilled_days)


def validate_storage_bands_configured(settings_doc, criteria_rows: list):
	"""A storage charge cannot be priced until its day ranges are confirmed

	Without them every day is recorded with no charge, which reads as nothing to
	bill rather than as nothing configured, so say so before anything is priced.
	"""

	if not any(row.expense_type in STORAGE_EXPENSE_TYPES for row in criteria_rows):
		return

	if not settings_doc.port_storage_days:
		frappe.throw(
			_("No Port Storage Days are set on the Expenses tab of ICD TZ Settings"),
			title=_("Port Storage Days Not Set"),
		)

	unset = [row.charge for row in settings_doc.port_storage_days if not is_band_configured(row)]
	if unset:
		frappe.throw(
			_("Set the From and To days for {0} on the Expenses tab of ICD TZ Settings").format(
				", ".join(unset)
			),
			title=_("Port Storage Days Not Set"),
		)


def get_expense_bucket(criteria_row) -> dict:
	return {
		"criteria_row": criteria_row.name,
		"expense_type": criteria_row.expense_type,
		"item_code": criteria_row.expense_item,
		"size": criteria_row.size,
		"cargo_type": criteria_row.cargo_type,
		"destination": criteria_row.destination,
		"port": criteria_row.port,
		"containers": [],
	}


def add_container_to_bucket(bucket: dict, container, expense_type: str, unbilled_days: dict):
	"""A container contributes one unit to a one off charge, or its unbilled days to storage"""

	day_rows = []

	if expense_type in ONE_OFF_EXPENSE_TYPES:
		if container.get(ONE_OFF_EXPENSE_TYPES[expense_type]):
			return

		quantity = 1

	else:
		if not container.ship_dc_date:
			return

		# a day count for the view, the day row names when an order is being built
		unbilled = unbilled_days.get((container.name, STORAGE_EXPENSE_TYPES[expense_type]), 0)
		day_rows = unbilled if isinstance(unbilled, list) else []
		quantity = len(unbilled) if isinstance(unbilled, list) else unbilled
		if not quantity:
			return

	bucket["containers"].append(
		{
			"icd_container": container.name,
			"container_no": container.container_no,
			"icd_master_bl": container.master_bl,
			"qty": quantity,
			"day_rows": day_rows,
		}
	)


def price_expense_rows(rows: list, buying_price_list: str) -> list:
	"""Attach the price list rate and the resulting amount to every row"""

	rates = get_buying_rates({row["item_code"] for row in rows}, buying_price_list)

	for row in rows:
		row["container_count"] = len(row["containers"])
		row["qty"] = sum(container["qty"] for container in row["containers"])
		row["rate"] = rates.get(row["item_code"], 0)
		row["amount"] = flt(row["qty"]) * flt(row["rate"])

	rows.sort(key=lambda row: (row["expense_type"], row["size"] or "", row["cargo_type"] or ""))

	return rows


def get_manifest_containers(manifest: str) -> list:
	return frappe.get_all(
		"ICD Container",
		filters={"manifest": manifest},
		fields=[
			"name",
			"container_no",
			"size",
			"master_bl",
			"ship_dc_date",
			*ONE_OFF_EXPENSE_TYPES.values(),
		],
		order_by="container_no asc",
	)


def get_manifest_master_bls(manifest: str) -> dict:
	rows = frappe.get_all(
		"ICD Master BL",
		filters={"manifest": manifest},
		fields=["name", "cargo_classification", "place_of_destination"],
	)

	return {row.name: row for row in rows}


def get_shared_container_bills(manifest: str) -> dict:
	"""ICD Master BL of every bill after the first, for each box listed under several"""

	bills = {}
	for row in frappe.get_all(
		"Containers Detail",
		filters={"parent": manifest, "m_bl_no": ("is", "set")},
		fields=["container_no", "m_bl_no"],
		order_by="idx asc",
	):
		names = bills.setdefault(row.container_no, [])
		name = build_dimension_name(row.m_bl_no, manifest)
		if name not in names:
			names.append(name)

	return {container_no: names[1:] for container_no, names in bills.items() if len(names) > 1}


def get_unbilled_storage_days(manifest: str, with_day_rows: bool = False) -> dict:
	"""Chargeable storage days not yet on a purchase order, keyed by container and charge

	The view only needs how many, which is a count of a few hundred rows instead
	of one row per container day. The names are read only when an order is built,
	because that is the one place they are written to the order line.
	"""

	storage_date = frappe.qb.DocType("ICD Container Storage Date")
	icd_container = frappe.qb.DocType("ICD Container")

	query = (
		frappe.qb.from_(storage_date)
		.inner_join(icd_container)
		.on(storage_date.parent == icd_container.name)
		.where(
			(icd_container.manifest == manifest)
			& (storage_date.charge.notnull())
			& (storage_date.charge != "")
			# a free day is never ordered, said here rather than left to the fact
			# that no expense type happens to map to it
			& (storage_date.charge != FREE_CHARGE)
			& ((storage_date.purchase_order.isnull()) | (storage_date.purchase_order == ""))
		)
	)

	if not with_day_rows:
		counted = query.select(storage_date.parent, storage_date.charge, Count("*").as_("days")).groupby(
			storage_date.parent, storage_date.charge
		)

		return {(row.parent, row.charge): row.days for row in counted.run(as_dict=True)}

	rows = query.select(storage_date.name, storage_date.parent, storage_date.charge).orderby(
		storage_date.date
	)

	unbilled = {}
	for row in rows.run(as_dict=True):
		unbilled.setdefault((row.parent, row.charge), []).append(row.name)

	return unbilled


def get_buying_rates(item_codes: set, price_list: str) -> dict:
	"""Current buying rate of each item, the newest price that is valid today winning"""

	if not item_codes or not price_list:
		return {}

	prices = frappe.get_all(
		"Item Price",
		filters={"price_list": price_list, "item_code": ("in", list(item_codes)), "buying": 1},
		fields=["item_code", "price_list_rate", "valid_from", "valid_upto"],
		order_by="valid_from asc",
	)

	return {price.item_code: flt(price.price_list_rate) for price in prices if is_price_current(price)}


def is_price_current(price) -> bool:
	today = getdate(nowdate())

	if price.valid_from and getdate(price.valid_from) > today:
		return False

	return not (price.valid_upto and getdate(price.valid_upto) < today)


def get_default_buying_price_list() -> str:
	"""The configured buying price list, which has no safe default to fall back on"""

	price_list = frappe.get_cached_value("ICD TZ Settings", "ICD TZ Settings", "default_buying_price_list")
	if not price_list:
		frappe.throw(
			_("Default Buying Price List is not set on the Expenses tab of ICD TZ Settings"),
			title=_("Port Expenses Not Configured"),
		)

	return price_list


def get_draft_expense_orders(manifest: str, rows: list) -> list:
	"""Draft orders touching the same manifest, bill of lading or container"""

	containers = [container["icd_container"] for row in rows for container in row["containers"]]
	master_bls = [
		container["icd_master_bl"]
		for row in rows
		for container in row["containers"]
		if container["icd_master_bl"]
	]

	item = frappe.qb.DocType("Purchase Order Item")
	order = frappe.qb.DocType("Purchase Order")

	overlap = item.manifest == manifest
	if master_bls:
		overlap = overlap | item.icd_master_bl.isin(master_bls)
	if containers:
		overlap = overlap | item.icd_container.isin(containers)

	return (
		frappe.qb.from_(item)
		.inner_join(order)
		.on(item.parent == order.name)
		.select(order.name)
		.distinct()
		.where((order.docstatus == 0) & overlap)
	).run(pluck=True)


def get_unpaid_port_charges(manifest: str, container_no: str) -> list:
	"""Port charges the terminal has not been paid for this container yet

	Only the charges this ICD actually configures are reported. A site that does
	not track port expenses has nothing to answer for, and neither does a charge
	no criteria row asks for.
	"""

	icd_container = frappe.db.get_value(
		"ICD Container",
		{"manifest": manifest, "container_no": container_no},
		["name", *ONE_OFF_EXPENSE_TYPES.values()],
		as_dict=True,
	)
	if not icd_container:
		return []

	configured = {row.expense_type for row in frappe.get_cached_doc("ICD TZ Settings").expense_types}

	unpaid = [
		expense_type
		for expense_type, booked_field in ONE_OFF_EXPENSE_TYPES.items()
		if expense_type in configured and not icd_container.get(booked_field)
	]

	if configured & set(STORAGE_EXPENSE_TYPES) and has_unbilled_storage_days(icd_container.name):
		unpaid.append(STORAGE_CHARGE_LABEL)

	return unpaid


def has_unbilled_storage_days(icd_container: str) -> bool:
	"""Whether any day the terminal charges for is still not on a purchase order"""

	storage_date = frappe.qb.DocType("ICD Container Storage Date")

	# an unset Data column is NULL, and IN (NULL) matches nothing, so both the
	# empty string and NULL have to be asked for explicitly
	unbilled = (
		frappe.qb.from_(storage_date)
		.select(storage_date.name)
		.where(
			(storage_date.parent == icd_container)
			& (storage_date.charge.notnull())
			& (storage_date.charge.notin(["", FREE_CHARGE]))
			& ((storage_date.purchase_order.isnull()) | (storage_date.purchase_order == ""))
		)
		.limit(1)
	).run()

	return bool(unbilled)


@frappe.whitelist()
def get_expense_view(manifest: str, buying_price_list: str | None = None) -> dict:
	"""Everything the port expense page shows for one manifest"""

	frappe.has_permission("Manifest", "read", doc=manifest, throw=True)

	header = get_manifest_header(manifest)
	price_list = buying_price_list or get_default_buying_price_list()
	rows = get_expense_rows(manifest, price_list)

	return {
		"manifest": manifest,
		"port": header.port,
		"vessel_name": header.vessel_name,
		"buying_price_list": price_list,
		"currency": frappe.get_cached_value("Price List", price_list, "currency") if price_list else None,
		"summary": get_expense_summary(manifest, rows),
		"rows": get_display_rows(rows),
		"draft_purchase_orders": get_draft_expense_orders(manifest, rows),
	}


def get_display_rows(rows: list) -> list:
	"""One row per distinct per container quantity, so every row multiplies out

	A storage charge covers containers that spent different numbers of days at
	the port. Shown as one row it cannot read quantity x containers x rate, so
	each quantity gets its own row. The container lists are left out and fetched
	per row, a large manifest would otherwise ship thousands of names.
	"""

	display_rows = []
	for row in rows:
		base = {key: value for key, value in row.items() if key != "containers"}

		if not row["containers"]:
			display_rows.append({**base, "row_key": row["criteria_row"], "display_qty": 0})
			continue

		for quantity, containers in sorted(get_containers_by_quantity(row).items()):
			billed = quantity * len(containers)
			display_rows.append(
				{
					**base,
					"row_key": f"{row['criteria_row']}:{quantity}",
					"display_qty": quantity,
					"container_count": len(containers),
					"qty": billed,
					"amount": flt(billed) * flt(row["rate"]),
				}
			)

	return display_rows


def get_containers_by_quantity(row: dict) -> dict:
	grouped = {}
	for container in row["containers"]:
		grouped.setdefault(container["qty"], []).append(container)

	return grouped


@frappe.whitelist()
def get_expense_row_containers(
	manifest: str,
	criteria_row: str,
	display_qty: float | None = None,
	buying_price_list: str | None = None,
) -> list:
	"""Containers behind one displayed row, for the drill down

	A criteria row is shown as several rows when its containers spent different
	numbers of days at the port, so the quantity narrows the list to the ones
	that row actually covers.
	"""

	frappe.has_permission("Manifest", "read", doc=manifest, throw=True)

	price_list = buying_price_list or get_default_buying_price_list()
	# every criteria row has to be matched before the winner of this one is known,
	# so the whole manifest is aggregated and the asked for bucket picked out
	for row in get_expense_rows(manifest, price_list):
		if row["criteria_row"] != criteria_row:
			continue

		return [
			{"container_no": container["container_no"], "qty": container["qty"]}
			for container in row["containers"]
			if display_qty is None or container["qty"] == flt(display_qty)
		]

	return []


def get_expense_summary(manifest: str, rows: list) -> dict:
	billable = {container["icd_container"] for row in rows for container in row["containers"] if row["qty"]}

	return {
		"total_containers": frappe.db.count("ICD Container", {"manifest": manifest}),
		"billable_containers": len(billable),
		# read from the stamp, a container with no matching criteria is not a booked one
		"booked_containers": frappe.db.count(
			"ICD Container", {"manifest": manifest, "purchase_order": ("is", "set")}
		),
		"missing_discharge_date": frappe.db.count(
			"ICD Container", {"manifest": manifest, "ship_dc_date": ("is", "not set")}
		),
	}
