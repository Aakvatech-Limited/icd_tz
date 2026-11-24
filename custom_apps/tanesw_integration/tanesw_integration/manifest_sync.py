"""TANeSW allocation -> ERP Manifest, box by box ("Manifest Sync" section of TANeSW Settings).

What TANeSW holds today for a vessel is its MRN 'Excel Download' (026Q), the same workbook Ops upload. icd_tz's own
Manifest.extract_data_from_manifest_file() turns it into rows (diverted boxes are absent from it). So every run, per vessel:
  1. download the workbook and extract it into an unsaved Manifest ("fresh");
  2. no ERP Manifest yet and "Create ERP Manifest" on: save it (Draft, or Submitted when the port is known);
  3. compare fresh with what we knew (ERP Manifest boxes + boxes TANeSW Container saw on our B/Ls): each box that left
     or joined our allocation gets a TANeSW Allocation Change row, and a removed box is traced to where it went;
  4. "Apply TANeSW Changes" on: added boxes and B/Ls go onto the ERP Manifest; removed boxes with no Movement Order,
     Container or Reception come off it; removed boxes that already have one stay on it and are flagged for Ops.
icd_tz's code is not touched: its own import parses the file, documents are saved through their own controllers, and
the four Manifest tables become editable after submit through Property Setters (switched by the setting).
"""

import base64
import re
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, get_datetime, getdate, now_datetime, nowdate

from tanesw_integration.credentials import watcher_accounts
from tanesw_integration.hints import Scalar
from tanesw_integration.outage import log_error as _outage_log_error

SETTINGS = "TANeSW Settings"
LOG = "TANeSW Allocation Change"
JOB_ID = "tanesw_manifest_sync"
TABLES = ("containers", "hbl_containers", "master_bl", "house_bl")
TAG = "tanesw_manifest_sync"  # marks our Property Setters so they can be removed again
MAX_VESSELS = 30
MAX_TRACES = 40  # TANeSW look-ups for removed boxes per run
TRACE_DAYS = 30  # a removed box is followed this long, or until it is carried in somewhere
SAFETY_HOURS = 24  # a vessel nothing pointed at is still re-read once a day (see _vessels)
ROW_SKIP = (
	"name",
	"parent",
	"parenttype",
	"parentfield",
	"idx",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"docstatus",
	"doctype",
)

# outcomes
TO_ICD, TO_PORT, ELSEWHERE, BACK, ADDED, NOT_TRACED = (
	"Diverted to another ICD",
	"Moved to a port facility",
	"Moved elsewhere",
	"Back on our allocation",
	"Added to our allocation",
	"Not traced yet",
)
# Received at OUR ICD first, then sent on by a Simple Transfer to another ICD. Not a diversion: the boxes were allocated to us and reached us; leaving
# by Simple Transfer is an ordinary exit. Such boxes are not recorded as allocation changes at all
# (sync_vessel); this outcome only names an older record whose box TANeSW later shows we received.
TRANSFERRED_OUT = "Simple Transfer (still ours)"
DIVERTED = (TO_ICD, TO_PORT, ELSEWHERE)  # left our allocation before reaching us
# what happened to the ERP Manifest
TAKEN_OFF, KEPT_ORDER, KEPT_OFF, PUT_ON, NO_MANIFEST, BEFORE = (
	"Taken off the Manifest",
	"Kept: Movement Order, Container or Reception exists",
	"Kept: Apply TANeSW Changes is off",
	"Added to the Manifest",
	"No ERP Manifest",
	"Left before the ERP Manifest was made",
)
KEPT_RECEIVED = "Kept: received at our ICD"


def settings():
	return frappe.get_single(SETTINGS)


