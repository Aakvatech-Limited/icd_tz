"""Container tracking for our ICD (TANeSW Container records -> container reports).

For every vessel allocated to us (TANeSW Vessel Allocation, see allocations.py) the job reads our B/Ls, then each
B/L's container list from TANeSW Cargo Tracking. The container list already carries each container's current
event code, so the full history (cntr-dtl, one call per container) is only fetched for new containers or when
that code changes. Containers received at our ICD are marked complete and never polled again.

Milestones are TANeSW Cargo Tracking event codes :
  B21 Discharge Result Report Approved   -> landed at the terminal: port dwell starts
  F03 ICD Transfer Declaration Approved  -> declared to our ICD
  C61 Gate Out Confirm (at the terminal) -> left the port, in transit to us: port dwell stops
  C03 Carry In Report Approved (our ICD) -> received at our ICD
  C03 at ANOTHER ICD                      -> diverted: it went to someone else's yard

After it is received the container keeps being followed until TANeSW shows it LEAVING our ICD (an exit event at our
warehouse: C53 / C60 / C61 / C62, "Gate Out", or a carry-out that is not just its approval -- the same rule as the
old GitHub delivery tracker: "Carry Out Report Approved" comes days before the exit).
Received containers are re-read in a rotating sweep rather than by walking their vessel's B/Ls every hour, and
containers that were already in our yard before tracking started are seeded from ERP (icd_tz) by their B/L.
anomalies.py compares all of this with the ERP.

A diverted container can also drop off our B/L list (the B/L's delivery place is changed to another ICD). Open
containers of a vessel that were not seen on our B/Ls in a run are therefore re-read on their own, so they cannot
sit as "In Transit" forever.
"""

import json
from contextlib import contextmanager

import frappe
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime, nowdate

from tanesw_integration.credentials import watcher_accounts
from tanesw_integration.outage import log_error as _outage_log_error

DOCTYPE = "TANeSW Container"
SETTINGS = "TANeSW Settings"
JOB_ID = "tanesw_container_sync"
MAX_DETAIL_CALLS = 400  # per run, to keep the load on TANeSW bounded

DISCHARGED, DECLARED, GATE_OUT, CARRY_IN = "B21", "F03", "C61", "C03"
EXIT_CODES = ("C53", "C60", "C61", "C62")
FULL_EVERY_MINUTES = 55  # ships not yet arrived, received-box sweep and yard seeding: about once an hour
FULL_RUN_KEY = "tanesw_container_full_run_at"
STATUS_RANK = {"Not Discharged": 0, "At Terminal": 1, "In Transit": 2, "Received at ICD": 3}
SWEEP_LIMIT = 150  # received containers re-read per run, oldest-read first
SEED_LIMIT = 40  # ERP yard containers looked up per run
SEED_RETRY_HOURS = 24  # a container TANeSW did not find is not searched again for this long
LOT_LIMIT = 60  # LCL cargo-lot lookups per run


# --------------------------------------------------------------------------- scheduling
def enqueue_container_sync():
	from tanesw_integration import outage

	if outage.paused():
		return  # TANeSW is down: skipped until the pause expires (outage.py)
	frappe.enqueue(
		"tanesw_integration.containers.sync_containers",
		queue="long",
		timeout=3000,
		job_id=JOB_ID,
		deduplicate=True,
	)


@frappe.whitelist(methods=["POST"])
def run_now():
	frappe.only_for("System Manager")
	enqueue_container_sync()
	return frappe._("Container tracking queued. Refresh TANeSW Settings in a few minutes to see the result.")


