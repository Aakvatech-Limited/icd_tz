"""Link TANeSW carry-ins to icd_tz: Best Pick Movement Order -> draft Container Reception.

Why the carry-in report and not the declaration: an ICD Transfer Declaration lists its containers and a POOL of
vehicles separately (one container, several trucks), so it cannot say
which truck carries which container. The carry-in report can: from the moment the terminal hands a container over
(Handover Report, its criBaseNo) each truck row names its container, trailer, driver and seal, and later carries
"gate exit confirmed" (left the port) and "entry confirmed" (reached our gate). Operators mostly work in the TANeSW
portal, so this job reads those reports from TANeSW instead of waiting for a carry-in made inside this app.

Timing (measured on about 150 handover reports from both terminals): the truck row
appears once the truck has left the port, and the carry-in at our ICD followed the handover by a median 1.9 h
(shortest 0.6 h, 90% within 3.9 h). So the Best Pick order is filled while the truck is still on the road; only the
reception waits for our gate. The job runs every 5 minutes and re-reads only handovers with a truck not yet in.

Every 5 minutes, when "Link Carry-Ins to icd_tz" is ticked in TANeSW Settings and icd_tz is installed:
  1. Read our carry-in reports of the last few days; log each truck/container pair once (TANeSW Carry In Container).
  2. Movement Order: use the container's submitted order, or fill the Best Pick order of the same manifest (MRN) and
     truck, after checking the container and its B/L are on that manifest. Filled exactly like the Movement Order
     screen does (container row as in its get_manifest_details, saved as an update), so icd_tz's own checks run: container
     on the manifest, one order per container, Ship D/C date, port charges paid.
     icd_tz itself is never modified: this app only reads its tables and saves its documents through their own
     controllers, so every icd_tz rule still applies.
  3. Container Reception: made and SUBMITTED from our carry-in screen, where the gate clerk gives the two things only
     the gate knows (yard location, clerk). A carry-in made in the TANeSW portal waits as "Awaiting Reception" until
     someone opens it on our screen and presses "Receive into ERP" -- unless "Also Draft Receptions for Portal
     Carry-Ins" is ticked, when a DRAFT reception is made for the clerk to finish (yard location and clerk cannot be
     changed on a submitted reception in icd_tz, so they are never guessed).
Anything that does not fit is left as an Exception with the reason, never guessed.

Two triggers, one path: the 5-minute check (carry-ins made in the TANeSW portal) and, for a carry-in submitted from
this app (cargo.cri_submit), an immediate job for that one report. No duplicates, from four guards:
  - one log per carry-in/handover and container (unique link_key; a simultaneous insert of the same key is caught);
  - each container's link is processed under a row lock (SELECT ... FOR UPDATE), so two jobs never work on it at once;
  - an order that already names the container is reused, and a Best Pick order is only filled while still empty
    (icd_tz also refuses a second order for the same container);
  - a reception that already exists for the order (draft or submitted, even one a clerk made by hand) is reused,
    and icd_tz itself refuses a second reception for the same movement order.
"""

import json
import re

import frappe
from frappe.utils import add_days, cint, get_datetime, now_datetime, nowdate, strip_html

from tanesw_integration.credentials import require_tanesw_user, watcher_accounts
from tanesw_integration.hints import JSONish, Scalar
from tanesw_integration.outage import log_error as _outage_log_error

SETTINGS = "TANeSW Settings"
LOG = "TANeSW Carry In Container"
CMO = "Container Movement Order"
RECEPTION = "Container Reception"
JOB_ID = "tanesw_icd_link"
LOOKBACK_DAYS = 3  # carry-in reports read from TANeSW
RETRY_DAYS = 7  # open links retried this long, then left as they are
WAITING, LINKED, DRAFTED, EXCEPTION = "Waiting for Order", "Order Linked", "Reception Drafted", "Exception"
SUBMITTED = "Reception Submitted"
AWAITING = (
	"Awaiting Reception"  # carried in through the TANeSW portal; the gate finishes it on our carry-in screen
)
CNTR_INFO = re.compile(r"([A-Z]{4}\d{7})\s*(?:\(([^)]*)\))?")