# --------------------------------------------------------------------------- settings switch
def apply_setters(on):
	"""'Apply TANeSW Changes to ERP Manifests': let the four Manifest tables change after submit (Property Setters)."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if "icd_tz" not in frappe.get_installed_apps():
		return
	for table in TABLES:
		name = f"Manifest-{table}-allow_on_submit"
		if on:
			make_property_setter(
				"Manifest", table, "allow_on_submit", "1", "Check", validate_fields_for_doctype=False
			)
			frappe.db.set_value("Property Setter", name, {"module": None, "default_value": TAG})
		elif frappe.db.get_value("Property Setter", name, "default_value") == TAG:
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype="Manifest")


# --------------------------------------------------------------------------- scheduling
def enqueue_manifest_sync():
	from tanesw_integration import outage

	if outage.paused():
		return  # TANeSW is down: skipped until the pause expires (outage.py)
	if not cint(frappe.db.get_single_value(SETTINGS, "enable_manifest_sync")):
		return
	frappe.enqueue(
		"tanesw_integration.manifest_sync.sync_manifests",
		queue="long",
		timeout=2400,
		job_id=JOB_ID,
		deduplicate=True,
	)


@frappe.whitelist(methods=["POST"])
def run_now():
	frappe.only_for("System Manager")
	frappe.enqueue(
		"tanesw_integration.manifest_sync.sync_manifests",
		queue="long",
		timeout=2400,
		job_id=JOB_ID,
		deduplicate=True,
		force=True,
	)
	return _("Manifest sync queued. Refresh TANeSW Settings in a few minutes to see the result.")


@frappe.whitelist(methods=["POST"])
def check_vessel_now(manifest: Scalar):
	"""'Check TANeSW Now' on the Manifest form: run this one vessel at once."""
	frappe.only_for(("System Manager", "TANeSW User", "TANeSW Operations"))
	s = settings()
	if not cint(s.enable_manifest_sync):
		frappe.throw(_("Switch on 'Track Allocation Changes Box by Box' in TANeSW Settings first."))
	mrn = frappe.db.get_value("Manifest", manifest, "mrn")
	if not mrn:
		frappe.throw(_("This Manifest has no MRN."))
	stats = _new_stats()
	with _watcher(s) as account:
		if not account:
			frappe.throw(_("No TANeSW watcher account could log in."))
		sync_vessel(mrn, s, stats, {"traces": MAX_TRACES})
		_mark_synced(mrn)
	return stats


# --------------------------------------------------------------------------- main
def sync_manifests():
	s = settings()
	if not cint(s.enable_manifest_sync):
		return _record({"status": "disabled"})
	stats = _new_stats()
	budget = {"traces": MAX_TRACES}
	with _watcher(s) as account:
		if not account:
			return _record({"status": "login_failed"})
		stats["account"] = account
		for mrn in _vessels(s, stats):
			try:
				sync_vessel(mrn, s, stats, budget)
				_mark_synced(mrn)
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background job: keep each finished vessel if a later one fails
			except Exception:
				frappe.db.rollback()
				stats["failed"] += 1
				_outage_log_error(title=f"TANeSW manifest sync failed: {mrn}", message=frappe.get_traceback())
				frappe.clear_messages()
		try:
			retrace_open(budget, stats)
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background job: keep each finished vessel if a later one fails
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="TANeSW manifest sync: re-trace failed", message=frappe.get_traceback())
			frappe.clear_messages()
	return _record(stats)


def sync_vessel(mrn, s, stats, budget, fresh=None):
	"""One vessel: download, create the Manifest if wanted, record changes, apply them if wanted."""
	fresh = fresh or download(mrn)
	if not fresh or not fresh.containers:
		stats["empty"] += 1
		return
	stats["vessels"] += 1
	now_boxes = {_cn(c.container_no): c for c in fresh.containers if c.container_no}

	manifest = erp_manifest(mrn)
	if not manifest and cint(s.auto_create_manifests):
		manifest = create_manifest(fresh, s.manifest_create_status or "Draft", stats)
	else:
		_discard_file(fresh)

	on_manifest = _manifest_boxes(manifest) if manifest else {}
	seen_by_sync = {
		_cn(r.container_no): r.bl_no
		for r in frappe.get_all("TANeSW Container", filters={"mrn": mrn}, fields=["container_no", "bl_no"])
	}
	known = {**seen_by_sync, **on_manifest}

	# gone from our B/Ls. A box TANeSW shows we received and then sent on (Simple Transfer) stays ours: not an
	# allocation change, not taken off the Manifest, counted as an exit (Delivered) on the home page
	gone = [c for c in known if c not in now_boxes]
	removed = [c for c in gone if not _received_here(mrn, c)]
	stats["simple_transfer"] = stats.get("simple_transfer", 0) + len(gone) - len(removed)
	# added only against an ERP Manifest: TANeSW Container may simply not have seen a new box yet
	added = [c for c in now_boxes if manifest and c not in on_manifest]

	for cntr in [c for c in now_boxes if frappe.db.exists(LOG, _log_name(mrn, c, "Removed"))]:
		_mark_back(mrn, cntr)

	vessel = fresh.vessel_name or frappe.db.get_value("TANeSW Vessel Allocation", mrn, "vessel_name")
	for cntr in removed:
		_record_change(
			mrn, vessel, manifest, cntr, known.get(cntr), "Removed", stats, on_manifest=cntr in on_manifest
		)
	for cntr in added:
		_record_change(mrn, vessel, manifest, cntr, now_boxes[cntr].m_bl_no, "Added", stats)

	if manifest and (removed or added):
		apply_to_manifest(manifest, fresh, [c for c in removed if c in on_manifest], added, s, stats)

	for name in frappe.get_all(
		LOG, filters={"mrn": mrn, "change_type": "Removed", "trace_complete": 0}, pluck="name"
	):
		if budget["traces"] <= 0:
			break
		budget["traces"] -= 1
		trace(name, stats)


# --------------------------------------------------------------------------- TANeSW workbook -> unsaved Manifest
def download(mrn):
	"""TANeSW's Excel Download, extracted by icd_tz's own import into an unsaved Manifest (file kept on _file)."""
	from tanesw_integration.cargo import manifest_excel

	company = our_company()
	res = manifest_excel(mrn) or {}
	if not res.get("content"):
		return None
	f = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": res.get("filename") or f"{mrn}.xlsx",
			"is_private": 1,
			"content": base64.b64decode(res["content"]),
		}
	).insert(ignore_permissions=True)
	doc = frappe.get_doc({"doctype": "Manifest", "manifest": f.file_url, "company": company})
	try:
		doc.extract_data_from_manifest_file()
	except Exception:
		frappe.delete_doc("File", f.name, ignore_permissions=True, force=True)
		raise
	doc._file = f.name
	return doc


def our_company():
	from tanesw_integration.containers import _facility_code

	code = _facility_code()
	company = frappe.db.get_value("ICD Setting", {"icd_code": code}, "company")
	if not company:
		frappe.throw(_("No ICD Setting has ICD Code {0}: the Manifest import needs it.").format(code))
	return company


def _discard_file(fresh):
	if getattr(fresh, "_file", None):
		frappe.delete_doc("File", fresh._file, ignore_permissions=True, force=True)


def erp_manifest(mrn):
	"""The latest ERP Manifest of this MRN that is not cancelled (an amended one wins)."""
	return frappe.db.get_value(
		"Manifest", {"mrn": mrn, "docstatus": ["<", 2]}, "name", order_by="creation desc"
	)


def create_manifest(fresh, status, stats):
	fresh.port = fresh.port or port_of(fresh.mrn)
	fresh.flags.ignore_permissions = True
	fresh.insert()
	if getattr(fresh, "_file", None):
		frappe.db.set_value(
			"File",
			fresh._file,
			{
				"attached_to_doctype": "Manifest",
				"attached_to_name": fresh.name,
				"attached_to_field": "manifest",
			},
		)
	stats["created"] += 1
	if status == "Submitted":
		if fresh.port:
			# icd_tz's own submit can refuse TANeSW's data (a consignee phone like 'TEL:+255700000000' is not a
			# valid Phone). Then keep the Draft and say why, instead of losing it and retrying every run.
			frappe.db.savepoint("tanesw_msync_submit")
			try:
				# icd_tz's submit makes a Consignee per name with TANeSW's phone as given, and Frappe refuses many of
				# them; made here first with the phone cleaned, icd_tz finds them existing and skips them
				_add_consignees(fresh.master_bl, fresh.house_bl)
				fresh.submit()
				stats["submitted"] += 1
			except Exception as e:
				frappe.db.rollback(save_point="tanesw_msync_submit")
				frappe.clear_messages()
				stats["submit_failed"] = stats.get("submit_failed", 0) + 1
				fresh.reload()
				fresh.add_comment(
					"Comment",
					_(
						"Created from TANeSW as Draft: icd_tz refused the submit: {0}. Correct it "
						"and submit."
					).format(frappe.utils.escape_html(frappe.utils.strip_html(str(e)))[:300]),
				)
		else:
			fresh.add_comment(
				"Comment",
				_(
					"Created from TANeSW as Draft: the port could not be read from TANeSW, so it "
					"was not submitted. Set the Port and submit."
				),
			)
	fresh.add_comment(
		"Comment", _("Created automatically from TANeSW's manifest Excel (TANeSW Manifest Sync).")
	)
	return fresh.name


def terminal_ports():
	"""TANeSW Settings > Terminal Codes to Manifest Ports: {'WTTZDL008': 'TEAGTL', ...}."""
	out = {}
	for line in (frappe.db.get_single_value("TANeSW Settings", "terminal_ports") or "").splitlines():
		code, sep, port = line.partition("=")
		if sep and code.strip() and port.strip():
			out[code.strip().upper()] = port.strip()
	return out


def port_of(mrn):
	from tanesw_integration.cargo import mrn_detail

	try:
		return terminal_ports().get(((mrn_detail(mrn) or {}).get("trmnlCd") or "").upper())
	except Exception:
		frappe.clear_messages()
		return None


# --------------------------------------------------------------------------- recording changes
def _cn(v):
	return (v or "").strip().upper()


def _log_name(mrn, cntr, change):
	return f"{mrn}-{cntr}-{change}"


def _manifest_boxes(manifest):
	return {
		_cn(r.container_no): r.m_bl_no
		for r in frappe.get_all(
			"Containers Detail",
			filters={"parent": manifest, "parenttype": "Manifest"},
			fields=["container_no", "m_bl_no"],
		)
		if r.container_no
	}


def _linked(manifest, cntr):
	"""Documents that already act on this box: then it is not taken off the Manifest automatically."""
	if not manifest:
		return {}
	f = {"manifest": manifest, "container_no": cntr, "docstatus": ["<", 2]}
	return {
		"movement_order": frappe.db.get_value("Container Movement Order", f, "name"),
		"container": frappe.db.get_value("Container", f, "name"),
		"reception": frappe.db.get_value("Container Reception", f, "name"),
		"port_charge": _port_charge(manifest, cntr),
	}


def _port_charge(manifest, cntr):
	"""A port-charge Purchase Order or Invoice already raised for this box (on its ICD Container, or a line naming
	it): the box stays on the Manifest, so the charge never loses its row."""
	if not frappe.db.exists("DocType", "ICD Container"):
		return None
	box = frappe.db.get_value(
		"ICD Container",
		{"manifest": manifest, "container_no": cntr},
		["name", "purchase_order", "purchase_invoice", "transport_purchase_invoice"],
		as_dict=True,
	)
	if not box:
		return None
	if box.purchase_order or box.purchase_invoice or box.transport_purchase_invoice:
		return box.purchase_order or box.purchase_invoice or box.transport_purchase_invoice
	for dt in ("Purchase Order Item", "Purchase Invoice Item"):
		if frappe.db.has_column(dt, "icd_container"):
			parent = frappe.db.get_value(dt, {"icd_container": box.name, "docstatus": ["<", 2]}, "parent")
			if parent:
				return parent
	return None


def _received_here(mrn, cntr):
	"""TANeSW says this box was carried in at our ICD (container sync, or a carry-in we linked)."""
	return bool(
		frappe.db.get_value("TANeSW Container", {"mrn": mrn, "container_no": cntr}, "received_on")
		or frappe.db.exists("TANeSW Carry In Container", {"mrn": mrn, "container_no": cntr})
	)


def _record_change(mrn, vessel, manifest, cntr, bl, change, stats, on_manifest=False):
	name = _log_name(mrn, cntr, change)
	if frappe.db.exists(LOG, name):
		doc = frappe.get_doc(LOG, name)
		if doc.outcome != BACK:
			return
		doc.outcome = NOT_TRACED if change == "Removed" else ADDED  # it left (or came) again
		doc.trace_complete = 0
		doc.detected_on = now_datetime()
		doc.save(ignore_permissions=True)
		stats["removed" if change == "Removed" else "added"] += 1
		return
	links = _linked(manifest, cntr)
	log = frappe.get_doc(
		{
			"doctype": LOG,
			"mrn": mrn,
			"vessel_name": vessel,
			"manifest": manifest,
			"container_no": cntr,
			"bl_no": bl,
			"change_type": change,
			"detected_on": now_datetime(),
			"outcome": NOT_TRACED if change == "Removed" else ADDED,
			"on_erp_manifest": 1 if on_manifest else 0,
			"manifest_action": NO_MANIFEST
			if not manifest
			else (BEFORE if change == "Removed" and not on_manifest else None),
			"movement_order": links.get("movement_order"),
			"container": links.get("container"),
			"reception": links.get("reception"),
			"trace_complete": 0 if change == "Removed" else 1,
		}
	)
	log.flags.ignore_links = True  # a log: a Movement Order deleted later must not stop the record
	log.insert(ignore_permissions=True)
	stats["removed" if change == "Removed" else "added"] += 1


def _mark_back(mrn, cntr):
	name = _log_name(mrn, cntr, "Removed")
	if frappe.db.get_value(LOG, name, "outcome") != BACK:
		frappe.db.set_value(LOG, name, {"outcome": BACK, "trace_complete": 1, "back_on": now_datetime()})


# --------------------------------------------------------------------------- where did a removed box go
def place_outcome(code, our_code):
	code = _cn(code)
	if not code:
		return NOT_TRACED
	if code == our_code:
		return BACK
	if code.startswith("WI"):
		return TO_ICD
	if code.startswith("WT"):
		return TO_PORT
	return ELSEWHERE


def trace(name, stats):
	"""TANeSW Cargo Tracking: the B/L's new place of delivery, when that was approved, where the box was carried in."""
	from tanesw_integration.cargo import tracking_container, tracking_detail, tracking_search
	from tanesw_integration.containers import _facility_code, milestones

	doc = frappe.get_doc(LOG, name)
	code = _facility_code()
	try:
		res = tracking_search(srch_cntr_no=doc.container_no) or {}
		hits = res.get("crns") or ([res["detail"]] if res.get("detail") else [])
		crn = next((h.get("crn") for h in hits if _cn(h.get("mrn")) == _cn(doc.mrn)), None)
		if not crn:
			doc.last_traced = now_datetime()
			doc.save(ignore_permissions=True)
			return
		d = tracking_detail(crn) or {}
		history = (tracking_container(crn, doc.container_no) or {}).get("cntrPrcssLst") or []
	except Exception:
		frappe.clear_messages()
		stats["trace_failed"] += 1
		return
	stats["traced"] += 1
	m = milestones(history, code) if history else {}
	new_code = _cn(d.get("dlvrPlcCd"))
	received_here = m.get("received_on")
	doc.update(
		{
			"crn": crn,
			"new_place_code": new_code,
			"new_place": (d.get("dlvrPlcCdNm") or "")[:140] or None,
			"last_traced": now_datetime(),
		}
	)
	doc.update(where_it_went(d, history, code, new_code, received_here, m))
	old = getdate(doc.detected_on) < getdate(add_days(nowdate(), -TRACE_DAYS))
	doc.trace_complete = 1 if (doc.carried_in_on or doc.outcome == BACK or old) else 0
	doc.save(ignore_permissions=True)