# --------------------------------------------------------------------------- main
def sync_containers():
	settings = frappe.get_single(SETTINGS)
	if not settings.enable_read_sync:
		return _record({"status": "disabled"})
	accounts = watcher_accounts(settings)
	if not accounts:
		return _record({"status": "not_configured"})

	days = cint(settings.get("container_tracking_days")) or 45
	full = _full_run_due()
	mrns = _mrns_to_track(days, full)
	stats = {
		"status": "ok",
		"pass": "full" if full else "live",
		"vessels": len(mrns),
		"bls": 0,
		"containers": 0,
		"new": 0,
		"refreshed": 0,
		"unchanged": 0,
		"failed": 0,
		"detail_calls": 0,
	}
	budget = {"left": MAX_DETAIL_CALLS}

	with _as_watcher(accounts) as account:
		if not account:
			return _record({"status": "login_failed"})
		stats["account"] = account
		code = _facility_code()
		for mrn in mrns:
			try:
				_sync_mrn(mrn, code, stats, budget)
			except Exception:
				stats["failed"] += 1
				_outage_log_error(
					title=f"TANeSW container sync failed: {mrn}", message=frappe.get_traceback()
				)
				frappe.clear_messages()
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background job: keep each finished vessel if a later one fails

		# following boxes after receipt, seeding older yard boxes and LCL lots read icd_tz and feed the anomaly
		# step: they run only when "Track TANeSW Anomalies" is on (the ICD server runs a different icd_tz)
		from tanesw_integration.anomalies import enabled as anomalies_on

		for step in (_sweep_received, _seed_yard) if full and anomalies_on() else ():
			try:
				step(code, stats, budget)
			except Exception:
				stats["failed"] += 1
				_outage_log_error(
					title=f"TANeSW container sync: {step.__name__} failed", message=frappe.get_traceback()
				)
				frappe.clear_messages()
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background job: keep each finished vessel if a later one fails

	_refresh_terminal_dwell()
	try:
		from tanesw_integration.anomalies import track_anomalies

		stats["anomalies"] = track_anomalies()
	except Exception:
		frappe.log_error(title="TANeSW anomaly tracking failed", message=frappe.get_traceback())
		frappe.clear_messages()
	if budget["left"] <= 0:
		stats["status"] = "partial (detail call limit reached; continues next run)"
	if full:
		frappe.cache().set_value(FULL_RUN_KEY, str(now_datetime()))
	return _record(stats)


def _full_run_due():
	last = frappe.cache().get_value(FULL_RUN_KEY)
	return not last or (now_datetime() - get_datetime(last)).total_seconds() >= FULL_EVERY_MINUTES * 60


def _mrns_to_track(days, full=True):
	"""Vessels whose B/Ls are walked this run, the ones with boxes on the move first (so a partial run spends its
	detail calls where the status is changing). The 15-minute pass skips ships that have not arrived yet."""
	since, today = add_days(nowdate(), -days), getdate(nowdate())
	vessels = frappe.get_all(
		"TANeSW Vessel Allocation", filters={"arrival_date": [">=", since]}, fields=["name", "arrival_date"]
	)
	recent = [v.name for v in vessels if full or (v.arrival_date and getdate(v.arrival_date) <= today)]
	moving = frappe.get_all(
		DOCTYPE,
		filters={"tracking_complete": 0, "status": ["in", ["At Terminal", "In Transit"]]},
		pluck="mrn",
		distinct=True,
	)
	# received containers are followed by _sweep_received, not by walking their vessel's B/Ls every run
	open_ = (
		frappe.get_all(
			DOCTYPE,
			filters={"tracking_complete": 0, "status": ["!=", "Received at ICD"]},
			pluck="mrn",
			distinct=True,
		)
		if full
		else []
	)
	return list(dict.fromkeys([m for m in moving + recent + open_ if m]))