# --------------------------------------------------------------------------- scheduling
def enqueue_icd_link():
	from tanesw_integration import outage

	if outage.paused():
		return  # TANeSW is down: skipped until the pause expires (outage.py)
	if not cint(frappe.db.get_single_value(SETTINGS, "enable_icd_link")):
		return
	frappe.enqueue(
		"tanesw_integration.icd_link.sync_carry_ins",
		queue="long",
		timeout=1500,
		job_id=JOB_ID,
		deduplicate=True,
	)


@frappe.whitelist(methods=["POST"])
def run_now():
	frappe.only_for("System Manager")
	if not cint(frappe.db.get_single_value(SETTINGS, "enable_icd_link")):
		frappe.throw(frappe._("Tick 'Link Carry-Ins to icd_tz' and save first."))
	frappe.enqueue(
		"tanesw_integration.icd_link.sync_carry_ins",
		queue="long",
		timeout=1500,
		job_id=JOB_ID,
		deduplicate=True,
	)
	return frappe._("ICD link queued. Refresh TANeSW Settings in a few minutes to see the result.")


def on_carry_in_submitted(header):
	"""Called by cargo.cri_submit after TANeSW accepted a carry-in made in this app: link that report now instead of
	waiting for the 5-minute check. Queued after the request commits; one job per report."""
	h = header or {}
	crn, base = h.get("crn"), h.get("criBaseNo")
	if not (crn and base) or not cint(frappe.db.get_single_value(SETTINGS, "enable_icd_link")):
		return
	frappe.enqueue(
		"tanesw_integration.icd_link.sync_report",
		queue="short",
		timeout=600,
		job_id=f"{JOB_ID}:{base}",
		deduplicate=True,
		enqueue_after_commit=True,
		crn=crn,
		cri_base_no=base,
	)


def sync_report(crn, cri_base_no):
	"""Read one carry-in/handover report and link its containers (same steps as the 5-minute check)."""
	from tanesw_integration.containers import _as_watcher, _facility_code

	if not icd_tz_installed():
		return
	s = frappe.get_single(SETTINGS)
	accounts = watcher_accounts(s)
	names = []
	with _as_watcher(accounts) as account:
		if not account:
			return
		code = _facility_code()
		report = {"crn": crn, "criBaseNo": cri_base_no}
		detail = _report_detail(report, code)
		report["mrn"] = detail.get("mrn")
		for row in detail.get("wrhsCriVhclList") or []:
			for cntr, info in parse_cntr_info(row.get("cntrInfo")):
				names.append(upsert_log(report, row, cntr, info))
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one carry-in / container at a time: one refused box must not undo the others
	for name in names:
		_process_safely(name)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one carry-in / container at a time: one refused box must not undo the others


KEEP_LINK_DAYS = 90


def purge_old_links(days=KEEP_LINK_DAYS):
	"""Daily clean-up: carry-in link rows older than 90 days are deleted. They stopped being re-checked long before
	(RETRY_DAYS); the containers, movement orders and receptions they pointed to are kept. Error Log entries are
	already trimmed by Frappe's own Log Settings."""
	old = frappe.get_all(LOG, filters={"creation": ["<", add_days(nowdate(), -cint(days))]}, pluck="name")
	for name in old:
		frappe.delete_doc(LOG, name, ignore_permissions=True, force=True)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one carry-in / container at a time: one refused box must not undo the others
	return len(old)


def icd_tz_installed():
	return "icd_tz" in frappe.get_installed_apps()


# --------------------------------------------------------------------------- main
def sync_carry_ins():
	from tanesw_integration.containers import _as_watcher, _facility_code

	settings = frappe.get_single(SETTINGS)
	if not cint(settings.get("enable_icd_link")):
		return _record({"status": "disabled"})
	if not icd_tz_installed():
		return _record({"status": "icd_tz not installed"})
	accounts = watcher_accounts(settings)
	if not accounts:
		return _record({"status": "not_configured"})

	stats = {"status": "ok", "reports": 0, "trucks": 0, "failed_reports": 0}
	with _as_watcher(accounts) as account:
		if not account:
			return _record({"status": "login_failed"})
		stats["account"] = account
		code = _facility_code()
		for report in _recent_reports(code):
			stats["reports"] += 1
			if _all_trucks_in(report):
				stats["skipped_done"] = stats.get("skipped_done", 0) + 1
				continue
			try:
				for row in _truck_rows(report, code):
					stats["trucks"] += 1
					for cntr, info in parse_cntr_info(row.get("cntrInfo")):
						upsert_log(report, row, cntr, info)
			except Exception:
				stats["failed_reports"] += 1
				_outage_log_error(
					title=f"TANeSW carry-in read failed: {report.get('criBaseNo')}",
					message=frappe.get_traceback(),
				)
				frappe.clear_messages()
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one carry-in / container at a time: one refused box must not undo the others

	# the icd_tz side needs no TANeSW session: records are written by the job user, not the watcher's ERP user
	stats.update(process_open_links())
	return _record(stats)


