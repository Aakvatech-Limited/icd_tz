import frappe


def execute():
	"""Give every EDI Partner the company of the ICD Setting, then name it {shipping_line_code}-{abbr}

	rename_doc moves every link to the new name. The partner settings do not change.
	"""

	partners = frappe.get_all("EDI Partner", fields=["name", "shipping_line_code", "company"])
	if any(not partner.company for partner in partners):
		company = get_only_icd_company()
		for partner in partners:
			if not partner.company:
				frappe.db.set_value("EDI Partner", partner.name, "company", company, update_modified=False)
				partner.company = company

	for partner in partners:
		abbr = frappe.get_cached_value("Company", partner.company, "abbr")
		frappe.db.set_value("EDI Partner", partner.name, "abbr", abbr, update_modified=False)

		new_name = f"{partner.shipping_line_code}-{abbr}"
		if partner.name != new_name:
			frappe.rename_doc("EDI Partner", partner.name, new_name, force=True, show_alert=False)
			print(f"EDI Partner: renamed {partner.name} to {new_name}")


def get_only_icd_company() -> str:
	companies = frappe.get_all("ICD Setting", pluck="company")
	if len(companies) != 1:
		frappe.throw(
			f"EDI Partner: found {len(companies)} ICD Setting records, so the company of the existing "
			"partners is not known. Set the Company on each EDI Partner, then run the migration again."
		)

	return companies[0]
