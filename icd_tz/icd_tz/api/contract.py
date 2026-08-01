import frappe
from frappe import _


def validate(doc, method):
	if doc.party_type == "Clearing and Forwarding Company" and doc.party_name:
		if not doc.start_date or not doc.end_date:
			frappe.throw(
				_("Start Date and End Date are mandatory for Clearing and Forwarding Company Contracts")
			)

		contract = frappe.qb.DocType("Contract")
		query = (
			frappe.qb.from_(contract)
			.select(contract.name)
			.where(
				(contract.party_type == "Clearing and Forwarding Company")
				& (contract.party_name == doc.party_name)
				& (contract.name != (doc.name or ""))
				& (contract.docstatus != 2)
				& (contract.start_date <= doc.end_date)
				& (contract.end_date >= doc.start_date)
			)
		)
		overlapping_contracts = query.run()

		if overlapping_contracts:
			frappe.throw(
				_(
					"There is already a contract for this company overlapping with this period: <b>{0}</b>"
				).format(overlapping_contracts[0][0])
			)
