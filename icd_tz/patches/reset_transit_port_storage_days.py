import frappe
from frappe.utils import create_batch

from icd_tz.icd_tz.doctype.icd_container.icd_container import (
	BATCH_SIZE,
	get_bill_cargo_types,
	get_containers_for_storage_days,
)


def execute():
	"""Drop the unbilled day rows of Transit containers still at the port

	They were counted on the Local bands. The next update_port_storage_days run counts
	them again on the Transit bands. A day on a Purchase Order is kept as billed.
	"""

	for batch in create_batch(get_transit_container_names(), BATCH_SIZE):
		table = frappe.qb.DocType("ICD Container Storage Date")
		(
			frappe.qb.from_(table)
			.delete()
			.where(table.parenttype == "ICD Container")
			.where(table.parent.isin(batch))
			.where(table.purchase_order.isnull() | (table.purchase_order == ""))
		).run()


def get_transit_container_names() -> list:
	"""Containers the scheduled run still counts whose bill of lading is Transit"""

	containers = get_containers_for_storage_days()
	cargo_types = get_bill_cargo_types({container.master_bl for container in containers})

	return [container.name for container in containers if cargo_types.get(container.master_bl) == "Transit"]
