import frappe
from frappe import _
from frappe.utils import create_batch, flt, nowdate

from icd_tz.icd_tz.api.port_expenses import (
	CRITERIA_FIELDS,
	ONE_OFF_EXPENSE_TYPES,
	STORAGE_EXPENSE_TYPES,
	get_default_buying_price_list,
	get_draft_expense_orders,
	get_expense_rows,
	get_manifest_header,
)

BATCH_SIZE = 500


@frappe.whitelist()
def create_purchase_order(
	manifest: str,
	buying_price_list: str | None = None,
	supplier: str | None = None,
	criteria_rows: str | list | None = None,
) -> str:
	"""Draft Purchase Order for the selected port expense rows of one manifest

	Only the criteria row names come back from the page: everything priced is
	recomputed here, so a stale or edited page cannot set its own amounts.
	"""

	frappe.has_permission("Purchase Order", "create", throw=True)
	frappe.has_permission("Manifest", "read", doc=manifest, throw=True)

	selected = set(frappe.parse_json(criteria_rows) or [])
	price_list = buying_price_list or get_default_buying_price_list()
	# the day row names are needed here, they go onto the order line
	rows = [
		row
		for row in get_expense_rows(manifest, price_list, with_day_rows=True)
		if row["criteria_row"] in selected
	]

	validate_expense_rows(rows)
	validate_no_draft_purchase_order(manifest, rows)

	purchase_order = build_purchase_order(manifest, price_list, supplier, rows)
	frappe.msgprint(_("Purchase Order {0} created successfully").format(purchase_order.name), alert=True)

	return purchase_order.name


def validate_expense_rows(rows: list):
	"""A row with no rate or no amount is a configuration gap, not an order line"""

	if not rows:
		frappe.throw(_("Select at least one expense row"))

	invalid = [row for row in rows if flt(row["rate"]) <= 0 or flt(row["amount"]) <= 0]
	if not invalid:
		return

	details = ", ".join(
		_("{0} ({1}): rate {2}, amount {3}").format(
			row["expense_type"], row["item_code"], row["rate"], row["amount"]
		)
		for row in invalid
	)
	frappe.throw(
		_("These rows have no rate or no amount, so they cannot be ordered: {0}").format(details),
		title=_("Incomplete Expense Rows"),
	)


def validate_no_draft_purchase_order(manifest: str, rows: list):
	"""A draft order already covering this manifest must be finished or deleted first"""

	drafts = get_draft_expense_orders(manifest, rows)
	if not drafts:
		return

	frappe.throw(
		_(
			"Draft Purchase Order {0} already covers this manifest or some of its containers. "
			"Submit or delete it before creating another."
		).format(", ".join(drafts)),
		title=_("Duplicate Port Expense Order"),
	)


def build_purchase_order(manifest: str, buying_price_list: str, supplier: str, rows: list):
	"""Draft order carrying one line per container, so cost lands on the right dimension"""

	if not supplier:
		frappe.throw(_("Select a Supplier before creating the Purchase Order"))

	header = get_manifest_header(manifest)

	purchase_order = frappe.new_doc("Purchase Order")
	purchase_order.update(
		{
			"supplier": supplier,
			"company": header.company,
			"transaction_date": nowdate(),
			"schedule_date": nowdate(),
			"buying_price_list": buying_price_list,
			"currency": frappe.get_cached_value("Price List", buying_price_list, "currency"),
			"manifest": manifest,
		}
	)

	for row in rows:
		for container in row["containers"]:
			add_container_line(purchase_order, manifest, row, container)

	purchase_order.flags.ignore_permissions = True
	purchase_order.insert()

	return purchase_order


def add_container_line(purchase_order, manifest: str, row: dict, container: dict):
	"""One order line for one container, stamped with its accounting dimensions"""

	purchase_order.append(
		"items",
		{
			"item_code": row["item_code"],
			"qty": container["qty"],
			"rate": row["rate"],
			"price_list_rate": row["rate"],
			"schedule_date": purchase_order.schedule_date,
			"description": get_expense_description(row, container),
			"container_no": container["container_no"],
			"container_child_refs": ",".join(container["day_rows"]),
			"manifest": manifest,
			"icd_master_bl": container["icd_master_bl"],
			"icd_container": container["icd_container"],
		},
	)


