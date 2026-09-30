import frappe
from frappe import _
from frappe.utils import get_link_to_form, getdate

from icd_tz.icd_tz.api.port_expenses import get_buying_rates, get_default_buying_price_list
from icd_tz.icd_tz.api.purchase_order import get_required_wip_account


@frappe.whitelist()
def get_transport_services(
	company: str, supplier: str, from_date: str, to_date: str, purchase_invoice: str | None = None
) -> dict:
	"""Invoice lines for every container the supplier brought to the ICD in the period and is still unpaid

	One line per container, so each carries its own manifest, bill of lading and container dimensions.
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

	item_code = get_required_transport_charge_item()
	validate_no_draft_transport_invoice(
		item_code, [container.icd_container for container in containers], purchase_invoice
	)

	price_list = get_default_buying_price_list()
	item = frappe.get_cached_value("Item", item_code, ["name", "item_name", "stock_uom"], as_dict=True)
	item.rate = get_buying_rates({item_code}, price_list).get(item_code, 0)
	wip_account = get_required_wip_account(company)

	return {
		"buying_price_list": price_list,
		"items": [get_transport_line(container, item, wip_account) for container in containers],
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

	return frappe.get_all(
		"ICD Container",
		filters={
			"company": company,
			"transporter": supplier,
			"status": "Received",
			"received_date": ("between", [from_date, to_date]),
			"transport_purchase_invoice": ("is", "not set"),
		},
		fields=[
			"name as icd_container",
			"container_no",
			"master_bl as icd_master_bl",
			"manifest",
			"m_bl_no",
			"received_date",
		],
		order_by="received_date asc, container_no asc",
	)


def validate_no_draft_transport_invoice(item_code: str, icd_containers: list, purchase_invoice: str | None):
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
			& (item.item_code == item_code)
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


def get_transport_charge_item() -> str | None:
	return frappe.get_cached_value("ICD TZ Settings", "ICD TZ Settings", "transport_charge_item")


def get_required_transport_charge_item() -> str:
	item_code = get_transport_charge_item()
	if not item_code:
		frappe.throw(
			_("Transport Charge Item is not set on the Expenses tab of ICD TZ Settings"),
			title=_("Transport Charges Not Configured"),
		)

	return item_code


def get_transport_containers(doc) -> list:
	"""ICD Containers the transport lines of a purchase invoice pay for"""

	item_code = get_transport_charge_item()
	if not item_code:
		return []

	return list(
		{
			item.icd_container
			for item in doc.items
			if item.item_code == item_code and item.get("icd_container")
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
