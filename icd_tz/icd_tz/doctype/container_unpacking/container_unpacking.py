# Copyright (c) 2026, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from frappe.utils import cint, flt, get_link_to_form, nowdate

from icd_tz.icd_tz.api.icd_services import BOOKING, RECEPTION, get_scope_services
from icd_tz.icd_tz.api.port_expenses import get_cargo_type
from icd_tz.icd_tz.api.utils import validate_delivered_container, validate_delivered_containers
from icd_tz.icd_tz.doctype.container_reception.container_reception import get_destination_details

# house bill number the ICD gives cargo the manifest lists under no house bill
INTERNAL_HBL_PREFIX = "ICD-HBL-"

# records that bind a container's charges: doctype -> (form doctype, name field)
LINKED_RECORDS = {
	"In Yard Container Booking": ("In Yard Container Booking", "name"),
	"Container Inspection": ("Container Inspection", "name"),
	"Service Order": ("Service Order", "name"),
	"Gate Pass": ("Gate Pass", "name"),
	"Waiver Request Item": ("Waiver Request", "parent"),
	"Sales Order Item": ("Sales Order", "parent"),
	"Sales Invoice Item": ("Sales Invoice", "parent"),
}

# Container field -> its field on the manifest's HBL Container and Containers Detail rows
CARGO_FIELDS = {
	"size": "container_size",
	"type_of_container": "type_of_container",
	"freight_indicator": "freight_indicator",
	"seal_no_1": "seal_no1",
	"seal_no_2": "seal_no2",
	"seal_no_3": "seal_no3",
	"no_of_packages": "no_of_packages",
	"package_unit": "package_unit",
	"volume": "volume",
	"volume_unit": "volume_unit",
	"weight": "weight",
	"weight_unit": "weight_unit",
	"plug_type_of_reefer": "plug_type_of_reefer",
	"minimum_temperature": "minimum_temperature",
	"maximum_temperature": "maximum_temperature",
}