def where_it_went(d, history, code, new_code, received_here, m):
	"""Outcome, move date and the carry-in at the new place. A box TANeSW shows carried in at OUR ICD that now
	belongs elsewhere was transferred out after receipt (Simple Transfer), not 'back on our allocation': BACK only
	when the B/L's place of delivery is ours again."""
	events = sorted([*(d.get("blPrcssLst") or []), *history], key=lambda e: e.get("prcssDt") or "")

	def names(e):
		return str(e.get("cagTrkngPrcssCdNm") or "")

	def after(e):
		return not received_here or (e.get("prcssDt") and get_datetime(e["prcssDt"]) > received_here)

	approved = next(
		(
			e["prcssDt"]
			for e in reversed(events)
			if e.get("prcssDt")
			and after(e)
			and (
				"Change of Delivery Place Approved" in names(e)
				or "Simple Transfer Declaration Approved" in names(e)
			)
		),
		None,
	)
	if new_code == code:
		return {"outcome": BACK, "moved_on": get_datetime(approved) if approved else None}
	if received_here:
		elsewhere = next(
			(
				e
				for e in events
				if "Carry In Report Approved" in names(e)
				and after(e)
				and _cn(e.get("wrhsCd")) not in ("", code)
			),
			None,
		)
		return {
			"outcome": TRANSFERRED_OUT,
			"moved_on": get_datetime(approved) if approved else None,
			"carried_in_on": get_datetime(elsewhere["prcssDt"]) if elsewhere else None,
			"carried_in_at": (elsewhere.get("wrhsCdNm") or elsewhere.get("wrhsCd")) if elsewhere else None,
		}
	return {
		"outcome": place_outcome(new_code, code),
		"moved_on": get_datetime(approved) if approved else None,
		"carried_in_on": m.get("diverted_on"),
		"carried_in_at": m.get("diverted_to"),
	}


