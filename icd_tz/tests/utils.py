import frappe
from erpnext import get_default_company


def get_test_company() -> str:
	"""The company every ICD test record and its ICD Setting belong to"""

	company = get_default_company()
	if not company:
		frappe.throw("Set a Default Company in Global Defaults on the test site")

	return company


def get_test_icd_setting(company: str | None = None):
	"""The ICD Setting of the test company, created on first use"""

	company = company or get_test_company()
	name = frappe.db.get_value("ICD Setting", {"company": company})
	if name:
		return frappe.get_doc("ICD Setting", name)

	settings_doc = frappe.new_doc("ICD Setting")
	settings_doc.update({"company": company, "icd_code": "_TEST", "gate_pass_expiry_hours": 48})
	settings_doc.flags.ignore_mandatory = True
	settings_doc.insert(ignore_permissions=True)

	return settings_doc


def set_test_icd_setting(values: dict, company: str | None = None):
	"""Write values to the ICD Setting of the test company, so the next read sees them"""

	name = get_test_icd_setting(company).name
	frappe.db.set_value("ICD Setting", name, values)
	frappe.clear_document_cache("ICD Setting", name)


def set_item_accounts(
	item_code: str, wip_account: str | None, cogs_account: str | None, company: str | None = None
):
	"""Set the WIP and COGS Accounts of the item for the company, without the save checks"""

	company = company or get_test_company()
	row = frappe.db.get_value("Item Default", {"parenttype": "Item", "parent": item_code, "company": company})
	if row:
		frappe.db.set_value("Item Default", row, {"wip_account": wip_account, "cogs_account": cogs_account})
	else:
		item = frappe.get_doc("Item", item_code)
		item.append(
			"item_defaults", {"company": company, "wip_account": wip_account, "cogs_account": cogs_account}
		)
		item.db_update_all()

	frappe.clear_document_cache("Item", item_code)


def make_test_account(account_name: str, root_type: str, company: str | None = None) -> str:
	"""A ledger account of the test company under a group of the root type, created on first use"""

	company = company or get_test_company()
	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = f"{account_name} - {abbr}"
	if frappe.db.exists("Account", name):
		return name

	parent = frappe.db.get_value(
		"Account", {"company": company, "is_group": 1, "root_type": root_type}, "name", order_by="lft desc"
	)
	frappe.get_doc(
		{"doctype": "Account", "account_name": account_name, "parent_account": parent, "company": company}
	).insert(ignore_permissions=True)

	return name


def make_test_item(item_code: str) -> str:
	"""A non-stock Item, created on first use"""

	if not frappe.db.exists("Item", item_code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)

	return item_code


def get_company_without_setting() -> str | None:
	return frappe.db.get_value(
		"Company", {"name": ("not in", frappe.get_all("ICD Setting", pluck="company"))}, "name"
	)


def get_foreign_expense_account(company: str) -> str | None:
	"""An expense ledger of another company, for the checks that refuse one"""

	other_company = frappe.db.get_value("Company", {"name": ("!=", company)}, "name")
	return frappe.db.get_value(
		"Account", {"company": other_company, "is_group": 0, "root_type": "Expense"}, "name"
	)


def insert_purchase_order(name: str, docstatus: int = 1, flagged: int = 0, company: str | None = None) -> str:
	"""A bare Purchase Order row, enough for the container expense flag"""

	insert_row(
		"Purchase Order",
		{
			"name": name,
			"company": company or get_test_company(),
			"docstatus": docstatus,
			"supplier": "_Test Supplier",
			"is_icd_container_expense": flagged,
		},
	)

	return name


def skip_without_inspection_services(test_case):
	"""The data patches read the table of the removed inspection services, a new site has none"""

	if not frappe.db.table_exists("Container Inspection Detail"):
		test_case.skipTest("the site has no table of the removed inspection services")


def insert_inspection_service(container_id: str, service: str, docstatus: int = 1, **row) -> str:
	"""An inspection with one row of the removed services table, which the data patches read"""

	inspection = frappe.generate_hash(length=10)
	insert_row(
		"Container Inspection",
		{
			"name": inspection,
			"container_id": container_id,
			"company": get_test_company(),
			"docstatus": docstatus,
		},
	)
	insert_row(
		"Container Inspection Detail",
		{
			"name": frappe.generate_hash(length=10),
			"parent": inspection,
			"parenttype": "Container Inspection",
			"parentfield": "services",
			"service": service,
			"docstatus": docstatus,
			**row,
		},
	)

	return inspection


def insert_row(doctype: str, values: dict):
	"""A bare table row, without the document checks a test does not need"""

	table = frappe.qb.DocType(doctype)
	frappe.qb.into(table).columns(*values).insert(*values.values()).run()
