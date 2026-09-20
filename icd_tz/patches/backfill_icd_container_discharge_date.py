import frappe


def execute():
	"""Backfill ICD Container.ship_dc_date from the operational Container

	Resolves the containers already received for free and leaves the TANeSW job
	only the boxes still at the port.
	"""

	icd_container = frappe.qb.DocType("ICD Container")
	container = frappe.qb.DocType("Container")

	rows = (
		frappe.qb.from_(icd_container)
		.inner_join(container)
		.on(
			(container.manifest == icd_container.manifest)
			& (container.container_no == icd_container.container_no)
		)
		.select(icd_container.name, container.ship_dc_date)
		.where(icd_container.ship_dc_date.isnull())
		.where(container.ship_dc_date.isnotnull())
	).run(as_dict=True)

	for row in rows:
		frappe.db.set_value(
			"ICD Container", row.name, "ship_dc_date", row.ship_dc_date, update_modified=False
		)

	print(f"Backfilled Ship Discharge Date on {len(rows)} ICD Container(s)")