def advance_from_carry_in(mrn, cntr, left_port, entered, carry_in_on=None):
	"""Real-time status from the 5-minute carry-in check: a handover that says the truck left the port, or a carry-in
	that says it entered our gate, moves the container's status forward at once instead of waiting for the next
	container sync. Never backwards; exact event times are left to the sync (it re-reads the box once its TANeSW
	event changes)."""
	name = f"{(mrn or '').upper()}-{cntr}"
	row = frappe.db.get_value(DOCTYPE, name, ["status", "received_on"], as_dict=True)
	if not row or not (left_port or entered):
		return None
	target = "Received at ICD" if entered else "In Transit"
	if row.status == "Diverted" and not entered:
		return None
	if STATUS_RANK.get(row.status, -1) >= STATUS_RANK[target] and row.status != "Diverted":
		return None
	values = {
		"status": target,
		"last_event": "Entered our gate (carry-in)" if entered else "Left the port (handover)",
	}
	if entered and not row.received_on and carry_in_on:
		values["received_on"] = carry_in_on
	if entered:
		values.update(diverted_to=None, diverted_on=None)
	frappe.db.set_value(DOCTYPE, name, values, update_modified=False)
	return target


def _sync_mrn(mrn, code, stats, budget):
	from tanesw_integration import api as legacy
	from tanesw_integration.cargo import tracking_detail

	vessel = (
		frappe.db.get_value(
			"TANeSW Vessel Allocation",
			mrn,
			["name", "vessel_name", "voyage_number", "arrival_date"],
			as_dict=True,
		)
		or {}
	)
	seen = set()
	for bl in legacy._our_bls(mrn, code):
		crn = bl.get("crn")
		if not crn or not cint(bl.get("cntrCnt")):
			continue
		stats["bls"] += 1
		detail = tracking_detail(crn) or {}
		for c in detail.get("blCntrLst") or []:
			cntr = (c.get("cntrNo") or "").strip().upper()
			if not cntr:
				continue
			stats["containers"] += 1
			# One record per container per manifest: the same container can sit on two B/Ls of one manifest
			# (one container on two B/L rows), and must count once.
			name = f"{mrn}-{cntr}"
			seen.add(name)
			existing = frappe.db.get_value(
				DOCTYPE, name, ["tracking_complete", "last_event_code"], as_dict=True
			)
			if existing and (
				existing.tracking_complete or existing.last_event_code == c.get("cagTrkngPrcssCd")
			):
				stats["unchanged"] += 1
				continue
			if budget["left"] <= 0:
				continue
			budget["left"] -= 1
			stats["detail_calls"] += 1
			_upsert(name, crn, cntr, bl, detail, c, vessel, code)
			stats["refreshed" if existing else "new"] += 1
	if seen:  # an empty B/L list is more likely a TANeSW hiccup than every B/L moving away at once
		back = frappe.get_all(
			DOCTYPE,
			filters={"mrn": mrn, "name": ["in", list(seen)], "removed_from_allocation_on": ["is", "set"]},
			pluck="name",
		)
		for name in back:  # TANeSW lists it on our B/Ls again: ours after all
			frappe.db.set_value(DOCTYPE, name, "removed_from_allocation_on", None, update_modified=False)
		_recheck_unseen(mrn, seen, code, stats, budget)


def _recheck_unseen(mrn, seen, code, stats, budget):
	"""Open containers of this vessel that our B/Ls no longer list: their B/L was most likely moved to another ICD.
	Re-read each one's own history (we keep its CRN), so a carry-in at another ICD marks it Diverted."""
	from tanesw_integration.cargo import tracking_container

	for r in frappe.get_all(
		DOCTYPE,
		filters={"mrn": mrn, "tracking_complete": 0},
		fields=["name", "crn", "container_no", "status", "removed_from_allocation_on"],
	):
		if r.name in seen:
			continue
		# off our B/Ls = TANeSW reduced our allocation; recorded at once, before (and whatever) the re-read finds
		if not r.removed_from_allocation_on and r.status != "Received at ICD":
			frappe.db.set_value(
				DOCTYPE, r.name, "removed_from_allocation_on", now_datetime(), update_modified=False
			)
			stats["removed_from_allocation"] = stats.get("removed_from_allocation", 0) + 1
		if not r.crn or budget["left"] <= 0:
			continue
		budget["left"] -= 1
		stats["detail_calls"] += 1
		stats["off_our_bls"] = stats.get("off_our_bls", 0) + 1
		history = (tracking_container(r.crn, r.container_no) or {}).get("cntrPrcssLst") or []
		if not history:
			continue
		values = milestones(history, code)
		values["last_synced"] = now_datetime()
		doc = frappe.get_doc(DOCTYPE, r.name)
		doc.update(values)
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)