def _recent_reports(code):
	from tanesw_integration.cargo import cri_list

	out, page = [], 0
	since, today = add_days(nowdate(), -LOOKBACK_DAYS), nowdate()
	while True:
		res = cri_list(str(since), str(today), page=page, size=50) or {}
		out += [r for r in res.get("content") or [] if (r.get("wrhsCd") or "").upper() == code]
		if page + 1 >= cint((res.get("page") or {}).get("totalPages") or 1):
			return out
		page += 1


def _all_trucks_in(report):
	"""True when every truck of this handover is already logged as entered our ICD: nothing left to learn from it.
	A handover we have not logged yet, or one with a truck still on the road, is read again."""
	entered = frappe.db.get_all(
		LOG, filters={"handover_no": report.get("criBaseNo")}, pluck="entry_confirmed"
	)
	expected = cint(report.get("vhclCnt") or report.get("cntrCnt") or 0)
	return bool(entered) and all(entered) and len(entered) >= expected


def _report_detail(report, code):
	from tanesw_integration.cargo import cri_detail

	return cri_detail(report.get("crn"), code, report.get("criBaseNo")) or {}


def _truck_rows(report, code):
	return _report_detail(report, code).get("wrhsCriVhclList") or []


def parse_cntr_info(text):
	"""'ABCU1234567 (22G0, SEAL1), XYZU7654321 (45G1, X1)' -> [(container, {size, seal}), ...]"""
	out = []
	for cntr, inside in CNTR_INFO.findall((text or "").upper()):
		parts = [p.strip() for p in (inside or "").split(",")]
		out.append(
			(
				cntr,
				{
					"size": parts[0] if parts and parts[0] else None,
					"seal": parts[1] if len(parts) > 1 and parts[1] else None,
				},
			)
		)
	return out


def upsert_log(report, row, cntr, info):
	"""One log per carry-in (or handover, before the carry-in has a number) and container. TANeSW facts are refreshed
	every run; the link fields are left to process_open_links."""
	mrn = (report.get("mrn") or "").upper()
	key = f"{row.get('dclrNo') or report.get('criBaseNo')}-{cntr}"
	# the carry-in number appears after the handover: keep the record made under the handover number
	old = f"{report.get('criBaseNo')}-{cntr}"
	name = _existing_log(key, old)
	values = {
		"container_no": cntr,
		"mrn": mrn,
		"crn": row.get("crn") or report.get("crn"),
		"carry_in_no": row.get("dclrNo"),
		"handover_no": report.get("criBaseNo"),
		"bl_no": frappe.db.get_value("TANeSW Container", f"{mrn}-{cntr}", "bl_no") or report.get("mblNo"),
		"truck": norm_plate(row.get("vhclNo")),
		"trailer": norm_plate(row.get("trlrNo")),
		"driver_name": row.get("drvrNm"),
		"driver_license": row.get("drvrLcneNo"),
		"container_size": info.get("size"),
		"seal_no": info.get("seal"),
		"gate_exit_confirmed": 1 if row.get("gateExitCfrmYn") == "Y" else 0,
		"entry_confirmed": 1 if row.get("entryCfrmYn") == "Y" else 0,
		"carry_in_status": row.get("prcssStatCd"),
		"carry_in_on": get_datetime(row["prcssDtm"]) if row.get("prcssDtm") else None,
	}
	try:  # real-time container status; never blocks the link itself
		from tanesw_integration.containers import advance_from_carry_in

		advance_from_carry_in(
			mrn, cntr, values["gate_exit_confirmed"], values["entry_confirmed"], values["carry_in_on"]
		)
	except Exception:
		_outage_log_error(title="TANeSW: real-time container status failed", message=frappe.get_traceback())
	doc = frappe.get_doc(LOG, name) if name else frappe.new_doc(LOG)
	if doc.is_new():
		doc.link_key = key
		doc.link_status = WAITING
	doc.update(values)
	doc.flags.ignore_permissions = True
	frappe.db.savepoint("tanesw_icd_log")
	try:
		doc.save()
	except frappe.DuplicateEntryError:
		# the other trigger logged the same carry-in/container a moment ago: update that one instead
		frappe.db.rollback(save_point="tanesw_icd_log")
		doc = frappe.get_doc(LOG, key)
		doc.update(values)
		doc.flags.ignore_permissions = True
		doc.save()
	return doc.name