def retrace_open(budget, stats):
	for name in frappe.get_all(
		LOG, filters={"change_type": "Removed", "trace_complete": 0}, order_by="last_traced asc", pluck="name"
	):
		if budget["traces"] <= 0:
			return
		budget["traces"] -= 1
		trace(name, stats)


# --------------------------------------------------------------------------- ERP Manifest update
def _row(r):
	return {k: v for k, v in r.as_dict().items() if k not in ROW_SKIP}


def apply_to_manifest(manifest, fresh, removed, added, s, stats):
	"""Removed/added boxes -> the ERP Manifest, when 'Apply TANeSW Changes' is on."""
	if not cint(s.update_erp_manifests):
		for cntr in removed:
			frappe.db.set_value(LOG, _log_name(fresh.mrn, cntr, "Removed"), "manifest_action", KEPT_OFF)
		for cntr in added:
			frappe.db.set_value(LOG, _log_name(fresh.mrn, cntr, "Added"), "manifest_action", KEPT_OFF)
		return
	doc = frappe.get_doc("Manifest", manifest)
	take_off, keep, received = [], [], []
	for cntr in removed:
		if _received_here(fresh.mrn, cntr):
			received.append(cntr)  # physically ours once: never off the Manifest, whatever the ERP has
		elif any(_linked(manifest, cntr).values()):
			keep.append(cntr)
		else:
			take_off.append(cntr)
	for cntr in received:
		frappe.db.set_value(LOG, _log_name(fresh.mrn, cntr, "Removed"), "manifest_action", KEPT_RECEIVED)
	stats["kept"] += len(received)

	take_off_set, added_set = set(take_off), set(added)
	doc.containers = [r for r in doc.containers if _cn(r.container_no) not in take_off_set]
	doc.hbl_containers = [r for r in doc.hbl_containers if _cn(r.container_no) not in take_off_set]
	for r in fresh.containers:
		if _cn(r.container_no) in added_set:
			doc.append("containers", _row(r))
	for r in fresh.hbl_containers:
		if _cn(r.container_no) in added_set:
			doc.append("hbl_containers", _row(r))

	# B/L rows follow their boxes: a B/L with no box left goes; a new B/L comes with its house B/Ls
	still = {r.m_bl_no for r in doc.containers}
	gone_bls = {r.m_bl_no for r in doc.master_bl if r.m_bl_no not in still}
	have = {r.m_bl_no for r in doc.master_bl}
	new_bls = [r for r in fresh.master_bl if r.m_bl_no in still and r.m_bl_no not in have]
	new_bl_nos = {r.m_bl_no for r in new_bls}
	doc.master_bl = [r for r in doc.master_bl if r.m_bl_no not in gone_bls]
	doc.house_bl = [r for r in doc.house_bl if r.m_bl_no not in gone_bls]
	for r in new_bls:
		doc.append("master_bl", _row(r))
	for r in fresh.house_bl:
		if r.m_bl_no in new_bl_nos:
			doc.append("house_bl", _row(r))

	doc.flags.ignore_permissions = True
	frappe.flags.tanesw_manifest_sync = True  # guard_manifest_tables lets only this sync change the tables
	try:
		doc.save()  # after submit: the four tables are allow_on_submit via apply_setters
	finally:
		frappe.flags.tanesw_manifest_sync = False
	if doc.docstatus == 1:
		_add_dimensions(doc, added_set, new_bl_nos)
	_refresh_bl_counts(doc, fresh)
	_add_consignees(new_bls, [r for r in fresh.house_bl if r.m_bl_no in new_bl_nos])
	doc.add_comment(
		"Comment",
		_(
			"TANeSW Manifest Sync: {0} box(es) taken off, {1} added. Kept (Movement Order, "
			"Container, Reception or port charge exists): {2}."
		).format(len(take_off), len(added), ", ".join(keep) or _("none")),
	)

	for cntr in take_off:
		frappe.db.set_value(LOG, _log_name(fresh.mrn, cntr, "Removed"), "manifest_action", TAKEN_OFF)
	for cntr in keep:
		frappe.db.set_value(LOG, _log_name(fresh.mrn, cntr, "Removed"), "manifest_action", KEPT_ORDER)
	for cntr in added:
		frappe.db.set_value(LOG, _log_name(fresh.mrn, cntr, "Added"), "manifest_action", PUT_ON)
	stats["taken_off"] += len(take_off)
	stats["kept"] += len(keep)
	stats["put_on"] += len(added)


