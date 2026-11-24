"""Port charges only for boxes that are still ours ("Check Port Charges Against TANeSW" in TANeSW Settings).

icd_tz raises port charges (Purchase Order / Purchase Invoice lines per ICD Container) from the ERP Manifest, on the day
it is uploaded: a Movement Order cannot be made until the box's port charges are on an order. A box TANeSW later moves
to another ICD keeps its ICD Container record, so it stays chargeable to us: diverted boxes
are typically already on the terminal's invoice, raised the day the Manifest was uploaded.

  on save   (validate):      lines for boxes already recorded as gone are listed as a warning, and a vessel whose
                             last comparison is older than FRESH_MINUTES is queued for a background re-read;
  on submit (before_submit): lines for boxes recorded as no longer ours stop the submit ("Block") or are only
                             reported ("Warn"). The submit never calls TANeSW: it uses what the manifest sync and
                             the background re-read recorded, and says how old that is when it is stale.
icd_tz's own hooks on these documents are untouched; this one runs beside them.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from tanesw_integration.hints import Scalar
from tanesw_integration.outage import log_error as _outage_log_error

SETTINGS = "TANeSW Settings"
FRESH_MINUTES = 30


def check_document(doc, method=None):
	s = frappe.get_single(SETTINGS)
	if not cint(s.get("check_port_charges")):
		return
	lines = container_lines(doc)
	if not lines:
		return
	submitting = method == "before_submit"
	manifests = {m for _i, m, _c in lines}
	if cint(s.enable_manifest_sync):
		stale = stale_manifests(manifests)
		if stale and not submitting:
			queue_refresh(stale)
		elif stale:
			frappe.msgprint(
				_(
					"TANeSW has not been re-checked for {0} in the last {1} minutes; the last recorded check "
					"was used."
				).format(", ".join(sorted(stale)), FRESH_MINUTES),
				indicator="orange",
			)
	bad = not_ours(lines)
	if not bad:
		return
	table = "".join(
		f"<tr><td>{i}</td><td>{frappe.utils.escape_html(c)}</td><td>{frappe.utils.escape_html(w)}</td></tr>"
		for i, c, w in bad
	)
	msg = _(
		"These lines charge us for boxes TANeSW no longer allocates to us. Remove them, or the port charges of "
		"another ICD's boxes are paid by us:"
	) + (
		"<table class='table table-bordered' style='margin-top:8px'>"
		f"<tr><th>{_('Row')}</th><th>{_('Container')}</th><th>{_('Went To')}</th></tr>{table}</table>"
	)
	if submitting and (s.get("port_charge_check_mode") or "Block") == "Block":
		frappe.throw(msg, title=_("Port charges for boxes that are not ours"))
	frappe.msgprint(msg, title=_("Port charges for boxes that are not ours"), indicator="orange")


@frappe.whitelist(methods=["POST"])
def precheck(manifest: Scalar):
	"""The boxes on this Manifest that TANeSW no longer allocates to us but icd_tz can still charge (they have an ICD
	Container), for the warning on the Manifest form (public/js/manifest_tanesw.js). icd_tz's own pages and scripts
	are not touched (PR #714 review, item 18): the warning sits on the form where port expense orders are started."""
	from tanesw_integration.manifest_sync import BACK, LOG

	frappe.has_permission("Manifest", "read", manifest, throw=True)
	s = frappe.get_single(SETTINGS)
	if not cint(s.get("check_port_charges")):
		return {"enabled": 0}
	note = None
	if cint(s.enable_manifest_sync) and stale_manifests({manifest}):
		queue_refresh(
			{manifest}
		)  # never make the user wait on TANeSW; the list below is the last recorded check
		note = _(
			"TANeSW is being re-checked for this vessel in the background; this list is the last recorded check."
		)
	mrn = frappe.db.get_value("Manifest", manifest, "mrn")
	gone = []
	for r in frappe.get_all(
		LOG,
		filters={"mrn": mrn, "change_type": "Removed", "outcome": ["!=", BACK]},
		fields=["container_no", "new_place", "carried_in_at"],
		order_by="container_no",
	):
		box = frappe.db.get_value(
			"ICD Container",
			{"manifest": manifest, "container_no": r.container_no},
			["name", "purchase_order"],
			as_dict=True,
		)
		if not box:
			continue  # not chargeable on this Manifest
		gone.append(
			{
				"container_no": r.container_no,
				"went_to": r.new_place or r.carried_in_at or _("not traced yet"),
				"ordered": box.purchase_order,
			}
		)
	return {
		"enabled": 1,
		"gone": gone,
		"note": note,
		"blocking": (s.get("port_charge_check_mode") or "Block") == "Block",
	}


def container_lines(doc):
	"""[(row idx, manifest, container_no)] for every line that names a box (one-off charges and storage days)."""
	out = []
	for item in doc.get("items") or []:
		names = set()
		if item.get("icd_container"):
			names.add(item.icd_container)
		for ref in (item.get("container_child_refs") or "").split(","):
			if ref:
				parent = frappe.db.get_value("ICD Container Storage Date", ref, "parent")
				if parent:
					names.add(parent)
		for name in names:
			box = frappe.db.get_value("ICD Container", name, ["manifest", "container_no"], as_dict=True)
			if box and box.manifest and box.container_no:
				out.append((item.idx, box.manifest, box.container_no.upper()))
	return out


def not_ours(lines):
	"""Lines whose box TANeSW Manifest Sync recorded as gone from our allocation (and not back)."""
	from tanesw_integration.manifest_sync import BACK, LOG

	mrns = {m: frappe.db.get_value("Manifest", m, "mrn") for m in {m for _i, m, _c in lines}}
	bad = []
	for idx, manifest, cntr in lines:
		mrn = mrns.get(manifest)
		if not mrn:
			continue
		gone = frappe.db.get_value(
			LOG,
			{"mrn": mrn, "container_no": cntr, "change_type": "Removed", "outcome": ["!=", BACK]},
			["new_place", "carried_in_at"],
			as_dict=True,
		)
		if gone:
			bad.append((idx, cntr, gone.new_place or gone.carried_in_at or _("not traced yet")))
	return bad


def stale_manifests(manifests):
	"""The manifests whose vessel was not compared with TANeSW in the last FRESH_MINUTES."""
	stale_before = add_to_date(now_datetime(), minutes=-FRESH_MINUTES)
	out = set()
	for manifest in manifests:
		mrn = frappe.db.get_value("Manifest", manifest, "mrn")
		if not mrn:
			continue
		synced = frappe.db.get_value("TANeSW Vessel Allocation", mrn, "manifest_synced_on")
		if not synced or get_datetime(synced) <= stale_before:
			out.add(manifest)
	return out


def queue_refresh(manifests):
	"""Re-read these vessels from TANeSW in a background job, once per set (a second save does not queue it again)."""
	names = sorted(manifests)
	frappe.enqueue(
		"tanesw_integration.port_charge_check.refresh_in_background",
		manifests=names,
		queue="short",
		job_id="tanesw-port-charge-refresh-" + "-".join(names)[:100],
		deduplicate=True,
		enqueue_after_commit=True,
	)


def refresh_in_background(manifests):
	refresh(set(manifests), frappe.get_single(SETTINGS))


def refresh(manifests, s):
	"""Re-read each vessel from TANeSW unless it was compared within FRESH_MINUTES."""
	from tanesw_integration import manifest_sync as ms
	from tanesw_integration import outage

	if outage.paused():  # TANeSW is down: do not make the user wait for it on every submit
		frappe.msgprint(_("TANeSW is not responding; the last recorded check was used."), indicator="orange")
		return
	stale_before = add_to_date(now_datetime(), minutes=-FRESH_MINUTES)
	for manifest in manifests:
		mrn = frappe.db.get_value("Manifest", manifest, "mrn")
		if not mrn:
			continue
		synced = frappe.db.get_value("TANeSW Vessel Allocation", mrn, "manifest_synced_on")
		if synced and get_datetime(synced) > stale_before:
			continue
		try:
			with ms._watcher(s) as account:
				if not account:
					raise frappe.ValidationError("no TANeSW watcher account could log in")
				ms.sync_vessel(mrn, s, ms._new_stats(), {"traces": 10})
				ms._mark_synced(mrn)
		except Exception as e:
			frappe.clear_messages()
			_outage_log_error(
				title=f"TANeSW port-charge re-check failed: {mrn}", message=frappe.get_traceback()
			)
			frappe.msgprint(
				_(
					"TANeSW could not be reached to re-check {0} ({1}); the last recorded check was used."
				).format(manifest, frappe.utils.escape_html(str(e))[:120]),
				indicator="orange",
			)