def _upsert(name, crn, cntr, bl, detail, current, vessel, code):
	from tanesw_integration.cargo import tracking_container

	history = (tracking_container(crn, cntr) or {}).get("cntrPrcssLst") or []
	m = milestones(history, code)
	values = {
		"container_no": cntr,
		"crn": crn,
		"mrn": bl.get("mrn") or detail.get("mrn"),
		"bl_no": bl.get("mblNo") or detail.get("mblNo"),
		"hbl_no": bl.get("hblNo") if bl.get("hblNo") != "SIMPLE" else None,
		"vessel_allocation": vessel.get("name"),
		"vessel_name": vessel.get("vessel_name") or detail.get("vsslNm"),
		"voyage_number": vessel.get("voyage_number") or detail.get("vygNo"),
		"arrival_date": vessel.get("arrival_date")
		or _date(detail.get("actlArvlDt") or detail.get("xptdArvlDt")),
		"container_size": current.get("cntrSizeCd"),
		"freight_indicator": current.get("frghIdcrCd"),
		"seal_no": current.get("sealNo1"),
		"terminal": current.get("stckWrhsCd") or current.get("lastGodsLoctCd"),
		"last_event_code": current.get("cagTrkngPrcssCd"),
		"last_event": current.get("cagTrkngPrcssCdNm"),
		"last_synced": now_datetime(),
		**m,
	}
	values["mrn"] = name.rsplit("-", 1)[0]
	doc = frappe.get_doc(DOCTYPE, name) if frappe.db.exists(DOCTYPE, name) else frappe.new_doc(DOCTYPE)
	doc.update(values)
	doc.flags.ignore_links = True
	doc.save(ignore_permissions=True) if not doc.is_new() else doc.insert(ignore_permissions=True)


def milestones(history, our_code, now=None):
	"""Container history (newest first, as TANeSW returns it) -> milestone dates, status and port dwell days."""
	first = {}
	elsewhere = None  # first carry-in at ANOTHER ICD: the container was diverted
	left = None  # first exit from OUR ICD: the container has left our yard
	for ev in sorted(history, key=lambda e: e.get("prcssDt") or ""):
		cd, wh = ev.get("cagTrkngPrcssCd"), (ev.get("wrhsCd") or "").upper()
		if wh == our_code and is_exit_event(cd, ev.get("cagTrkngPrcssCdNm")):
			left = left or ev
			continue  # leaving OUR ICD is not leaving the port
		if cd == CARRY_IN and wh != our_code:
			elsewhere = elsewhere or ev
			continue
		first.setdefault(cd, ev)

	def dt(cd):
		return get_datetime(first[cd]["prcssDt"]) if cd in first and first[cd].get("prcssDt") else None

	discharged, declared, gate_out, received = dt(DISCHARGED), dt(DECLARED), dt(GATE_OUT), dt(CARRY_IN)
	if (
		received and not left
	):  # crossed a border after it reached us: it left our yard (old tracker, same rule)
		left = next(
			(
				e
				for e in sorted(history, key=lambda e: e.get("prcssDt") or "")
				if "Border Point Confirm" in str(e.get("cagTrkngPrcssCdNm") or "")
				and e.get("prcssDt")
				and get_datetime(e["prcssDt"]) > received
			),
			None,
		)
	diverted_on = get_datetime(elsewhere["prcssDt"]) if elsewhere and elsewhere.get("prcssDt") else None
	if received:
		status = "Received at ICD"  # reached us in the end, even if another ICD carried it in first
	elif elsewhere:
		status = "Diverted"
	elif gate_out:
		status = "In Transit"
	elif discharged:
		status = "At Terminal"
	else:
		status = "Not Discharged"
	latest = max(history, key=lambda e: e.get("prcssDt") or "", default={})
	return {
		"status": status,
		"discharged_on": discharged,
		"declared_on": declared,
		"gate_out_on": gate_out,
		"received_on": received,
		"icd_declaration_no": (first.get(DECLARED) or {}).get("dclrNo"),
		"carry_in_report_no": (first.get(CARRY_IN) or {}).get("dclrNo"),
		"dwell_days": dwell_days(discharged, gate_out, now),
		"last_event_on": get_datetime(latest["prcssDt"]) if latest.get("prcssDt") else None,
		"left_icd_on": get_datetime(left["prcssDt"]) if received and left and left.get("prcssDt") else None,
		"left_icd_event": (left.get("cagTrkngPrcssCdNm") or left.get("cagTrkngPrcssCd"))
		if received and left
		else None,
		"diverted_to": None
		if received or not elsewhere
		else (elsewhere.get("wrhsCdNm") or elsewhere.get("wrhsCd") or "")[:140],
		"diverted_on": None if received else diverted_on,
		# finished once it has left our yard, or another ICD received it
		"tracking_complete": 1 if (received and left) or (elsewhere and not received) else 0,
	}


