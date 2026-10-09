import frappe
from frappe import _
from frappe.query_builder.functions import IfNull
from frappe.utils import get_link_to_form, getdate

from icd_tz.icd_tz.api.port_expenses import (
	TRANSPORT_EXPENSE_TYPE,
	get_buying_rates,
	get_container_key,
	get_default_buying_price_list,
)
from icd_tz.icd_tz.api.purchase_order import get_required_wip_account
from icd_tz.icd_tz.api.utils import get_best_criteria


@frappe.whitelist()
def get_transport_services(
	company: str,
	supplier: str,
	from_date: str,
	to_date: str,
	purchase_invoice: str | None = None,
	posting_date: str | None = None,
) -> dict:
	"""Invoice lines for every container the supplier brought to the ICD in the period and is still unpaid

	One line per container, so each carries its own manifest, bill of lading and container dimensions.
	Each item is priced once, on the invoice posting date.
	"""

	frappe.has_permission("Purchase Invoice", "create", throw=True)
	if getdate(from_date) > getdate(to_date):
		frappe.throw(_("From Date cannot be after To Date"))

	containers = get_unpaid_transport_containers(company, supplier, from_date, to_date)
	if not containers:
		frappe.throw(
			_("No unpaid transport services of {0} were received between {1} and {2}").format(
				frappe.bold(supplier), frappe.format(from_date, "Date"), frappe.format(to_date, "Date")
			),
			title=_("Nothing to Bill"),
		)

	container_items = get_container_transport_items(containers)
	validate_no_draft_transport_invoice(get_transport_items(), list(container_items), purchase_invoice)

	price_list = get_default_buying_price_list()
	item_codes = set(container_items.values())
	rates = get_buying_rates(item_codes, price_list, posting_date)
	items = {}
	for item_code in item_codes:
		items[item_code] = frappe.get_cached_value(
			"Item", item_code, ["name", "item_name", "stock_uom"], as_dict=True
		)
		items[item_code].rate = rates.get(item_code, 0)

	wip_account = get_required_wip_account(company)

	return {
		"buying_price_list": price_list,
		"unpriced_items": sorted(item_codes - set(rates)),
		"items": [
			get_transport_line(container, items[container_items[container.icd_container]], wip_account)
			for container in containers
		],
	}


def get_transport_line(container, item, wip_account: str | None) -> dict:
	"""One invoice line for one container, stamped with its accounting dimensions"""

	return {
		"item_code": item.name,
		"item_name": item.item_name,
		"description": _("Transport of {0} ({1}), received {2}").format(
			container.container_no, container.m_bl_no, frappe.format(container.received_date, "Date")
		),
		"uom": item.stock_uom,
		"stock_uom": item.stock_uom,
		"conversion_factor": 1,
		"qty": 1,
		"rate": item.rate,
		"price_list_rate": item.rate,
		"expense_account": wip_account,
		"container_no": container.container_no,
		"manifest": container.manifest,
		"icd_master_bl": container.icd_master_bl,
		"icd_container": container.icd_container,
	}


def get_unpaid_transport_containers(company: str, supplier: str, from_date: str, to_date: str) -> list:
	"""Containers this transporter brought to the ICD in the period, with no transport invoice yet

	A manifest older than the accounting dimensions has no ICD Container, so it never shows.
	"""

	container = frappe.qb.DocType("ICD Container")
	master_bl = frappe.qb.DocType("ICD Master BL")
	manifest = frappe.qb.DocType("Manifest")

	return (
		frappe.qb.from_(container)
		.left_join(master_bl)
		.on(master_bl.name == container.master_bl)
		.left_join(manifest)
		.on(manifest.name == container.manifest)
		.select(
			container.name.as_("icd_container"),
			container.container_no,
			container.master_bl.as_("icd_master_bl"),
			container.manifest,
			container.m_bl_no,
			container.received_date,
			container.size,
			master_bl.cargo_classification,
			manifest.port,
		)
		.where(
			(container.company == company)
			& (container.transporter == supplier)
			& (container.status == "Received")
			& (container.received_date.between(from_date, to_date))
			& (IfNull(container.transport_purchase_invoice, "") == "")
		)
		.orderby(container.received_date, container.container_no)
	).run(as_dict=True)


