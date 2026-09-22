from time import sleep

import frappe
from frappe import _
from frappe.utils import cint, nowdate

from icd_tz.icd_tz.api.accounting_dimensions import get_container_dimensions
from icd_tz.icd_tz.api.contract import get_selling_price_list, get_storage_day_counts
from icd_tz.icd_tz.api.utils import (
	get_service_item,
	get_service_key,
	throw_missing_criteria,
	validate_qty_storage_item,
)
from icd_tz.icd_tz.doctype.waiver_request.waiver_request import apply_approved_waiver


def before_save(doc, method):
	validate_qty_storage_item(doc)


def before_submit(doc, method):
	validate_empty_containers_are_billed_apart(doc)

	if doc.waiver_status == "Pending":
		frappe.throw(
			_(
				"This Sales Order has a pending Waiver Request. Please wait for it to be Approved or Rejected before submitting."
			)
		)


def on_trash(doc, method):
	unlink_sales_order(doc)


def validate_empty_containers_are_billed_apart(doc):
	"""An order bills either the cargo or the empty boxes, never both

	One M BL can cover both, and the empty box is owed by the shipping line, so
	letting them share an order would put that debt on the consignee invoice.
	"""

	container_ids, empty_containers = get_order_containers(doc)
	if not empty_containers or len(empty_containers) == len(container_ids):
		return

	frappe.throw(
		_(
			"Empty containers must be billed on their own Sales Order, but this one also bills cargo: {0}"
		).format(frappe.bold(", ".join(sorted({row.container_no for row in empty_containers})))),
		title=_("Empty Containers Mixed With Cargo"),
	)


def get_order_containers(doc) -> tuple[set, list]:
	"""The containers an order bills, and which of them are empty boxes"""

	container_ids = {item.container_id for item in doc.items if item.get("container_id")}
	if not container_ids:
		return set(), []

	empty_containers = frappe.get_all(
		"Container",
		filters={"name": ("in", list(container_ids)), "is_empty_container": 1},
		fields=["name", "container_no"],
	)

	return container_ids, empty_containers


def is_empty_container_order(doc) -> bool:
	"""Whether this order bills empty containers rather than the cargo of an M BL"""

	container_ids, empty_containers = get_order_containers(doc)

	return bool(container_ids) and len(empty_containers) == len(container_ids)


def replace_items(doc, items: list):
	"""Swap an order onto a freshly priced set of charge rows"""

	if not items:
		frappe.throw(
			_("Nothing is left to bill on this order, so its rows were not replaced"),
			title=_("Nothing To Bill"),
		)

	doc.items = []
	for item in items:
		doc.append("items", item)

	doc.set_missing_values()
	apply_approved_waiver(doc)

	doc.save(ignore_permissions=True)
	doc.reload()

	return True


def unlink_sales_order(doc):
	if not doc.m_bl_no:
		return

	service_orders = frappe.db.get_all("Service Order", filters={"sales_order": doc.name})
	if len(service_orders) > 0:
		for row in service_orders:
			frappe.db.set_value("Service Order", row.name, "sales_order", "", update_modified=False)


@frappe.whitelist()
def update_items_on_sales_order(doc_name: str):
	doc = frappe.get_doc("Sales Order", doc_name)

	items = []
	unique_containers = []
	for item in doc.items:
		if item.container_id not in unique_containers:
			unique_containers.append(item.container_id)

	for container_id in unique_containers:
		container_doc = frappe.get_doc("Container", container_id)
		container_doc.update_container_stay(up_to_date=doc.delivery_date)
		container_doc.reload()

	sleep(10)

	if is_empty_container_order(doc):
		return replace_items(doc, get_empty_container_services(doc.m_bl_no))

	items += get_storage_services(doc.m_bl_no, doc.h_bl_no)

	service_order_items, service_docs = get_service_order_items(m_bl_no=doc.m_bl_no, h_bl_no=doc.h_bl_no)
	items += service_order_items

	if len(service_docs) > 0:
		source_doc = service_docs[0]

		if not doc.consignee:
			doc.consignee = source_doc.consignee

		if not doc.company:
			doc.company = source_doc.company

		if not doc.c_and_f_company:
			doc.c_and_f_company = source_doc.c_and_f_company

		if not doc.m_bl_no:
			doc.m_bl_no = source_doc.m_bl_no

		if not doc.h_bl_no:
			doc.h_bl_no = source_doc.h_bl_no

	for record in service_docs:
		record.db_set("sales_order", doc.name)

	doc.items = []
	for item in items:
		doc.append("items", item)

	doc.set_missing_values()
	apply_approved_waiver(doc)

	doc.save(ignore_permissions=True)
	doc.reload()
	return True