def _existing_log(key, old):
	return key if frappe.db.exists(LOG, key) else (old if frappe.db.exists(LOG, old) else None)


def norm_plate(v):
	return re.sub(r"[^A-Z0-9]", "", (v or "").upper()) or None


# --------------------------------------------------------------------------- icd_tz side
def process_open_links():
	counts = {LINKED: 0, DRAFTED: 0, SUBMITTED: 0, EXCEPTION: 0, WAITING: 0}
	for name in frappe.get_all(
		LOG,
		filters={"link_status": ["!=", SUBMITTED], "creation": [">=", add_days(nowdate(), -RETRY_DAYS)]},
		pluck="name",
		order_by="creation asc",
	):
		status = _process_safely(name)
		counts[status] = counts.get(status, 0) + 1
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one carry-in / container at a time: one refused box must not undo the others
	return {"links": counts}


def _process_safely(name):
	frappe.db.savepoint("tanesw_icd_link")
	try:
		return process_link(name)
	except Exception:
		frappe.db.rollback(save_point="tanesw_icd_link")
		frappe.log_error(title=f"TANeSW ICD link failed: {name}", message=frappe.get_traceback())
		frappe.clear_messages()
		return _set(name, EXCEPTION, "Unexpected error, see Error Log")


def process_link(name):
	# row lock: the 5-minute check and an immediate carry-in job never work on the same container at once;
	# the second waits, then sees the first one's order / reception and reuses it
	Log = frappe.qb.DocType(LOG)
	frappe.qb.from_(Log).select(Log.name).where(Log.name == name).for_update().run()
	if frappe.db.get_value(LOG, name, "link_status") == SUBMITTED:
		return SUBMITTED
	log = frappe.get_doc(LOG, name)
	at_gate = log.entry_confirmed or log.received_at_gate
	manifest = log.manifest or frappe.db.get_value("Manifest", {"mrn": log.mrn, "docstatus": 1}, "name")
	if not manifest:
		return _set(name, EXCEPTION, f"No submitted Manifest with MRN {log.mrn}")

	order, problem = find_or_fill_order(manifest, log)
	if not order:
		# before the container reaches our gate an order can still be made: keep waiting, but say why
		return _set(name, EXCEPTION if at_gate else WAITING, problem, manifest=manifest)

	check, note = compare_transport(order, log)
	frappe.db.set_value(LOG, name, {"transport_check": check, "transport_note": note})
	tail = f" | {note}" if check == DIFFERS else ""

	if not at_gate:
		return _set(
			name,
			LINKED,
			"Movement Order ready; reception is drafted when TANeSW confirms entry at our gate" + tail,
			manifest=manifest,
			movement_order=order,
		)

	if not log.received_at_gate and not cint(frappe.db.get_single_value(SETTINGS, "draft_portal_receptions")):
		return _set(
			name,
			AWAITING,
			"Carried in through the TANeSW portal: open it on our Carry-In screen and press "
			"'Receive into ERP' with the yard location and clerk" + tail,
			manifest=manifest,
			movement_order=order,
		)

	reception, problem = draft_reception(order, log)
	if not reception:
		return _set(name, EXCEPTION, problem, manifest=manifest, movement_order=order)
	if frappe.db.get_value(RECEPTION, reception, "docstatus") == 1:
		return _set(
			name,
			SUBMITTED,
			"Received: Container Reception submitted" + tail,
			manifest=manifest,
			movement_order=order,
			container_reception=reception,
		)
	why = f" ({problem})" if problem else ""
	return _set(
		name,
		DRAFTED,
		"Draft reception ready: add yard location and clerk, check the box, then submit" + why + tail,
		manifest=manifest,
		movement_order=order,
		container_reception=reception,
	)


