import frappe


def execute():
	"""Move the ICD Setting values left in tabSingles to the record of one company

	The rename patch kept the Single values, and the child rows kept the old Single name as
	parent. Child rows keep their names and order, only their parent changes. The old WIP and
	COGS accounts go to the migration output, because the accounts are now set on the items.
	"""

	values = frappe.db.get_singles_dict("ICD Setting")
	if not values:
		return

	company = get_company(values.get("wip_account"))
	if frappe.db.exists("ICD Setting", {"company": company}):
		print(f"ICD Setting: {company} has a record already, the old settings values were not moved")
		return

	settings_doc = create_company_record(company, values)
	move_child_rows(settings_doc.name)
	print_old_accounts(values)

	frappe.db.delete("Singles", {"doctype": "ICD Setting"})
	frappe.clear_cache(doctype="ICD Setting")


def get_company(wip_account: str | None) -> str:
	company = (wip_account and frappe.db.get_value("Account", wip_account, "company")) or (
		frappe.db.get_single_value("Global Defaults", "default_company")
	)
	if not company:
		frappe.throw(
			"ICD Setting: set a Default Company in Global Defaults, so the settings can move to its record"
		)

	return company


def create_company_record(company: str, values: dict):
	"""The child rows move by query, so only the mandatory check would stop old values"""

	meta = frappe.get_meta("ICD Setting")
	settings_doc = frappe.new_doc("ICD Setting")
	settings_doc.update({field: value for field, value in values.items() if meta.has_field(field)})
	settings_doc.company = company
	settings_doc.flags.ignore_mandatory = True
	settings_doc.insert(ignore_permissions=True, ignore_links=True)
	return settings_doc


def move_child_rows(new_parent: str):
	for df in frappe.get_meta("ICD Setting").get_table_fields():
		child = frappe.qb.DocType(df.options)
		(
			frappe.qb.update(child)
			.set(child.parent, new_parent)
			.where(
				(child.parenttype == "ICD Setting")
				& (child.parentfield == df.fieldname)
				& (child.parent == "ICD TZ Settings")
			)
		).run()


def print_old_accounts(values: dict):
	accounts = [
		f"  {label}: {values[field]}"
		for field, label in (("wip_account", "WIP Account"), ("cogs_account", "COGS Account"))
		if values.get(field)
	]
	if accounts:
		print("ICD Setting: set these accounts on the Item Defaults of the container expense items:")
		print("\n".join(accounts))
