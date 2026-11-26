from collections import defaultdict

import frappe
from frappe.utils import create_batch

from icd_tz.icd_tz.doctype.container.container import get_cargo_category


def execute():
	"""Fill the IMDG Code and reefer plug of every container not Delivered, then their Cargo Category"""

	containers = frappe.get_all(
		"Container",
		filters={"status": ["!=", "Delivered"]},
		fields=["name", "manifest", "m_bl_no", "h_bl_no", "has_hbl", "container_no", "plug_type_of_reefer"],
	)
	master_codes = get_imdg_codes("Master BL", "m_bl_no")
	house_codes = get_imdg_codes("House BL", "h_bl_no")

	updates = defaultdict(lambda: defaultdict(list))
	for container in containers:
		container.imdg_code = house_codes.get((container.manifest, container.h_bl_no)) or master_codes.get(
			(container.manifest, container.m_bl_no)
		)
		if container.imdg_code:
			updates["imdg_code"][container.imdg_code].append(container.name)

		if not container.has_hbl and not container.plug_type_of_reefer:
			container.plug_type_of_reefer = frappe.db.get_value(
				"Containers Detail",
				{"parent": container.manifest, "container_no": container.container_no},
				"plug_type_of_reefer",
			)
			if container.plug_type_of_reefer:
				updates["plug_type_of_reefer"][container.plug_type_of_reefer].append(container.name)

		updates["cargo_category"][get_cargo_category(container)].append(container.name)

	for field, names_by_value in updates.items():
		set_in_batches(field, names_by_value)


def get_imdg_codes(doctype: str, bill_field: str) -> dict:
	"""IMDG Code of each bill of lading that carries dangerous goods, by manifest and bill number"""

	rows = frappe.get_all(
		doctype, filters={"imdg_code": ["is", "set"]}, fields=["parent", bill_field, "imdg_code"]
	)
	return {(row.parent, row[bill_field]): row.imdg_code.strip() for row in rows if row.imdg_code.strip()}


def set_in_batches(field: str, names_by_value: dict):
	table = frappe.qb.DocType("Container")
	for value, names in names_by_value.items():
		for batch in create_batch(names, 1000):
			frappe.qb.update(table).set(table[field], value).where(table.name.isin(batch)).run()