MATCHES, DIFFERS = "Matches", "Differs"


def compare_transport(order, log):
	"""TANeSW's truck / trailer / driver for this container against the Movement Order's.

	The reception copies truck, trailer, driver, licence and transporter from the order (icd_tz fetch_from), and icd_tz
	does not let them change on a submitted order, so a mismatch is flagged for the gate clerk, never overwritten.
	The driver is compared by licence number: names are spelled differently for the same licence .
	Plates ignore spaces and brackets ("(T123ABC)", "T 123 ABC")."""
	o = frappe.db.get_value(CMO, order, ["truck", "trailer", "driver", "driver_license"], as_dict=True) or {}
	diffs = []
	for label, ours, theirs in (
		("truck", norm_plate(o.get("truck")), log.truck),
		("trailer", norm_plate(o.get("trailer")), log.trailer),
		("driver licence", _norm_licence(o.get("driver_license")), _norm_licence(log.driver_license)),
	):
		if ours and theirs and ours != theirs:
			diffs.append(f"{label}: TANeSW {theirs}, order {ours}")
	if (
		diffs
		and log.driver_name
		and _norm_licence(o.get("driver_license")) != _norm_licence(log.driver_license)
	):
		diffs[-1] += f" (TANeSW driver {log.driver_name}, order driver {o.get('driver')})"
	return (DIFFERS, "Check at the gate - " + "; ".join(diffs)) if diffs else (MATCHES, None)


def _norm_licence(v):
	return re.sub(r"[^0-9A-Z]", "", (v or "").upper()) or None


def find_or_fill_order(manifest, log):
	"""-> (movement order name, None) or (None, why not)."""
	existing = frappe.get_all(
		CMO,
		filters={"manifest": manifest, "container_no": log.container_no, "docstatus": 1},
		pluck="name",
		order_by="creation asc",
	)
	if existing:
		return existing[0], None

	if not log.truck:
		return None, "TANeSW gives no truck for this container, so no Best Pick order can be matched"
	chosen, why = pick_best_pick(manifest, log)
	if not chosen:
		return None, why

	rows = manifest_container(manifest, log.container_no)
	if not rows:
		return (
			None,
			f"Container {log.container_no} is not on manifest {manifest}, or already has a Movement Order",
		)
	row = rows[0]
	if log.bl_no and (row.m_bl_no or "").upper() != log.bl_no.upper():
		return None, f"B/L mismatch: TANeSW says {log.bl_no}, manifest {manifest} has {row.m_bl_no}"

	order = frappe.get_doc(CMO, chosen)
	if (
		not order.manifest
	):  # made before the manifest was known: it comes with the container (best_pick_setup)
		m = (
			frappe.db.get_value(
				"Manifest", manifest, ["vessel_name", "port", "voyage_no", "company"], as_dict=True
			)
			or {}
		)
		order.update(
			{
				"manifest": manifest,
				"ship": m.get("vessel_name"),
				"port": m.get("port"),
				"voyage_no": m.get("voyage_no"),
				"company": order.company or m.get("company"),
			}
		)
	# same five fields the Movement Order screen's "Select Container" sets, then saved as an update
	order.update(
		{
			"container_no": row.container_no,
			"m_bl_no": row.m_bl_no,
			"size": row.container_size,
			"freight_indicator": row.freight_indicator,
			"cargo_type": row.cargo_type,
		}
	)
	order.flags.ignore_permissions = True
	frappe.db.savepoint("tanesw_icd_order")
	frappe.flags.tanesw_best_pick_fill = (
		True  # the one path allowed past best_pick_setup.validate_manifest_change
	)
	try:
		order.save()
	except frappe.ValidationError as e:
		frappe.db.rollback(save_point="tanesw_icd_order")
		frappe.clear_messages()
		return None, f"icd_tz refused to fill {chosen}: {strip_html(str(e))[:300]}"
	finally:
		frappe.flags.tanesw_best_pick_fill = False
	return order.name, None