BL_FIGURES = (
	"number_of_containers",
	"gross_volume",
	"gross_volume_unit",
	"gross_weight",
	"net_weight",
	"number_of_package",
)  # B/L totals TANeSW restates when a box moves within a B/L


def _refresh_bl_counts(doc, fresh=None):
	"""Master BL totals follow TANeSW. 'Number of Containers' drives icd_tz's Movement Order 'box x of y'
	(update_container_count); Billing Efficiency splits an LCL B/L's volume over it. A B/L TANeSW still lists takes
	its figures from TANeSW's row; a B/L only kept on the Manifest (a box with a Movement Order) gets the box count the
	Manifest now has. Written with db.set_value, the way icd_tz's own update_master_bl_values edits Master BL rows
	of a submitted Manifest."""
	meta = frappe.get_meta("Master BL")
	figures = [f for f in BL_FIGURES if meta.has_field(f)]
	tanesw = {r.m_bl_no: r for r in (fresh.master_bl if fresh else [])}
	per_bl = {}
	for r in doc.containers:
		per_bl[r.m_bl_no] = per_bl.get(r.m_bl_no, 0) + 1
	for r in doc.master_bl:
		src = tanesw.get(r.m_bl_no)
		if src:
			changed = {f: src.get(f) for f in figures if str(src.get(f) or "") != str(r.get(f) or "")}
		else:
			n = per_bl.get(r.m_bl_no)
			changed = {"number_of_containers": n} if n and cint(r.number_of_containers) != n else {}
		if changed:
			frappe.db.set_value("Master BL", r.name, changed, update_modified=False)


