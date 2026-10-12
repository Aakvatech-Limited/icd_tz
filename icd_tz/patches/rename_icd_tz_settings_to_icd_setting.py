import frappe


def execute():
	"""Rename ICD TZ Settings to ICD Setting before the model sync makes it a company record

	rename_doc moves the tabSingles values, the child row parenttype, the Link options and
	the workspace link. The values stay in tabSingles until the company record patch moves them.
	rename_field needs the synced meta, so the renamed field is moved by query.
	"""

	if not frappe.db.exists("DocType", "ICD TZ Settings"):
		return

	frappe.rename_doc(
		"DocType", "ICD TZ Settings", "ICD Setting", force=True, show_alert=False, rebuild_search=False
	)

	singles = frappe.qb.DocType("Singles")
	(
		frappe.qb.update(singles)
		.set(singles.field, "enable_wip_and_cogs_for_expenses")
		.where((singles.doctype == "ICD Setting") & (singles.field == "enable_wip_for_expenses"))
	).run()