@frappe.whitelist()
def make_sales_order(
	doc_type: str | None = None,
	doc_name: str | None = None,
	m_bl_no: str | None = None,
	h_bl_no: str | None = None,
):
	items = []
	company = None
	consignee = None
	c_and_f_company = None
	order_m_bl_no = m_bl_no if m_bl_no else None
	order_h_bl_no = h_bl_no if h_bl_no else None

	items += get_storage_services(m_bl_no, h_bl_no)

	service_order_items, service_docs = get_service_order_items(
		doc_type=doc_type, doc_name=doc_name, m_bl_no=m_bl_no, h_bl_no=h_bl_no
	)

	items += service_order_items
	if len(items) == 0:
		return

	if len(service_docs) > 0:
		source_doc = service_docs[0]

		if not consignee:
			consignee = source_doc.consignee

		if not company:
			company = source_doc.company

		if not c_and_f_company:
			c_and_f_company = source_doc.c_and_f_company

		if not order_m_bl_no:
			order_m_bl_no = source_doc.m_bl_no

		if not order_h_bl_no:
			order_h_bl_no = source_doc.h_bl_no

	else:
		if not consignee and h_bl_no:
			consignee = frappe.get_cached_value("Container", {"h_bl_no": h_bl_no}, "consignee")
		if not consignee and m_bl_no:
			consignee = frappe.get_cached_value("Container", {"m_bl_no": m_bl_no}, "consignee")

	sales_order = build_sales_order(
		items,
		customer=consignee,
		company=company,
		c_and_f_company=c_and_f_company,
		consignee=consignee,
		m_bl_no=order_m_bl_no,
		h_bl_no=order_h_bl_no,
	)

	for doc in service_docs:
		doc.db_set("sales_order", sales_order.name)

	return sales_order.name


@frappe.whitelist()
def make_empty_container_sales_order(m_bl_no: str | None = None, customer: str | None = None) -> str:
	"""Sales Order billing the shipping line for the yard dwell of its empty containers"""

	frappe.has_permission("Sales Order", "create", throw=True)

	if not m_bl_no:
		frappe.throw(_("Please enter the M BL No of the empty containers"))

	if not customer:
		frappe.throw(_("Please select the Customer the empty container storage is billed to"))

	items = get_empty_container_services(m_bl_no)
	if not items:
		frappe.throw(
			_("No empty container storage is waiting to be billed for M BL No: {0}").format(
				frappe.bold(m_bl_no)
			)
		)

	validate_no_draft_empty_container_order({row["container_id"] for row in items})

	sales_order = build_sales_order(
		items,
		customer=customer,
		company=frappe.get_cached_value("Container", items[0]["container_id"], "company"),
		m_bl_no=m_bl_no,
	)

	return sales_order.name


def validate_no_draft_empty_container_order(container_ids: set):
	"""A draft already billing these boxes must be finished or deleted first

	Storage days only carry an invoice once one is submitted, so without this a second
	run of the dialog would bill the shipping line for the same days again.
	"""

	order = frappe.qb.DocType("Sales Order")
	item = frappe.qb.DocType("Sales Order Item")

	drafts = (
		frappe.qb.from_(item)
		.join(order)
		.on(item.parent == order.name)
		.select(order.name)
		.distinct()
		.where((order.docstatus == 0) & (item.container_id.isin(list(container_ids))))
	).run(pluck=True)

	if not drafts:
		return

	frappe.throw(
		_("Draft Sales Order {0} already bills these empty containers. Submit or delete it first.").format(
			frappe.bold(", ".join(sorted(drafts)))
		),
		title=_("Empty Containers Already On A Draft Order"),
	)