def _open_best_picks(manifest, log):
	"""Open Best Pick orders for this truck, on this manifest or made before the manifest was known; oldest first.
	The truck must match: it cannot change on a submitted order."""
	return [
		o
		for o in frappe.get_all(
			CMO,
			filters={"best_pick": 1, "docstatus": 1, "container_no": ["is", "not set"]},
			or_filters=[["manifest", "=", manifest], ["manifest", "is", "not set"]],
			fields=["name", "manifest", "truck", "trailer", "driver_license", "transporter", "creation"],
			order_by="creation asc",
		)
		if norm_plate(o.truck) == log.truck
	]


def best_pick_candidates(manifest, log):
	"""Open Best Pick orders on this manifest for this truck, best match first.

	Among several open orders for the same truck (one truck can have several trips, with different drivers), the one Ops made for THIS driver and trailer comes first: driver licence first (names are spelled differently, the
	licence is not), then trailer, then an order made for this manifest, then the oldest."""
	lic, trailer = _norm_licence(log.driver_license), log.trailer
	rows = _open_best_picks(manifest, log)
	rows.sort(
		key=lambda o: (
			o.manifest != manifest,
			not (lic and _norm_licence(o.driver_license) == lic),
			not (trailer and norm_plate(o.trailer) == trailer),
			o.creation,
		)
	)
	return [o.name for o in rows]


def pick_best_pick(manifest, log):
	"""The ONE open Best Pick order this TANeSW truck row belongs to -> (name, None), or (None, why) for the gate clerk.

	Never a guess between two different trips. A reused truck or a mistyped plate must not put the box -- and with it
	the transport payment -- on another transporter's order (PR #714 review, item 16):
	  - an order whose driver licence differs from TANeSW's is another driver's trip: never taken;
	  - several orders left: narrowed by this driver's licence, then the trailer, then an order made for this manifest;
	  - still several, and they differ in trailer, licence or transporter: nothing is filled, the clerk chooses;
	  - several identical ones (the same trip entered twice): the oldest, which is any of them."""
	rows = _open_best_picks(manifest, log)
	if not rows:
		return None, f"No open Best Pick Movement Order for truck {log.truck} on manifest {manifest}"
	lic, trailer = _norm_licence(log.driver_license), log.trailer
	if lic:
		rows = [o for o in rows if _norm_licence(o.driver_license) in (None, lic)]
		if not rows:
			return None, (
				f"The open Best Pick orders for truck {log.truck} are for other drivers (TANeSW licence {lic})"
				" - check at the gate"
			)
	for fits in (
		lambda o: bool(lic) and _norm_licence(o.driver_license) == lic,
		lambda o: bool(trailer) and norm_plate(o.trailer) == trailer,
		lambda o: o.manifest == manifest,
	):
		if len(rows) > 1:
			narrower = [o for o in rows if fits(o)]
			if narrower:
				rows = narrower
	trips = {(norm_plate(o.trailer), _norm_licence(o.driver_license), o.transporter) for o in rows}
	if len(trips) > 1:
		return None, (
			f"{len(rows)} open Best Pick orders fit truck {log.truck} ({', '.join(o.name for o in rows)}) - "
			"choose the right one at the gate"
		)
	return rows[0].name, None


def manifest_container(manifest, container_no):
	"""The container's row on the manifest, if it has no movement order yet.

	Same tables and conditions as icd_tz's get_manifest_details (the Select Container dialog), queried here rather
	than imported: icd_tz is never changed by us, and must not be able to break this link by renaming its helpers.
	"""
	from pypika.functions import Upper

	CD, MB = frappe.qb.DocType("Containers Detail"), frappe.qb.DocType("Master BL")
	return (
		frappe.qb.from_(CD)
		.join(MB)
		.on((MB.parent == CD.parent) & (MB.m_bl_no == CD.m_bl_no))
		.select(
			CD.container_no,
			CD.m_bl_no,
			CD.container_size,
			CD.freight_indicator,
			MB.cargo_classification.as_("cargo_type"),
		)
		.where(
			(CD.parent == manifest)
			& (CD.has_order == 0)
			& (Upper(CD.container_no) == (container_no or "").upper())
		)
		.run(as_dict=True)
	)


