import frappe


def execute():
	"""Backfill Container.ship_dc_date from its Container Reception"""

	container = frappe.qb.DocType("Container")
	reception = frappe.qb.DocType("Container Reception")

	containers = (
		frappe.qb.from_(container)
		.inner_join(reception)
		.on(container.container_reception == reception.name)
		.select(container.name, reception.ship_dc_date)
		.where(container.ship_dc_date.isnull())
		.where(reception.ship_dc_date.isnotnull())
	).run(as_dict=True)

	for row in containers:
		frappe.db.set_value("Container", row.name, "ship_dc_date", row.ship_dc_date, update_modified=False)

	print(f"Backfilled Ship D/C Date on {len(containers)} Container(s)")