def get_empty_container_services(m_bl_no: str) -> list:
	"""Storage rows for the empty containers of an M BL

	Storage only: an empty box holds no cargo, so no shore handling, corridor levy,
	stripping, verification or removal can arise on it. The days are priced on the
	standard container criteria by size, not on the loose cargo rates the box was
	stripped under, because what is left in the yard is equipment.
	"""

	containers = frappe.db.get_all(
		"Container",
		filters={"m_bl_no": m_bl_no, "is_empty_container": 1},
		fields=["name", "days_to_be_billed"],
	)

	settings_doc = frappe.get_cached_doc("ICD TZ Settings")
	services = []

	for container in containers:
		if container.days_to_be_billed == 0:
			continue

		container_doc = frappe.get_doc("Container", container.name)
		container_refs = get_container_refs(container_doc, container_doc.name)
		single_days, double_days = get_container_days_to_be_billed(container_doc)
		key = get_service_key(
			size=container_doc.size,
			cargo_type=container_doc.cargo_type,
			port=container_doc.port_of_destination,
		)

		for service_type, days in (("Storage-Single", single_days), ("Storage-Double", double_days)):
			if not days:
				continue

			item_code = get_service_item(settings_doc, service_type, key)
			if not item_code:
				throw_missing_criteria(service_type, key)

			services.append(
				{
					"item_code": item_code,
					"qty": len(days),
					"container_child_refs": ",".join(days),
					**container_refs,
				}
			)

	return services


def build_sales_order(items: list, customer: str, company: str, c_and_f_company: str | None = None, **values):
	"""Save a draft Sales Order for charge rows the caller has already priced"""

	selling_price_list = get_selling_price_list(c_and_f_company)

	sales_order = frappe.get_doc(
		{
			"doctype": "Sales Order",
			"company": company,
			"customer": customer,
			"c_and_f_company": c_and_f_company,
			"transaction_date": nowdate(),
			"delivery_date": nowdate(),
			"selling_price_list": selling_price_list,
			"currency": frappe.get_cached_value("Price List", selling_price_list, "currency"),
			"items": items,
			**values,
		}
	)

	sales_order.insert()
	sales_order.set_missing_values()
	sales_order.calculate_taxes_and_totals()
	sales_order.save(ignore_permissions=True)
	sales_order.reload()

	frappe.msgprint(
		_("Sales Order {0} created successfully").format(frappe.bold(sales_order.name)), alert=True
	)

	return sales_order


def get_container_refs(source, container_id: str) -> dict:
	"""Container identity and accounting dimensions carried by every charge row

	Resolve once per container, the dimension lookup is two queries.
	"""

	return {
		"container_no": source.container_no,
		"container_id": container_id,
		"manifest": source.manifest,
		**get_container_dimensions(source),
	}


def get_storage_services(m_bl_no=None, h_bl_no=None):
	if not m_bl_no and not h_bl_no:
		frappe.throw(_("Please enter either M BL No or H BL No"))
		return

	services = []

	filters = {}
	if h_bl_no:
		filters["h_bl_no"] = h_bl_no
		filters["has_hbl"] = 1
	elif m_bl_no:
		filters["m_bl_no"] = m_bl_no
		filters["has_hbl"] = 0
		filters["is_empty_container"] = 0

	containers = frappe.db.get_all("Container", filters=filters, fields=["name", "days_to_be_billed"])
	if len(containers) == 0:
		return []

	settings_doc = frappe.get_cached_doc("ICD TZ Settings")

	for container in containers:
		container_doc = frappe.get_doc("Container", container.name)
		container_refs = get_container_refs(container_doc, container_doc.name)

		cancellation_service = get_gatepass_cancellation_service(container_doc, settings_doc, container_refs)
		if cancellation_service:
			services.append(cancellation_service)

		if container.days_to_be_billed == 0:
			continue

		single_days, double_days = get_container_days_to_be_billed(container_doc)

		if container_doc.has_single_charge == 1:
			single_storage_item = get_charged_item(container_doc, settings_doc, "Storage-Single")

			if len(single_days) > 0:
				new_row = {
					"item_code": single_storage_item,
					"qty": len(single_days) * container_doc.gross_volume
					if container_doc.freight_indicator == "LCL"
					else len(single_days),
					"container_child_refs": ",".join(single_days),
					**container_refs,
				}

				services.append(new_row)

		if container_doc.has_double_charge == 1:
			double_storage_item = get_charged_item(container_doc, settings_doc, "Storage-Double")

			if len(double_days) > 0:
				new_row = {
					"item_code": double_storage_item,
					"qty": len(double_days) * container_doc.gross_volume
					if container_doc.freight_indicator == "LCL"
					else len(double_days),
					"container_child_refs": ",".join(double_days),
					**container_refs,
				}

				services.append(new_row)

		if not container_doc.r_sales_invoice and container_doc.has_removal_charges == "Yes":
			removal_item = get_charged_item(container_doc, settings_doc, "Removal")

			services.append(
				{
					"item_code": removal_item,
					"qty": container_doc.gross_volume if container_doc.freight_indicator == "LCL" else 1,
					**container_refs,
				}
			)

	return services


