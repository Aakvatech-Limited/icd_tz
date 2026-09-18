"""Manifest-grained accounting dimensions.

ICD Container and ICD Master BL exist so a Purchase Order or Purchase Invoice can be
costed against a container or a bill of lading before the Container record is created
at Container Reception.
"""

import re

import frappe
from frappe.utils import now, nowdate

# Accounting Dimension fieldname is scrub(document_type)
DIMENSIONS = {"ICD Container": "icd_container", "ICD Master BL": "icd_master_bl"}

# Orders post no GL Entry, so they are checked on their own dimension fields
ORDER_DOCTYPES = ("Purchase Order", "Purchase Order Item", "Sales Order", "Sales Order Item")

# Tables the cancellation guard filters, so their dimension fields need an index
GUARDED_DOCTYPES = ("GL Entry", *ORDER_DOCTYPES)

# erpnext groups dimension fields under this section break
ACCOUNTING_SECTION = "accounting_dimensions_section"

# broadest first, the order the fields read in on a form
DIMENSION_DISPLAY_ORDER = ("manifest", "icd_master_bl", "icd_container")


def get_container_dimensions(source) -> dict:
	"""Dimension values for a charge row, read from its container_no, m_bl_no and manifest

	Resolved by data rather than by rebuilding the record name, so the ID format stays
	the autoname's business. A manifest submitted before these dimensions existed has no
	records, and its rows stay blank instead of naming something that does not resolve.
	"""

	if not source.manifest or not source.container_no:
		return {}

	values = {}
	container = frappe.db.get_value(
		"ICD Container", {"manifest": source.manifest, "container_no": source.container_no}, "name"
	)
	if container:
		values["icd_container"] = container

	if source.m_bl_no:
		master_bl = frappe.db.get_value(
			"ICD Master BL", {"manifest": source.manifest, "m_bl_no": source.m_bl_no}, "name"
		)
		if master_bl:
			values["icd_master_bl"] = master_bl

	return values


def build_dimension_name(value: str, manifest: str) -> str:
	"""The one definition of the dimension ID, MSKU1234567:2026-00042

	The manifest keeps only its numeric tail, every ICD series prefix being alphabetic.
	Bulk creation sets the name itself, so the controllers autoname through here too.
	"""

	manifest_code = re.sub(r"^\D+", "", manifest or "")
	if not manifest_code:
		frappe.throw(
			f"Manifest <b>{manifest}</b> has no numeric part, a dimension ID cannot be built from it"
		)

	return f"{value}:{manifest_code}"


def create_dimension_records(manifest_doc):
	"""One ICD Master BL per bill of lading, one ICD Container per manifested unit

	Both are written with bulk_insert. They are read-only, in_create and hook-free, their
	names are deterministic, and a manifest can carry hundreds of rows.
	"""

	consignees = get_bl_consignees(manifest_doc)
	master_bl_names = create_master_bls(manifest_doc, consignees)
	create_containers(manifest_doc, consignees, master_bl_names)


def get_bl_consignees(manifest_doc) -> dict:
	"""Consignee link value per M BL No, blank where the Consignee record is missing

	Consignee is named after consignee_name, so the manifest value is the link value.
	"""

	names = {row.consignee_name for row in manifest_doc.master_bl if row.consignee_name}
	known = get_existing_consignees(names)

	# first row wins, the same rule create_master_bls uses for every other field
	consignees = {}
	for row in manifest_doc.master_bl:
		if row.m_bl_no in consignees:
			continue

		consignees[row.m_bl_no] = row.consignee_name if row.consignee_name in known else None

	return consignees


def get_existing_consignees(names) -> set:
	"""Consignee records that already exist, resolved in one query"""

	if not names:
		return set()

	return set(frappe.get_all("Consignee", filters={"name": ["in", list(names)]}, pluck="name"))