def guard_manifest_tables(doc, method=None):
	"""doc_events hook on Manifest (before_update_after_submit). 'Apply TANeSW Changes' makes the four tables editable
	after submit so this sync can follow TANeSW; nobody else may add or remove rows on a submitted Manifest."""
	if frappe.flags.get("tanesw_manifest_sync"):
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	for table in TABLES:
		if {r.name for r in before.get(table) or []} != {r.name for r in doc.get(table) or []}:
			frappe.throw(
				_(
					"Rows of a submitted Manifest cannot be added or removed by hand. TANeSW Manifest Sync keeps "
					"them in line with TANeSW."
				),
				title=_("Manifest"),
			)


def clean_phone(value):
	"""TANeSW phones are free text ('TEL:+255700000000', '0700 000000/0711', 'MOB. 0700-000000'). Keep the FIRST
	number, digits only with a leading +, so Frappe's Phone check accepts it. None when no usable number is left.

	A number in scientific notation ('2.55072E+12', about 1 in 5 TANeSW phones) has lost its digits inside TANeSW
	itself: its Excel AND its Master BL API both return that text. Only 6 digits
	are left, so it is None, never a made-up number."""
	if not value:
		return None
	if re.search(r"\d[.,]?\d*\s*E\s*[+-]?\s*\d", str(value), re.I):
		return None
	text = re.sub(
		r"^\s*(TEL(EPHONE)?|PHONE|MOB(ILE)?|CELL|CONTACT)\b\s*(NO\b)?\s*[:.#]?\s*", "", str(value).upper()
	)
	first = re.split(r"/|,|;|\bOR\b|&", text)[0].strip()
	plus = first.startswith("+")
	digits = re.sub(r"\D", "", first)
	if not 7 <= len(digits) <= 15:  # shorter is not a phone number; ITU numbers are at most 15 digits
		return None
	return ("+" if plus else "") + digits


def _add_consignees(*row_lists):
	"""Same rule as icd_tz on submit: a Consignee per consignee name, created once. TANeSW phones are free text and
	Frappe's Phone check refuses many, so the phone is cleaned first (clean_phone). When it changed, or no number could
	be kept, the number TANeSW gave is kept in a comment, so one phone can never stop the vessel's update."""
	for rows in row_lists:
		for r in rows:
			if not r.consignee_name or frappe.db.exists("Consignee", r.consignee_name):
				continue
			given = (r.get("consignee_tel") or "").strip()
			values = {
				"doctype": "Consignee",
				"consignee_name": r.consignee_name,
				"consignee_tel": clean_phone(given),
				"consignee_tin": r.get("consignee_tin"),
				"consignee_address": r.get("consignee_address"),
			}
			try:
				c = frappe.get_doc(values).insert(ignore_permissions=True)
			except frappe.InvalidPhoneNumberError:
				frappe.clear_messages()
				c = frappe.get_doc({**values, "consignee_tel": None}).insert(ignore_permissions=True)
			if given and c.consignee_tel != given:
				kept = c.consignee_tel
				c.add_comment(
					"Comment",
					(
						_("TANeSW gave the phone '{0}'; it was saved as {1}.").format(
							frappe.utils.escape_html(given), kept
						)
						if kept
						else _(
							"TANeSW gave the phone '{0}', which is not a "
							"valid phone number, so it was left out."
						).format(frappe.utils.escape_html(given))
					),
				)