def is_exit_event(code, name):
	"""A TANeSW event that is the box physically leaving a yard (same rule as the old GitHub delivery tracker)."""
	name = str(name or "")
	if str(code or "").strip() in EXIT_CODES or "Gate Out" in name:
		return True
	# a carry-out report being submitted or approved is paperwork, not the box leaving (both come
	# minutes to days before the box's Gate Out Confirm, approval as the old tracker found)
	return "Carry Out" in name and "Approv" not in name and "Submit" not in name


def _history_values(crn, cntr, code):
	from tanesw_integration.cargo import tracking_container

	history = (tracking_container(crn, cntr) or {}).get("cntrPrcssLst") or []
	return (milestones(history, code) if history else None), history


def _sweep_received(code, stats, budget):
	"""Received containers that have not left our ICD yet, oldest-read first, within the call budget."""
	rows = frappe.get_all(
		DOCTYPE,
		filters={"status": "Received at ICD", "tracking_complete": 0},
		fields=["name", "crn", "container_no"],
		order_by="last_synced asc",
		limit=min(SWEEP_LIMIT, budget["left"]),
	)
	for r in rows:
		if not r.crn or budget["left"] <= 0:
			continue
		budget["left"] -= 1
		stats["detail_calls"] += 1
		values, history = _history_values(r.crn, r.container_no, code)
		if not values:
			continue
		if not values.get("left_icd_on") and budget["left"] > 0:
			budget["left"] -= 1
			stats["detail_calls"] += 1
			exit_ = bl_level_exit(r.crn, code)
			if exit_:
				values.update(left_icd_on=exit_[0], left_icd_event=f"{exit_[1]} (B/L)", tracking_complete=1)
		if _stripped_here(history, code):
			values["lcl_lots"] = json.dumps(_check_lots(r, code, stats, budget), default=str)
		values["last_synced"] = now_datetime()
		doc = frappe.get_doc(DOCTYPE, r.name)
		doc.update(values)
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)
		stats["swept"] = stats.get("swept", 0) + 1
		if values.get("left_icd_on"):
			stats["left_icd"] = stats.get("left_icd", 0) + 1