def create_master_bls(manifest_doc, consignees: dict) -> dict:
	"""One ICD Master BL per M BL No on the manifest, returns the name of each"""

	rows = {}
	for row in manifest_doc.master_bl:
		if not row.m_bl_no or row.m_bl_no in rows:
			continue

		rows[row.m_bl_no] = {
			"name": build_dimension_name(row.m_bl_no, manifest_doc.name),
			"m_bl_no": row.m_bl_no,
			"manifest": manifest_doc.name,
			"posting_date": nowdate(),
			"company": manifest_doc.company,
			"consignee": consignees.get(row.m_bl_no),
			"cargo_classification": row.cargo_classification,
			"number_of_containers": row.number_of_containers,
			"place_of_destination": row.place_of_destination,
			"place_of_delivery": row.place_of_delivery,
			"port_of_loading": row.port_of_loading,
			"cargo_description": row.cargo_description,
			"vessel_name": manifest_doc.vessel_name,
			"voyage_no": manifest_doc.voyage_no,
			"shipping_agent_code": row.shipping_agent_code,
			"shipping_agent_name": row.shipping_agent_name,
		}

	bulk_insert_dimension("ICD Master BL", list(rows.values()))

	return {m_bl_no: row["name"] for m_bl_no, row in rows.items()}


def create_containers(manifest_doc, consignees: dict, master_bl_names: dict):
	"""One record per manifested unit, loose cargo and vehicles included

	The HBL Container rows are deliberately left out. An LCL box carries many house bills
	but it is moved and costed once, so it gets one dimension value.
	"""

	rows = {}
	for row in manifest_doc.containers:
		if not row.container_no:
			continue

		if row.container_no in rows:
			validate_one_bill_of_lading(row, rows[row.container_no]["m_bl_no"])
			continue

		rows[row.container_no] = {
			"name": build_dimension_name(row.container_no, manifest_doc.name),
			"container_no": row.container_no,
			"manifest": manifest_doc.name,
			"posting_date": nowdate(),
			"company": manifest_doc.company,
			"m_bl_no": row.m_bl_no,
			# a containers row can name a bill the Master BL sheet never listed, bulk_insert
			# validates no links, so an absent bill must stay blank rather than dangle
			"master_bl": master_bl_names.get(row.m_bl_no),
			"consignee": consignees.get(row.m_bl_no),
			"type_of_container": row.type_of_container,
			"size": row.container_size,
			"freight_indicator": row.freight_indicator,
			"no_of_packages": row.no_of_packages,
			"package_unit": row.package_unit,
			"weight": row.weight,
			"weight_unit": row.weight_unit,
			"vessel_name": manifest_doc.vessel_name,
			"voyage_no": manifest_doc.voyage_no,
			"arrival_date": manifest_doc.arrival_date,
		}

	bulk_insert_dimension("ICD Container", list(rows.values()))


def bulk_insert_dimension(doctype: str, rows: list):
	"""Write the dimension records of one manifest in a single statement

	Each row is still built through new_doc, which applies the field defaults and type
	coercion that a raw insert skips: an Int column rejects the None a blank manifest
	cell gives. Duplicate names still raise, the name is the primary key.
	"""

	if not rows:
		return

	timestamp = now()
	user = frappe.session.user

	records = []
	for row in rows:
		doc = frappe.new_doc(doctype)
		doc.update(row)
		doc.owner = doc.modified_by = user
		doc.creation = doc.modified = timestamp
		records.append(doc.get_valid_dict(convert_dates_to_str=True))

	fields = list(records[0].keys())
	frappe.db.bulk_insert(doctype, fields, [[record[field] for field in fields] for record in records])


def validate_one_bill_of_lading(row, first_m_bl_no: str | None):
	"""One container gets one dimension record per manifest

	If the manifest puts a container under two bills, every cost booked on it would land
	on whichever bill was read first, so the manifest is rejected instead.
	"""

	if not row.m_bl_no or not first_m_bl_no or row.m_bl_no == first_m_bl_no:
		return

	frappe.throw(
		f"Container <b>{row.container_no}</b> appears on this manifest under two bills of lading: "
		f"<b>{first_m_bl_no}</b> and <b>{row.m_bl_no}</b>."
		"<br>Correct the manifest file, its costs cannot be attributed to one bill."
	)