ICD_DIMENSIONS = "icd_tz.icd_tz.api.accounting_dimensions"  # what icd_tz's Manifest submit uses


def _add_dimensions(doc, added, new_bl_nos):
	"""ICD Master BL / ICD Container records for what was added after submit, made by icd_tz's OWN functions -- the
	ones its Manifest submit uses -- so the two can never drift apart (PR #714 review, item 12). They are looked up by
	name when needed, not imported: if icd_tz renames them, the copy below is used, a warning is logged, and
	test_review_fixes fails, so the change is noticed."""
	if not frappe.db.exists("DocType", "ICD Container"):
		return
	try:
		bl_consignees = frappe.get_attr(f"{ICD_DIMENSIONS}.get_bl_consignees")
		make_bls = frappe.get_attr(f"{ICD_DIMENSIONS}.create_master_bls")
		make_containers = frappe.get_attr(f"{ICD_DIMENSIONS}.create_containers")
	except (ImportError, AttributeError):
		frappe.logger("tanesw_integration").warning(
			"icd_tz dimension functions not found: using the app's copy"
		)
		return _add_dimensions_copy(doc, added, new_bl_nos)
	have_bls = set(frappe.get_all("ICD Master BL", filters={"manifest": doc.name}, pluck="m_bl_no"))
	have_boxes = set(frappe.get_all("ICD Container", filters={"manifest": doc.name}, pluck="container_no"))
	new = frappe._dict(
		name=doc.name,
		company=doc.company,
		vessel_name=doc.vessel_name,
		voyage_no=doc.voyage_no,
		arrival_date=doc.arrival_date,
		master_bl=[r for r in doc.master_bl if r.m_bl_no in new_bl_nos and r.m_bl_no not in have_bls],
		containers=[
			r for r in doc.containers if _cn(r.container_no) in added and r.container_no not in have_boxes
		],
	)
	consignees = bl_consignees(frappe._dict(master_bl=doc.master_bl))  # an added box may sit on an older B/L
	make_bls(new, consignees)
	names = dict(
		frappe.get_all(
			"ICD Master BL", filters={"manifest": doc.name}, fields=["m_bl_no", "name"], as_list=True
		)
	)
	make_containers(new, consignees, names)


def _add_dimensions_copy(doc, added, new_bl_nos):
	"""Fallback when icd_tz's own functions cannot be found: the same records, saved through their controllers."""
	for r in doc.master_bl:
		if r.m_bl_no in new_bl_nos and not frappe.db.exists(
			"ICD Master BL", {"manifest": doc.name, "m_bl_no": r.m_bl_no}
		):
			frappe.get_doc(
				{
					"doctype": "ICD Master BL",
					"m_bl_no": r.m_bl_no,
					"manifest": doc.name,
					"posting_date": nowdate(),
					"company": doc.company,
					"consignee": r.consignee_name
					if r.consignee_name and frappe.db.exists("Consignee", r.consignee_name)
					else None,
					"cargo_classification": r.cargo_classification,
					"number_of_containers": r.number_of_containers,
					"place_of_destination": r.place_of_destination,
					"place_of_delivery": r.place_of_delivery,
					"port_of_loading": r.port_of_loading,
					"cargo_description": r.cargo_description,
					"vessel_name": doc.vessel_name,
					"voyage_no": doc.voyage_no,
					"shipping_agent_code": r.shipping_agent_code,
					"shipping_agent_name": r.shipping_agent_name,
				}
			).insert(ignore_permissions=True)
	for r in doc.containers:
		cntr = _cn(r.container_no)
		if cntr not in added or frappe.db.exists(
			"ICD Container", {"manifest": doc.name, "container_no": r.container_no}
		):
			continue
		frappe.get_doc(
			{
				"doctype": "ICD Container",
				"container_no": r.container_no,
				"manifest": doc.name,
				"posting_date": nowdate(),
				"company": doc.company,
				"m_bl_no": r.m_bl_no,
				"master_bl": frappe.db.get_value(
					"ICD Master BL", {"manifest": doc.name, "m_bl_no": r.m_bl_no}, "name"
				),
				"type_of_container": r.type_of_container,
				"size": r.container_size,
				"freight_indicator": r.freight_indicator,
				"no_of_packages": r.no_of_packages,
				"package_unit": r.package_unit,
				"weight": r.weight,
				"weight_unit": r.weight_unit,
				"vessel_name": doc.vessel_name,
				"voyage_no": doc.voyage_no,
				"arrival_date": doc.arrival_date,
			}
		).insert(ignore_permissions=True)


