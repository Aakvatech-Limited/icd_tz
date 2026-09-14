import frappe

WORKSPACE = "ICD"
OLD_LINK = "EDI Settings"
NEW_LINK = "EDI Partner"


def execute():
	"""Repoint the ICD workspace link that still names the retired EDI Settings Single.

	A workspace renders no cards at all when one of its links names a doctype
	that does not exist, so the whole page comes up empty. Syncing the workspace
	file does not fix an existing site, because Frappe leaves a workspace that is
	already in the database alone.
	"""

	link = frappe.db.get_value("Workspace Link", {"parent": WORKSPACE, "link_to": OLD_LINK})
	if not link:
		return

	if frappe.db.exists("DocType", NEW_LINK):
		frappe.db.set_value("Workspace Link", link, {"label": NEW_LINK, "link_to": NEW_LINK})
		print(f"Repointed the {WORKSPACE} workspace link from {OLD_LINK} to {NEW_LINK}")
	else:
		frappe.db.delete("Workspace Link", {"name": link})
		print(f"Removed the {WORKSPACE} workspace link to the retired {OLD_LINK}")

	frappe.clear_cache()