class ContainerUnpacking(Document):
	"""Cargo of an LCL container counted per house bill, leaving the container empty"""

	def before_validate(self):
		if self.container_id and not self.hbls:
			self.set_hbls()

	def validate(self):
		self.validate_container()
		self.validate_duplicate_unpacking()

		for row in self.hbls:
			row.set_package_difference()

	def before_submit(self):
		self.validate_gross_volumes()
		self.posting_date = nowdate()
		validate_no_linked_records([self.container_id], action="unpacked")

		for row in self.hbls:
			if row.is_internal_hbl and not row.h_bl_no:
				row.h_bl_no = INTERNAL_HBL_PREFIX + getseries(INTERNAL_HBL_PREFIX, 4)

	def on_submit(self):
		reception = frappe.get_doc("Container Reception", self.container_reception)
		for row in self.hbls:
			row.db_set("container_id", self.make_hbl_container(reception, row))

		self.set_container_empty()

		frappe.msgprint(
			_("HBL records: {0} were created for container {1}").format(
				len(self.hbls), frappe.bold(self.container_no)
			),
			alert=True,
		)

	def before_cancel(self):
		validate_delivered_containers(self.hbl_container_ids)
		validate_no_linked_records(self.hbl_container_ids, action="cancelled")

	def on_cancel(self):
		for row in self.hbls:
			if not row.container_id:
				continue

			# delete refuses a record any document links to, cancelled or not
			container_id = row.container_id
			row.db_set("container_id", None)
			frappe.delete_doc("Container", container_id, ignore_permissions=True)

		self.restore_container()

	@property
	def hbl_container_ids(self) -> list:
		return [row.container_id for row in self.hbls if row.container_id]

	@frappe.whitelist()
	def set_hbls(self):
		"""HBL rows from the manifest, one per house bill, or one per bill of a box with no house bills"""

		container = frappe.db.get_value(
			"Container", self.container_id, ["manifest", "container_no", "m_bl_no"], as_dict=True
		)
		self.set("hbls", get_hbl_rows(container))

	def validate_container(self):
		# locked on submit, so two unpackings of one box cannot both find it full
		container = frappe.db.get_value(
			"Container",
			self.container_id,
			["has_hbl", "freight_indicator", "is_empty_container"],
			as_dict=True,
			for_update=self.docstatus == 1,
		)
		if container.has_hbl or container.freight_indicator != "LCL":
			frappe.throw(
				_("Only an LCL container received under its M BL can be unpacked, {0} is not one").format(
					frappe.bold(self.container_id)
				),
				title=_("Not An LCL Container"),
			)

		if container.is_empty_container:
			frappe.throw(
				_("Container {0} is already empty").format(frappe.bold(self.container_no)),
				title=_("Already Unpacked"),
			)

		validate_delivered_container(self.container_id, self.container_no, action="unpacked")

	def validate_duplicate_unpacking(self):
		duplicate = frappe.db.get_value(
			"Container Unpacking",
			{"container_id": self.container_id, "docstatus": ["<", 2], "name": ["!=", self.name or ""]},
		)
		if duplicate:
			frappe.throw(
				_("Container {0} is already unpacked on {1}").format(
					frappe.bold(self.container_no), get_link_to_form("Container Unpacking", duplicate)
				),
				title=_("Duplicate Unpacking"),
			)

	def validate_gross_volumes(self):
		"""LCL cargo is billed by volume, so a bill with no manifest CBM needs the consolidator's"""

		missing = [row.h_bl_no or row.m_bl_no for row in self.hbls if not row.gross_volume]
		if missing:
			frappe.throw(
				_("Set the Consolidator CBM of these bills, the manifest gives them none: {0}").format(
					frappe.bold(", ".join(missing))
				),
				title=_("Gross Volume Missing"),
			)

	def make_hbl_container(self, reception, row) -> str:
		container = reception.new_container()
		container.update(self.get_hbl_details(row))
		container.current_location = row.location or container.current_location
		container.update_container_stay()

		# insert copies the manifest volume over, the row may carry the consolidator's
		container.db_set("gross_volume", row.gross_volume, update_modified=False)

		return container.name

	def get_hbl_details(self, row) -> dict:
		filters = {"parent": self.manifest, "container_no": self.container_no, "m_bl_no": row.m_bl_no}
		if row.is_internal_hbl:
			details = {
				**get_cargo_details("Containers Detail", filters),
				**get_internal_bill_details(self.manifest, self.container_no, row.m_bl_no),
			}
		else:
			details = get_cargo_details("HBL Container", {**filters, "h_bl_no": row.h_bl_no})

		return {**details, "has_hbl": 1, "h_bl_no": row.h_bl_no, "m_bl_no": row.m_bl_no, "container_count": 1}

	def set_container_empty(self):
		"""The box restarts storage on the posting date and owes nothing else

		Removal and corridor levy follow is_empty_container on save, the rest is cleared here.
		"""

		container = frappe.get_doc("Container", self.container_id)
		container.update({"is_empty_container": 1, "unpack_date": self.posting_date})
		for scope in (RECEPTION, BOOKING):
			for service in get_scope_services(scope):
				container.set(service.flag_field, 0)

		container.reset_container_dates()
		container.update_container_stay()

	def restore_container(self):
		"""The box holds its cargo again, as it was received"""

		container = frappe.get_doc("Container", self.container_id)
		container.update({"is_empty_container": 0, "unpack_date": None})
		container.set_reception_charge_flags()
		container.reset_container_dates()
		container.update_container_stay()


def validate_no_linked_records(container_ids: list, action: str):
	"""Bookings, orders and invoices hold on to the records the unpacking creates or empties"""

	records = []
	for doctype, (form_doctype, name_field) in LINKED_RECORDS.items():
		names = frappe.get_all(
			doctype,
			filters={"container_id": ["in", container_ids], "docstatus": ["<", 2]},
			pluck=name_field,
			distinct=True,
		)
		records += [get_link_to_form(form_doctype, name) for name in names]

	if records:
		frappe.throw(
			_("Cancel these documents first, the unpacking cannot be {0} while they exist: {1}").format(
				action, ", ".join(records)
			),
			title=_("Linked Documents Exist"),
		)