def get_expense_description(row: dict, container: dict) -> str:
	"""Line description that reads on its own in the order and on its print format"""

	criteria = " ".join(str(row[field]) for field in CRITERIA_FIELDS if row[field])
	unit = _("days") if row["expense_type"] in STORAGE_EXPENSE_TYPES else _("container")

	return f"{row['expense_type']} {criteria} - {container['container_no']} ({container['qty']} {unit})"


def on_submit(doc, method):
	coverage = get_expense_coverage(doc)
	validate_not_already_booked(coverage)
	book_expense_containers(doc, coverage)


def validate_not_already_booked(coverage: tuple):
	"""Refuse an order whose charge another order already booked

	The draft guard runs when the order is built, so two people building at the
	same time both pass it. This is the check that actually stops a double bill.
	"""

	one_off, storage_day_rows = coverage

	clashes = []
	for booked_field, container_ids in one_off.items():
		clashes += frappe.get_all(
			"ICD Container",
			filters={"name": ("in", list(container_ids)), booked_field: 1},
			pluck="container_no",
		)

	clashes += frappe.get_all(
		"ICD Container Storage Date",
		filters={"name": ("in", list(storage_day_rows)), "purchase_order": ("is", "set")},
		pluck="parent",
	)

	if clashes:
		frappe.throw(
			_("These containers are already booked for a charge on this order: {0}").format(
				frappe.bold(", ".join(sorted(set(clashes))))
			),
			title=_("Already Booked"),
		)


def on_cancel(doc, method):
	release_expense_containers(doc)


def book_expense_containers(doc, coverage: tuple):
	"""Mark every container and storage day this order covers, so nothing is billed twice"""

	one_off, storage_day_rows = coverage

	for booked_field, container_ids in one_off.items():
		set_rows("ICD Container", container_ids, {booked_field: 1, "purchase_order": doc.name})

	set_rows("ICD Container Storage Date", storage_day_rows, {"purchase_order": doc.name})


def release_expense_containers(doc):
	"""Give back what a cancelled order claimed, or it would be frozen out for ever

	Only what still carries this order is released, so a container already
	re-booked on a later order is left alone. The stamp is what identifies this
	order, so every flag is cleared before the stamp itself goes.
	"""

	one_off, storage_day_rows = get_expense_coverage(doc)

	for booked_field, container_ids in one_off.items():
		set_rows("ICD Container", container_ids, {booked_field: 0}, doc.name)

	claimed = {container for container_ids in one_off.values() for container in container_ids}
	set_rows("ICD Container", claimed, {"purchase_order": ""}, doc.name)
	set_rows(
		"ICD Container Storage Date",
		storage_day_rows,
		{"purchase_order": "", "purchase_invoice": ""},
		doc.name,
	)


def get_expense_coverage(doc) -> tuple[dict, set]:
	"""What an order covers: containers per booked flag, and storage day rows

	A plain purchase order carries no icd_container, so this costs one attribute
	read per line and returns nothing.
	"""

	expense_items = get_expense_items_by_type()
	one_off = {}
	storage_day_rows = set()

	for item in doc.items:
		if not item.get("icd_container"):
			continue

		expense_type = expense_items.get(item.item_code)
		if expense_type in ONE_OFF_EXPENSE_TYPES:
			one_off.setdefault(ONE_OFF_EXPENSE_TYPES[expense_type], set()).add(item.icd_container)

		elif expense_type in STORAGE_EXPENSE_TYPES and item.get("container_child_refs"):
			storage_day_rows.update(ref for ref in item.container_child_refs.split(",") if ref)

	return one_off, storage_day_rows


def get_expense_items_by_type() -> dict:
	"""Item code to expense type, read from the configured criteria"""

	settings_doc = frappe.get_cached_doc("ICD TZ Settings")

	return {row.expense_item: row.expense_type for row in settings_doc.expense_types}


def set_rows(doctype: str, names, values: dict, purchase_order: str | None = None):
	"""Write values to named rows, optionally only where they still carry this order"""

	for batch in create_batch(list(names), BATCH_SIZE):
		filters = {"name": ("in", batch)}
		if purchase_order:
			filters["purchase_order"] = purchase_order

		frappe.db.set_value(doctype, filters, values, update_modified=False)
