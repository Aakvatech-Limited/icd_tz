import frappe
from frappe.utils import getdate


def execute():
	"""Backfill Container.gate_out_date from the Gate Pass of each delivered container"""

	gate_pass = frappe.qb.DocType("Gate Pass")

	gate_passes = (
		frappe.qb.from_(gate_pass)
		.select(
			gate_pass.container_id,
			gate_pass.gate_out_date,
			gate_pass.submitted_date,
		)
		.where(gate_pass.docstatus == 1)
		.where(gate_pass.container_id.isnotnull())
		.orderby(gate_pass.submitted_date)
	).run(as_dict=True)

	count = 0
	for row in gate_passes:
		# gate_out_date is only stamped by the workflow, fall back to the submitted date
		gate_out_date = row.gate_out_date or row.submitted_date
		if not gate_out_date:
			continue

		if frappe.db.get_value("Container", row.container_id, "gate_out_date"):
			continue

		frappe.db.set_value(
			"Container", row.container_id, "gate_out_date", getdate(gate_out_date), update_modified=False
		)
		count += 1

	print(f"Backfilled Gate Out Date on {count} Container(s)")