def get_hbl_rows(container) -> list:
	house_bills = frappe.get_all(
		"HBL Container",
		filters={
			"parent": container.manifest,
			"container_no": container.container_no,
			"m_bl_no": container.m_bl_no,
		},
		fields=["m_bl_no", "h_bl_no", "no_of_packages", "package_unit"],
		order_by="idx",
	)
	if house_bills:
		bills = get_bills("House BL", "h_bl_no", "description_of_goods", container.manifest, house_bills)
		return [make_hbl_row(row, bills.get(row.h_bl_no), h_bl_no=row.h_bl_no) for row in house_bills]

	rows = get_bill_rows(container)
	bills = get_bills("Master BL", "m_bl_no", "cargo_description", container.manifest, rows)
	return [make_hbl_row(row, bills.get(row.m_bl_no), is_internal_hbl=1) for row in rows]


def get_bill_rows(container) -> list:
	"""Containers Detail rows of the box, one per bill it is listed under"""

	rows = {}
	for row in frappe.get_all(
		"Containers Detail",
		filters={"parent": container.manifest, "container_no": container.container_no},
		fields=["m_bl_no", "no_of_packages", "package_unit"],
		order_by="idx",
	):
		# a box repeated under the same bill is still one consignee's cargo
		rows.setdefault(row.m_bl_no, row)

	return list(rows.values())


def get_bills(doctype: str, bill_field: str, description_field: str, manifest: str, rows: list) -> dict:
	"""House BL or Master BL sheet rows of the manifest, by bill number"""

	bills = frappe.get_all(
		doctype,
		filters={"parent": manifest, bill_field: ["in", [row.get(bill_field) for row in rows]]},
		fields=[
			bill_field,
			"consignee_name",
			f"{description_field} as cargo_description",
			"number_of_package",
			"gross_volume",
			"gross_volume_unit",
		],
	)

	return {bill.get(bill_field): bill for bill in bills}


def make_hbl_row(row, bill, **values) -> dict:
	bill = bill or frappe._dict()
	packages = cint(bill.number_of_package or row.no_of_packages)

	return {
		"m_bl_no": row.m_bl_no,
		"consignee": bill.consignee_name,
		"cargo_description": bill.cargo_description,
		"manifest_packages": packages,
		"counted_packages": packages,
		"package_unit": row.package_unit,
		"manifest_gross_volume": flt(bill.gross_volume),
		"gross_volume_unit": bill.gross_volume_unit,
		**values,
	}


def get_cargo_details(doctype: str, filters: dict) -> dict:
	"""Container fields of one bill's cargo, from its HBL Container or Containers Detail row"""

	row = frappe.db.get_value(doctype, filters, list(CARGO_FIELDS.values()), as_dict=True, order_by="idx")

	return {field: row.get(source) for field, source in CARGO_FIELDS.items()}


def get_internal_bill_details(manifest: str, container_no: str, m_bl_no: str) -> dict:
	"""Cargo type and destination of a bill the manifest gives no house bills"""

	master_bl = frappe.db.get_value(
		"Master BL",
		{"parent": manifest, "m_bl_no": m_bl_no},
		["cargo_classification", "place_of_destination"],
		as_dict=True,
	)
	if not master_bl:
		frappe.throw(
			_("Bill {0} of container {1} is not on the Master BL sheet of manifest {2}").format(
				frappe.bold(m_bl_no), frappe.bold(container_no), frappe.bold(manifest)
			),
			title=_("Master BL Missing"),
		)

	return {
		"cargo_type": get_cargo_type(master_bl.cargo_classification),
		**get_destination_details(master_bl.place_of_destination),
	}
