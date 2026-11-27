"""Best Pick orders made BEFORE the manifest is known: Ops creates the Movement Order with transporter, driver, truck
and trailer before the driver goes to the port; the manifest, container and B/L are filled in once TANeSW's handover
says which box that truck took (icd_link.find_or_fill_order).

icd_tz's code is not touched. Its Movement Order already does every manifest check only once a container is set, which
is exactly the fill. What stands in the way are field settings, changed here the way Frappe allows on any site
(Property Setters):
  - manifest: required only when Best Pick is NOT ticked;
  - manifest, ship, port, voyage_no, company: may be set after submit (they come with the manifest).
A guard (validate_manifest_change) keeps that narrow: on a submitted order the manifest can only go from empty to
filled, on a Best Pick order, together with the container. It cannot be changed or removed afterwards.

Switched on and off with "Allow Best Pick Orders Without Manifest" in TANeSW Settings.
"""

import frappe
from frappe import _
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

CMO = "Container Movement Order"
FILLED_WITH_MANIFEST = ("manifest", "ship", "port", "voyage_no", "company")
TAG = "tanesw_best_pick_without_manifest"  # marks our property setters so they can be removed again


def _setters():
	yield "manifest", "reqd", "0", "Check"
	yield "manifest", "mandatory_depends_on", "eval:!doc.best_pick", "Code"
	for f in FILLED_WITH_MANIFEST:
		yield f, "allow_on_submit", "1", "Check"


def apply(on):
	if "icd_tz" not in frappe.get_installed_apps():
		return
	for field, prop, value, ptype in _setters():
		name = f"{CMO}-{field}-{prop}"
		if on:
			make_property_setter(CMO, field, prop, value, ptype, validate_fields_for_doctype=False)
			frappe.db.set_value("Property Setter", name, "module", None)
			frappe.db.set_value("Property Setter", name, "default_value", TAG)  # our marker
		elif frappe.db.get_value("Property Setter", name, "default_value") == TAG:
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype=CMO)


def enabled():
	return bool(frappe.db.get_single_value("TANeSW Settings", "best_pick_without_manifest"))


def validate_manifest_change(doc, method=None):
	"""doc_events hook on Container Movement Order (before_update_after_submit).

	The Property Setters make manifest, ship, port, voyage and company editable after submit for the whole site, so
	this guard narrows it back down (PR #714 review, item 13): those fields of a submitted order change ONLY through the
	app's own Best Pick fill (icd_link.find_or_fill_order), only from empty to filled, only on a Best Pick order, and
	only together with its container. Nobody can change them by hand, whatever their role."""
	before = doc.get_doc_before_save()
	if not before or all(before.get(f) == doc.get(f) for f in FILLED_WITH_MANIFEST):
		return
	filling = (
		frappe.flags.tanesw_best_pick_fill
		and doc.best_pick
		and not before.manifest
		and doc.manifest
		and doc.container_no
		and not before.container_no
	)
	if not filling:
		frappe.throw(
			_(
				"The Manifest, ship, port, voyage and company of a submitted Movement Order cannot be changed. "
				"They are filled once, by the TANeSW link, on a Best Pick order made without a manifest, when its "
				"container is known."
			),
			title=_("Best Pick"),
		)