def bl_level_exit(crn, code):
	"""(when, event) the B/L of this CRN left our ICD, from its whole-B/L steps -- ONLY when the B/L holds a single
	box, so a sister box's exit is never taken for this one (old tracker rule, after the 3 Nov 2026 false departures:
	19 of 39 alerts sat on multi-box B/Ls). An LCL cargo lot's House-B/L CRN is such a single-box B/L."""
	from tanesw_integration.cargo import tracking_detail

	d = tracking_detail(crn) or {}
	if len(d.get("blCntrLst") or []) > 1:
		return None
	for s in sorted(d.get("blPrcssLst") or [], key=lambda s: s.get("prcssDt") or ""):
		name = str(s.get("cagTrkngPrcssCdNm") or "")
		at_ours = (s.get("wrhsCd") or "").upper() == code
		if s.get("prcssDt") and (
			(at_ours and is_exit_event(s.get("cagTrkngPrcssCd"), name)) or "Border Point Confirm" in name
		):
			return get_datetime(s["prcssDt"]), name or s.get("cagTrkngPrcssCd")
	return None


def _stripped_here(history, code):
	return any(
		(e.get("wrhsCd") or "").upper() == code and "Stripping" in str(e.get("cagTrkngPrcssCdNm") or "")
		for e in history or []
	)


def _check_lots(r, code, stats, budget):
	"""LCL box stripped at our ICD: the CARGO leaves per House B/L, the box itself may never show an exit. Look up
	each ERP cargo lot (icd_tz Container with h_bl_no) on TANeSW by its House B/L and record when it left."""
	from tanesw_integration.cargo import tracking_search

	old = {l["h_bl_no"]: l for l in json.loads(frappe.db.get_value(DOCTYPE, r.name, "lcl_lots") or "[]")}
	if "icd_tz" not in frappe.get_installed_apps():
		return list(old.values())
	mrn = frappe.db.get_value(DOCTYPE, r.name, "mrn")
	manifests = frappe.get_all("Manifest", filters={"mrn": mrn, "docstatus": 1}, pluck="name")
	lots = (
		frappe.get_all(
			"Container",
			filters={
				"container_no": r.container_no,
				"manifest": ["in", manifests or ["-"]],
				"has_hbl": 1,
				"docstatus": ["<", 2],
			},
			fields=["h_bl_no"],
		)
		if manifests
		else []
	)
	out = []
	for lot in lots:
		hbl = lot.h_bl_no
		rec = old.get(hbl) or {"h_bl_no": hbl, "crn": None, "left_on": None, "event": None}
		if not rec["left_on"] and stats.get("lot_calls", 0) < LOT_LIMIT and budget["left"] > 1:
			if not rec["crn"]:
				found = tracking_search(srch_bl_no=hbl) or {}
				stats["lot_calls"] = stats.get("lot_calls", 0) + 1
				budget["left"] -= 1
				rec["crn"] = (
					(found.get("detail") or {}).get("crn")
					if found.get("count") == 1
					else next(
						(
							x.get("crn")
							for x in found.get("crns") or []
							if str(x.get("mrn") or "").upper() == str(mrn).upper()
						),
						None,
					)
				)
			if rec["crn"]:
				exit_ = bl_level_exit(rec["crn"], code)
				stats["lot_calls"] = stats.get("lot_calls", 0) + 1
				budget["left"] -= 1
				if exit_:
					rec["left_on"], rec["event"] = exit_
		out.append(rec)
	return out


