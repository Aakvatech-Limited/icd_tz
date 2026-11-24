import frappe

ROLE = "TANeSW User"
# who receives allocation / ready-to-declare EMAILS (bell notifications still reach every TANeSW user)
OPS_ROLE = "TANeSW Operations"


def ensure_role():
	"""Role for warehouse operators: opens Cargo Management / Joint Inspection and the TANeSW records,
	reads TANeSW Settings, but cannot change settings or other people's TANeSW logins."""
	for role in (ROLE, OPS_ROLE):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def after_install():
	ensure_role()


def before_migrate():
	ensure_role()


def after_migrate():
	ensure_role()
	keep_reports_live()


def keep_reports_live():
	"""Frappe switches a slow report to 'Prepared Report' by itself, after which Export says 'No data to export'.
	Our reports carry disable_prepared_report_automation=1, but a report that was already switched stays switched
	after migrate: switch ours back on every migrate."""
	import frappe

	for name in frappe.get_all(
		"Report", filters={"module": "TANeSW Integration", "prepared_report": 1}, pluck="name"
	):
		frappe.db.set_value(
			"Report",
			name,
			{"prepared_report": 0, "disable_prepared_report_automation": 1},
			update_modified=False,
		)


def before_uninstall():
	"""Put icd_tz's form rules back as they were: remove every Property Setter this app made (Best Pick orders
	without a manifest, Manifest tables editable after submit), so nothing of ours stays behind on icd_tz."""
	from tanesw_integration import best_pick_setup, manifest_sync

	best_pick_setup.apply(False)
	manifest_sync.apply_setters(False)
	for tag in (best_pick_setup.TAG, manifest_sync.TAG):
		for name in frappe.get_all("Property Setter", filters={"default_value": tag}, pluck="name"):
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