def validate_manifest_not_in_accounts(manifest: str):
	"""Block cancellation while any accounting document still carries the manifest

	Cancelling deletes the dimension records, and frappe refuses to delete a record any
	document still links to, whatever its docstatus. So this guard counts cancelled and
	draft documents too: anything narrower reports the manifest as cancellable and then
	fails inside on_cancel with a LinkExistsError naming a GL Entry nobody can delete.
	"""

	dimension_names = get_dimension_names(manifest)
	blockers = get_referencing_vouchers(manifest, dimension_names) + get_referencing_orders(dimension_names)
	if not blockers:
		return

	document_list = ", ".join(f"<b>{doctype}: {name}</b>" for doctype, name in blockers)
	frappe.throw(
		f"Manifest <b>{manifest}</b> is still referenced by: {document_list}. "
		"<br>Remove those references first, this manifest cannot be cancelled."
	)


def get_referencing_vouchers(manifest: str, dimension_names: dict) -> list:
	"""Vouchers whose GL Entries carry this manifest, through the manifest field or a dimension

	Every posted document reaches the ledger, so GL Entry covers them all at once.
	Cancelled entries count: erpnext keeps their rows and only flags is_cancelled.
	"""

	filter_sets = get_dimension_filters("GL Entry", dimension_names)
	if frappe.db.has_column("GL Entry", "manifest"):
		filter_sets.append({"manifest": manifest})

	vouchers = set()
	for filters in filter_sets:
		vouchers.update(
			(row.voucher_type, row.voucher_no)
			for row in frappe.get_all(
				"GL Entry",
				filters=filters,
				fields=["voucher_type", "voucher_no"],
				distinct=True,
				limit=5,
			)
		)

	return sorted(vouchers)


def get_referencing_orders(dimension_names: dict) -> list:
	"""Purchase and Sales Orders carrying this manifest, at parent and item level

	Neither posts a GL Entry, and a draft order blocks the delete just as a submitted one
	does, so docstatus is not filtered.
	"""

	orders = set()
	for doctype in ORDER_DOCTYPES:
		order_doctype = doctype.removesuffix(" Item")
		name_field = "parent" if doctype.endswith(" Item") else "name"
		for filters in get_dimension_filters(doctype, dimension_names):
			orders.update(
				(order_doctype, name)
				for name in frappe.get_all(doctype, filters=filters, pluck=name_field, limit=5)
			)

	return sorted(orders)


def get_dimension_names(manifest: str) -> dict:
	"""The manifest dimension record names, keyed by accounting dimension fieldname"""

	return {
		fieldname: frappe.get_all(doctype, filters={"manifest": manifest}, pluck="name")
		for doctype, fieldname in DIMENSIONS.items()
	}


def get_dimension_filters(doctype: str, dimension_names: dict) -> list:
	"""One filter set per ICD dimension field that doctype actually carries

	The fields only exist once create_icd_accounting_dimensions has run, and until then
	nothing can reference them either.
	"""

	return [
		{fieldname: ["in", names]}
		for fieldname, names in dimension_names.items()
		if names and frappe.db.has_column(doctype, fieldname)
	]


def revoke_dimension_records(manifest: str):
	"""Drop the dimension records of a cancelled manifest, the amendment creates its own set

	ICD Container is deleted first, it links to ICD Master BL. delete_doc is kept over a
	bulk delete so a draft document still holding a record fails loudly.
	"""

	for doctype in DIMENSIONS:
		for name in frappe.get_all(doctype, filters={"manifest": manifest}, pluck="name"):
			frappe.delete_doc(doctype, name, ignore_permissions=True, delete_permanently=True)


def add_accounting_dimension(document_type: str):
	"""Register one dimension and create its fields now, shared by the dimension patches"""

	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		make_dimension_in_accounting_doctypes,
	)

	if frappe.db.exists("Accounting Dimension", {"document_type": document_type}):
		return

	dimension = frappe.new_doc("Accounting Dimension")
	dimension.document_type = document_type
	dimension.flags.ignore_permissions = True
	dimension.insert()

	# on_update only queues the field creation, run it here so the fields exist once the patch ends
	make_dimension_in_accounting_doctypes(doc=dimension)

	print(f"Added the {document_type} accounting dimension, field: {dimension.fieldname}")