def _seed_yard(code, stats, budget):
	"""Containers already in our yard per the ERP (icd_tz Container, not Delivered) that tracking has never read:
	find them on TANeSW by their B/L and start tracking them. Needs icd_tz on this site."""
	from tanesw_integration.cargo import tracking_search

	if "icd_tz" not in frappe.get_installed_apps():
		return
	from frappe.query_builder import DocType, Order
	from frappe.query_builder.functions import IfNull
	from pypika.terms import ExistsCriterion

	C, M, T = DocType("Container"), DocType("Manifest"), DocType("TANeSW Container")
	tracked = frappe.qb.from_(T).select(T.name).where((T.container_no == C.container_no) & (T.mrn == M.mrn))
	rows = (
		frappe.qb.from_(C)
		.join(M)
		.on(M.name == C.manifest)
		.select(C.container_no, C.m_bl_no, M.mrn, M.vessel_name, M.voyage_no, M.arrival_date)
		.where(
			(C.status != "Delivered")
			& (C.docstatus < 2)
			& (IfNull(C.has_hbl, 0) == 0)
			& (IfNull(C.container_no, "") != "")
			& (IfNull(M.mrn, "") != "")
			& ExistsCriterion(tracked).negate()
		)
		.orderby(C.received_date, order=Order.asc)
		.limit(500)
		.run(as_dict=True)
	)
	cache = frappe.cache()
	tried = 0
	for r in rows:
		if tried >= SEED_LIMIT or budget["left"] <= 1:
			break
		key = f"tanesw:seed_miss:{r.mrn}:{r.container_no}"
		if cache.get_value(key):
			continue
		tried += 1
		found = tracking_search(srch_bl_no=r.m_bl_no) or {}
		budget["left"] -= 1
		crns = (
			[found["detail"].get("crn")]
			if found.get("count") == 1 and found.get("detail")
			else [
				x.get("crn")
				for x in found.get("crns") or []
				if str(x.get("mrn") or r.mrn).upper() == r.mrn.upper()
			]
		)
		values = None
		for crn in [c for c in crns if c][:2]:
			budget["left"] -= 1
			stats["detail_calls"] += 1
			values, _ = _history_values(crn, r.container_no, code)
			if values:
				break
		if not values:
			cache.set_value(key, 1, expires_in_sec=SEED_RETRY_HOURS * 3600)
			continue
		doc = frappe.new_doc(DOCTYPE)
		doc.update(
			{
				"container_no": r.container_no,
				"crn": crn,
				"mrn": r.mrn,
				"bl_no": r.m_bl_no,
				"vessel_allocation": r.mrn if frappe.db.exists("TANeSW Vessel Allocation", r.mrn) else None,
				"vessel_name": r.vessel_name,
				"voyage_number": r.voyage_no,
				"arrival_date": r.arrival_date,
				"last_synced": now_datetime(),
				**values,
			}
		)
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True, set_name=f"{r.mrn}-{r.container_no}")
		stats["seeded"] = stats.get("seeded", 0) + 1


def dwell_days(discharged, gate_out, now=None):
	if not discharged:
		return None
	end = gate_out or now or now_datetime()
	return round(max((end - discharged).total_seconds(), 0) / 86400, 1)


def _refresh_terminal_dwell():
	"""Containers still at the terminal keep accruing dwell between polls."""
	now = now_datetime()
	for r in frappe.get_all(DOCTYPE, filters={"status": "At Terminal"}, fields=["name", "discharged_on"]):
		if r.discharged_on:
			frappe.db.set_value(
				DOCTYPE,
				r.name,
				"dwell_days",
				dwell_days(get_datetime(r.discharged_on), None, now),
				update_modified=False,
			)


# --------------------------------------------------------------------------- helpers
def _facility_code():
	from tanesw_integration import api as legacy

	return legacy._our_facility_code()


def _date(v):
	return getdate(v) if v else None


@contextmanager
def _as_watcher(accounts):
	"""Run TANeSW calls with the first enabled watcher account (same accounts as the allocation watcher)."""
	from tanesw_integration.credentials import SHARED
	from tanesw_integration.session_utils import as_user

	for name in accounts:
		if (
			name == SHARED
		):  # the shared login on TANeSW Settings: read TANeSW as the system, not as the caller
			with as_user("Administrator"):
				yield name
			return
		acc = frappe.db.get_value("TANeSW User Account", name, ["user", "enabled"], as_dict=True)
		if acc and acc.enabled and acc.user:
			# as_user, not set_user: this also runs inside report requests, where set_user breaks the browser login
			with as_user(acc.user):
				yield name
			return
	yield None


def _record(stats):
	try:
		frappe.db.set_single_value(
			SETTINGS,
			{"container_last_sync": now_datetime(), "container_last_result": json.dumps(stats, default=str)},
		)
	except Exception:
		frappe.log_error(title="TANeSW container sync: could not record run", message=frappe.get_traceback())
	return stats