# --------------------------------------------------------------------------- Manifest form
@frappe.whitelist(methods=["POST"])
def manifest_summary(manifest: Scalar):
	"""Figures for the 'Diverted' card and the TANeSW changes line on the Manifest form."""
	frappe.has_permission("Manifest", "read", manifest, throw=True)
	mrn = frappe.db.get_value("Manifest", manifest, "mrn")
	enabled = cint(frappe.db.get_single_value(SETTINGS, "enable_manifest_sync"))
	if not mrn or not enabled:
		return {"enabled": enabled}
	rows = frappe.get_all(
		LOG,
		filters={"mrn": mrn},
		fields=[
			"container_no",
			"bl_no",
			"change_type",
			"outcome",
			"new_place",
			"carried_in_at",
			"manifest_action",
			"movement_order",
		],
		order_by="detected_on desc",
	)
	# diverted = left our allocation before reaching us; a box we received and then transferred out is counted apart
	removed = [r for r in rows if r.change_type == "Removed" and r.outcome not in (BACK, TRANSFERRED_OUT)]
	transferred = [r for r in rows if r.change_type == "Removed" and r.outcome == TRANSFERRED_OUT]
	places, out_places = {}, {}
	for r in removed:
		key = r.new_place or r.carried_in_at or _("not traced yet")
		places[key] = places.get(key, 0) + 1
	for r in transferred:
		key = r.new_place or r.carried_in_at or _("not traced yet")
		out_places[key] = out_places.get(key, 0) + 1
	return {
		"enabled": 1,
		"mrn": mrn,
		"diverted": len(removed),
		"transferred_out": len(transferred),
		"out_places": out_places,
		"to_icd": sum(1 for r in removed if r.outcome == TO_ICD),
		"to_port": sum(1 for r in removed if r.outcome == TO_PORT),
		"added": sum(1 for r in rows if r.change_type == "Added" and r.outcome != BACK),
		"needs_action": sum(1 for r in removed if r.manifest_action == KEPT_ORDER),
		"places": places,
		"last_run": _last_run(),
	}


def _last_run():
	v = frappe.db.get_single_value(SETTINGS, "manifest_sync_last_run")
	try:
		return (
			v if v and get_datetime(v).year > 2000 else None
		)  # an empty Datetime single comes back as year 1
	except Exception:
		return None


# --------------------------------------------------------------------------- helpers
def _new_stats():
	return frappe._dict(
		{
			k: 0
			for k in (
				"vessels",
				"unchanged",
				"empty",
				"failed",
				"created",
				"submitted",
				"removed",
				"added",
				"traced",
				"trace_failed",
				"taken_off",
				"kept",
				"put_on",
			)
		},
		status="ok",
		why={},
	)


# --------------------------------------------------------------------------- which vessels to download
def _vessels(s, stats=None):
	"""Only vessels where TANeSW shows something new. The signals are already in our tables, read for free:
	the allocation watcher's B/L and box counts (one TANeSW list call for every vessel, every 15 minutes) and the
	container sync's boxes (a new box on our B/Ls, or a box that left them). The workbook is downloaded only then,
	plus once a day per vessel as a safety net for a swap the counts and the container sync could both miss."""
	days = cint(s.get("container_tracking_days")) or 45
	since = add_days(nowdate(), -days)
	rows = frappe.get_all(
		"TANeSW Vessel Allocation",
		fields=["name", "bl_count", "container_count", "manifest_synced_on", "manifest_synced_counts"],
		or_filters=[["arrival_date", ">=", since], ["arrival_date", "is", "not set"]],
		order_by="arrival_date desc",
		limit=MAX_VESSELS,
	)
	out = []
	for v in rows:
		why = why_check(v, cint(s.auto_create_manifests))
		if not why:
			if stats is not None:
				stats["unchanged"] += 1
			continue
		out.append(v.name)
		if stats is not None:
			stats["why"][why] = stats["why"].get(why, 0) + 1
	return out


def why_check(v, auto_create):
	"""Why this vessel's workbook should be downloaded now, or None when nothing points at a change."""
	synced = v.manifest_synced_on and get_datetime(v.manifest_synced_on)
	if not synced:
		return "first check"
	if _counts(v) != (v.manifest_synced_counts or ""):
		return "allocation counts changed"
	manifest = erp_manifest(v.name)
	if not manifest and auto_create:
		return "no ERP Manifest yet"
	if manifest and get_datetime(frappe.db.get_value("Manifest", manifest, "creation")) > synced:
		return "ERP Manifest uploaded"
	if frappe.db.exists("TANeSW Container", {"mrn": v.name, "creation": [">", synced]}):
		return "new box on our B/Ls"
	if frappe.db.exists("TANeSW Container", {"mrn": v.name, "removed_from_allocation_on": [">", synced]}):
		return "box left our B/Ls"
	if synced < add_to_date(now_datetime(), hours=-SAFETY_HOURS):
		return "daily re-check"
	return None


def _counts(v):
	return f"{cint(v.get('bl_count'))}/{cint(v.get('container_count'))}"


def _mark_synced(mrn):
	v = frappe.db.get_value("TANeSW Vessel Allocation", mrn, ["bl_count", "container_count"], as_dict=True)
	if v:
		frappe.db.set_value(
			"TANeSW Vessel Allocation",
			mrn,
			{"manifest_synced_on": now_datetime(), "manifest_synced_counts": _counts(v)},
			update_modified=False,
		)


@contextmanager
def _watcher(s):
	from tanesw_integration.containers import _as_watcher

	accounts = watcher_accounts(s)
	with _as_watcher(accounts) as account:
		yield account


def _record(stats):
	import json

	frappe.db.set_single_value(
		SETTINGS,
		{
			"manifest_sync_last_run": now_datetime(),
			"manifest_sync_last_result": json.dumps(stats, default=str),
		},
	)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background job: keep each finished vessel if a later one fails
	return stats