def get_charged_item(container_doc, settings_doc, service_type: str) -> str:
	"""Item a container is charged for one service, from its best fitting criteria row"""

	key = get_service_key(
		size=container_doc.size,
		cargo_type=container_doc.cargo_type,
		port=container_doc.port_of_destination,
	)
	item_code = get_service_item(
		settings_doc,
		service_type,
		key,
		is_loose_cargo=container_doc.freight_indicator == "LCL",
	)
	if not item_code:
		throw_missing_criteria(service_type, key)

	return item_code


def get_gatepass_cancellation_service(container_doc, settings_doc, container_refs: dict):
	"""Charge row for a container whose Gate Pass was cancelled and is not yet invoiced"""

	if container_doc.has_cancellation_charge != 1 or container_doc.g_sales_invoice:
		return {}

	if not settings_doc.gatepass_cancellation_item:
		frappe.throw(_("Gatepass Cancellation Item is not set in ICD TZ Settings, Please set it to continue"))

	return {
		"item_code": settings_doc.gatepass_cancellation_item,
		"qty": 1,
		**container_refs,
	}


def get_container_days_to_be_billed(container_doc):
	single_days = []
	double_days = []
	single_charge_count = 0
	double_charge_count = 0

	day_counts = get_storage_day_counts(container_doc)
	no_of_single_days = day_counts["Single"]
	no_of_double_days = day_counts["Double"]

	for row in container_doc.container_dates:
		if (
			row.is_billable == 1
			and container_doc.has_single_charge == 1
			and single_charge_count < no_of_single_days
		):
			single_days.append(row)
			single_charge_count += 1

		elif (
			row.is_billable == 1
			and container_doc.has_double_charge == 1
			and single_charge_count >= no_of_single_days
			and double_charge_count < no_of_double_days
		):
			double_days.append(row)
			double_charge_count += 1

	single_days = [row.name for row in single_days if not row.sales_invoice]
	double_days = [row.name for row in double_days if not row.sales_invoice]
	return single_days, double_days


def get_service_order_items(doc_type=None, doc_name=None, m_bl_no=None, h_bl_no=None):
	items = []
	service_docs = []

	if h_bl_no or m_bl_no:
		service_docs = get_service_orders(m_bl_no, h_bl_no)

	if len(service_docs) == 0:
		if not doc_type or not doc_name:
			return [], []

		source_doc = frappe.get_cached_doc(doc_type, doc_name)
		if source_doc.sales_invoice:
			return [], []

		service_docs.append(source_doc)

	for doc in service_docs:
		items += get_items(doc)

	return items, service_docs


def get_service_orders(m_bl_no=None, h_bl_no=None):
	service_docs = []

	filters = {}
	if h_bl_no:
		filters["h_bl_no"] = h_bl_no
	elif m_bl_no:
		filters["m_bl_no"] = m_bl_no

	orders = frappe.db.get_all(
		"Service Order", filters=filters, fields=["name", "docstatus", "sales_invoice"]
	)
	if len(orders) == 0:
		return []

	draft_service_orders = [order for order in orders if order.docstatus == 0]
	msg = ""
	if h_bl_no:
		msg = f"H BL No: <b>{h_bl_no}</b>"
	elif m_bl_no:
		msg = f"M BL No: <b>{m_bl_no}</b>"

	if len(draft_service_orders) > 0:
		frappe.throw(f"Please submit all draft Service Orders for {msg}")

	for entry in orders:
		if entry.sales_invoice:
			continue

		source_doc = frappe.get_cached_doc("Service Order", entry.name)
		service_docs.append(source_doc)

	return service_docs


def get_items(doc):
	container_refs = get_container_refs(doc, doc.container_id)

	items = []
	for item in doc.get("services"):
		row_item = {
			"item_code": item.get("service"),
			"qty": item.get("qty"),
			**container_refs,
		}
		items.append(row_item)

	return items


@frappe.whitelist()
def create_sales_order(data: str | dict):
	data = frappe.parse_json(data)

	if cint(data.get("is_empty_container")):
		return make_empty_container_sales_order(data.get("m_bl_no"), data.get("customer"))

	return make_sales_order(m_bl_no=data.get("m_bl_no"), h_bl_no=data.get("h_bl_no"))