def manifest_reception_values(order):
	"""What the Reception screen copies from the manifest in the browser when an order is picked (icd_tz's
	get_container_details): size, weight, volume, seals and destination. A reception made on the server does not run
	that screen code, so it is read here: same tables, same destination rule (B/L place-of-destination code: TZ ->
	Local, CD -> DRC, anything else -> Other; country from the code)."""
	o = frappe.db.get_value(CMO, order, ["manifest", "container_no"], as_dict=True) or {}
	row = frappe.db.get_value(
		"Containers Detail",
		{"parent": o.get("manifest"), "container_no": o.get("container_no")},
		["m_bl_no", "container_size", "volume", "weight", "weight_unit", "seal_no1", "seal_no2", "seal_no3"],
		as_dict=True,
	)
	if not row:
		return {}
	out = {
		"size": row.container_size,
		"volume": row.volume,
		"weight": row.weight,
		"weight_unit": row.weight_unit,
		"seal_no_1": row.seal_no1,
		"seal_no_2": row.seal_no2,
		"seal_no_3": row.seal_no3,
	}
	abbr = frappe.db.get_value(
		"Master BL", {"parent": o.get("manifest"), "m_bl_no": row.m_bl_no}, "place_of_destination"
	)
	if abbr:
		code = str(abbr)[:2]
		out.update(
			abbr_for_destination=abbr,
			place_of_destination={"TZ": "Local", "CD": "DRC"}.get(code, "Other"),
			country_of_destination=frappe.db.get_value("Country", {"code": code.lower()}, "name"),
		)
	return {k: v for k, v in out.items() if v not in (None, "")}


def draft_reception(order, log):
	"""The order's reception: reused if one exists (draft or submitted), created otherwise. When the gate clerk gave
	yard location and clerk on the carry-in screen it is SUBMITTED too; otherwise it stays a draft for them.
	-> (reception name, problem) -- a reception with a problem is a draft that could not be submitted."""
	existing = frappe.db.get_value(
		RECEPTION, {"movement_order": order, "docstatus": ["<", 2]}, ["name", "docstatus"], as_dict=True
	)
	if existing:
		if existing.docstatus == 0 and log.container_location and log.clerk:
			return existing.name, _submit_reception(frappe.get_doc(RECEPTION, existing.name), log)
		return existing.name, None
	doc = frappe.new_doc(RECEPTION)
	doc.movement_order = order  # icd_tz fills container, B/L, manifest, truck, driver... from the order
	doc.update(manifest_reception_values(order))
	if log.seal_no and not doc.get("seal_no_1"):
		doc.seal_no_1 = log.seal_no
	# left for the gate clerk, who checks the box: yard location, clerk, condition
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_permissions = True
	frappe.db.savepoint("tanesw_icd_reception")
	try:
		doc.insert()
	except frappe.ValidationError as e:
		frappe.db.rollback(save_point="tanesw_icd_reception")
		frappe.clear_messages()
		return None, f"icd_tz refused the reception: {strip_html(str(e))[:300]}"
	if log.container_location and log.clerk:
		return doc.name, _submit_reception(doc, log)
	return doc.name, None


def _submit_reception(doc, log):
	"""Fill what only the gate knows and submit through icd_tz's own controller (creates the Container, starts storage,
	applies the last-box-on-the-B/L storage rule, sends the gate-in file). -> None, or why it stayed a draft."""
	doc.container_location = log.container_location
	doc.clerk = log.clerk
	doc.flags.ignore_permissions = True
	frappe.db.savepoint("tanesw_icd_submit")
	try:
		doc.save()
		doc.submit()
	except Exception as e:
		frappe.db.rollback(save_point="tanesw_icd_submit")
		frappe.clear_messages()
		return f"could not submit: {strip_html(str(e))[:250]}"
	return None