def get_container_transport_items(containers: list) -> dict:
	"""Transport item of each ICD Container, from the most specific Transport row that matches it"""

	criteria_rows = get_transport_rows()
	container_items = {}
	unmatched = []
	for container in containers:
		key = get_container_key(container, container, container.port)
		row = get_best_criteria(criteria_rows, key)
		if row:
			container_items[container.icd_container] = row.expense_item
		else:
			unmatched.append(f"{container.container_no} ({key['size'] or '-'}, {key['port'] or '-'})")

	if unmatched:
		frappe.throw(
			_(
				"No Transport row matches these containers: {0}. Add a Transport row in ICD TZ Settings > Expenses."
			).format(", ".join(unmatched)),
			title=_("Transport Charges Not Configured"),
		)

	return container_items


def validate_no_draft_transport_invoice(item_codes: set, icd_containers: list, purchase_invoice: str | None):
	"""Another draft carrying one of these containers must be submitted first"""

	item = frappe.qb.DocType("Purchase Invoice Item")
	invoice = frappe.qb.DocType("Purchase Invoice")

	drafts = (
		frappe.qb.from_(item)
		.inner_join(invoice)
		.on(item.parent == invoice.name)
		.select(invoice.name)
		.distinct()
		.where(
			(invoice.docstatus == 0)
			& (invoice.name != (purchase_invoice or ""))
			& (item.item_code.isin(list(item_codes)))
			& (item.icd_container.isin(icd_containers))
		)
	).run(pluck=True)

	if drafts:
		frappe.throw(
			_(
				"Draft Purchase Invoice {0} already carries transport of some of these containers. Submit it first."
			).format(", ".join(get_link_to_form("Purchase Invoice", draft) for draft in drafts)),
			title=_("Draft Transport Invoice Exists"),
		)


def get_transport_rows() -> list:
	settings_doc = frappe.get_cached_doc("ICD TZ Settings")

	return [row for row in settings_doc.expense_types if row.expense_type == TRANSPORT_EXPENSE_TYPE]


def get_transport_items() -> set:
	return {row.expense_item for row in get_transport_rows()}


def get_transport_containers(doc) -> list:
	"""ICD Containers the transport lines of a purchase invoice pay for"""

	transport_items = get_transport_items()

	return list(
		{
			item.icd_container
			for item in doc.items
			if item.item_code in transport_items and item.get("icd_container")
		}
	)


def stamp_transport_invoice(doc):
	"""Record the invoice on the containers it pays transport for, refusing one already paid"""

	containers = get_transport_containers(doc)
	if not containers:
		return

	validate_transport_unpaid(doc, containers)
	frappe.db.set_value(
		"ICD Container",
		{"name": ("in", containers)},
		"transport_purchase_invoice",
		doc.name,
		update_modified=False,
	)


def validate_transport_unpaid(doc, containers: list):
	"""Every container must be unpaid and brought by the invoice supplier, as one invoice pays one transporter

	Locked, so two invoices submitted together cannot both see a container unpaid.
	"""

	icd_container = frappe.qb.DocType("ICD Container")
	rows = (
		frappe.qb.from_(icd_container)
		.select(
			icd_container.container_no, icd_container.transport_purchase_invoice, icd_container.transporter
		)
		.where(icd_container.name.isin(containers))
		.for_update()
	).run(as_dict=True)

	paid = [row for row in rows if row.transport_purchase_invoice]
	if paid:
		frappe.throw(
			_("Transport of these containers is already paid: {0}").format(
				", ".join(
					f"{row.container_no} ({get_link_to_form('Purchase Invoice', row.transport_purchase_invoice)})"
					for row in paid
				)
			),
			title=_("Transport Already Paid"),
		)

	others = sorted(row.container_no for row in rows if row.transporter != doc.supplier)
	if others:
		frappe.throw(
			_("These containers were not received from transporter {0}: {1}").format(
				frappe.bold(doc.supplier), ", ".join(others)
			),
			title=_("Wrong Transporter"),
		)


def clear_transport_invoice(doc):
	"""Free the containers a cancelled invoice paid for, so they can be billed again"""

	frappe.db.set_value(
		"ICD Container",
		{"transport_purchase_invoice": doc.name},
		"transport_purchase_invoice",
		"",
		update_modified=False,
	)


def validate_reception_transport_unpaid(manifest: str, container_no: str):
	"""A reception whose transport is paid must wait until that invoice is cancelled"""

	invoice = frappe.db.get_value(
		"ICD Container", {"manifest": manifest, "container_no": container_no}, "transport_purchase_invoice"
	)
	if invoice:
		frappe.throw(
			_(
				"Transport of container {0} is paid on Purchase Invoice {1}. Cancel that invoice first."
			).format(frappe.bold(container_no), get_link_to_form("Purchase Invoice", invoice)),
			title=_("Transport Already Paid"),
		)