# --------------------------------------------------------------------------- carry-in screen
@frappe.whitelist(methods=["POST"])
def carry_in_context():
	"""What the carry-in screen needs to offer 'Receive into ERP': whether it is on, and the user's own employee record
	as the default clerk."""
	require_tanesw_user()
	on = bool(cint(frappe.db.get_single_value(SETTINGS, "enable_icd_link")) and icd_tz_installed())
	return {
		"enabled": on,
		"default_clerk": frappe.db.get_value(
			"Employee", {"user_id": frappe.session.user, "status": "Active"}, "name"
		)
		if on
		else None,
	}


@frappe.whitelist(methods=["POST"])
def receive_reported(crn: Scalar, cri_base_no: Scalar, reception: JSONish):
	"""'Receive into ERP' on a carry-in already reported to TANeSW (made in the portal): nothing is sent to TANeSW,
	the containers' receptions are created from their movement orders and submitted with the gate's details."""
	frappe.has_permission("Container Reception", "create", throw=True)
	r = reception if isinstance(reception, dict) else json.loads(reception or "{}")
	if not r.get("clerk"):
		frappe.throw(frappe._("Choose the Clerk receiving these containers."))
	if not carry_in_context().get("enabled"):
		frappe.throw(frappe._("Tick 'Link Carry-Ins to icd_tz' in TANeSW Settings first."))
	return receive_carry_in(crn, cri_base_no, r)


def require_receiving_rights():
	"""A gate clerk receiving into the ERP must hold icd_tz's own rights for it. The app fills the movement order and
	submits the reception on their behalf; it never lends rights the user does not have (PR #714 review, item 25)."""
	for doctype, ptype in (
		(CMO, "write"),
		("Container Reception", "create"),
		("Container Reception", "submit"),
	):
		if not frappe.has_permission(doctype, ptype):
			frappe.throw(
				frappe._(
					"Receiving into the ERP needs {0} rights on {1}; ask IT for the icd_tz role."
				).format(ptype, doctype),
				frappe.PermissionError,
			)


def receive_carry_in(crn, cri_base_no, reception):
	"""Called by cargo.cri_submit once TANeSW accepted a carry-in made on our screen, with the clerk and yard
	locations the gate clerk entered: link each container on this carry-in to its movement order and create AND submit
	its Container Reception. Anything that does not fit stays a draft / exception with its reason."""
	from tanesw_integration.containers import _facility_code

	r = reception if isinstance(reception, dict) else json.loads(reception or "{}")
	if not (cint(frappe.db.get_single_value(SETTINGS, "enable_icd_link")) and icd_tz_installed()):
		return []
	require_receiving_rights()
	clerk, default_loc, locs = r.get("clerk"), r.get("default_location"), r.get("locations") or {}
	report = {"crn": crn, "criBaseNo": cri_base_no}
	detail = _report_detail(report, _facility_code())
	report["mrn"] = detail.get("mrn")
	names = []
	for row in detail.get("wrhsCriVhclList") or []:
		for cntr, info in parse_cntr_info(row.get("cntrInfo")):
			name = upsert_log(report, row, cntr, info)
			frappe.db.set_value(
				LOG,
				name,
				{"clerk": clerk, "container_location": locs.get(cntr) or default_loc, "received_at_gate": 1},
			)
			names.append((cntr, name))
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one carry-in / container at a time: one refused box must not undo the others
	out = []
	for cntr, name in names:
		status = _process_safely(name)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one carry-in / container at a time: one refused box must not undo the others
		v = frappe.db.get_value(
			LOG, name, ["link_message", "container_reception", "movement_order"], as_dict=True
		)
		out.append(
			{
				"container_no": cntr,
				"status": status,
				"message": v.link_message,
				"container_reception": v.container_reception,
				"movement_order": v.movement_order,
			}
		)
	return out


def _set(name, status, message, **links):
	frappe.db.set_value(
		LOG,
		name,
		{
			"link_status": status,
			"link_message": (message or "")[:500],
			"last_processed": now_datetime(),
			**{k: v for k, v in links.items() if v},
		},
	)
	return status


def _record(stats):
	try:
		frappe.db.set_single_value(
			SETTINGS,
			{"icd_link_last_run": now_datetime(), "icd_link_last_result": json.dumps(stats, default=str)},
		)
	except Exception:
		frappe.log_error(title="TANeSW ICD link: could not record run", message=frappe.get_traceback())
	return stats
