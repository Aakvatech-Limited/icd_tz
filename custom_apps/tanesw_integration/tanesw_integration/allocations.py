"""Vessel allocation watcher.

Every 15 minutes (hooks.scheduler_events -> enqueue_allocation_watch) the "Our cargo" manifest scan runs as the
background watcher account. Each manifest with B/Ls delivered to our ICD is kept as a TANeSW Vessel Allocation.
The first complete run is a silent baseline; afterwards a new vessel or a change in its B/L / container counts
creates a bell notification AND an email for every TANeSW user.

Manifests TANeSW does not answer for (``unverified``) are never treated as ours, never treated as removed, and
never alerted on. If one was unverified during the baseline it is seeded silently once it verifies, so the
baseline cannot produce a burst of false "new" alerts later.
"""

import json

import frappe
from frappe.utils import add_days, cint, escape_html, get_url, getdate, now_datetime, nowdate

from tanesw_integration.cargo import manifest_info_list
from tanesw_integration.credentials import watcher_accounts
from tanesw_integration.outage import log_error as _outage_log_error

DOCTYPE = "TANeSW Vessel Allocation"
SETTINGS = "TANeSW Settings"
JOB_ID = "tanesw_allocation_watch"


# --------------------------------------------------------------------------- scheduling
def enqueue_allocation_watch():
	"""Scheduler entry point. The scan reads every manifest's B/L list (about a minute for a busy week's
	manifests), so it runs on the long queue with its own timeout instead
	of the default queue's 300 s, and never twice at the same time."""
	from tanesw_integration import outage

	if outage.paused():
		return  # TANeSW is down: skipped until the pause expires (outage.py)
	frappe.enqueue(
		"tanesw_integration.allocations.watch_allocations",
		queue="long",
		timeout=1800,
		job_id=JOB_ID,
		deduplicate=True,
	)


@frappe.whitelist(methods=["POST"])
def run_now():
	"""'Run Allocation Check Now' button on TANeSW Settings (System Manager only)."""
	frappe.only_for("System Manager")
	enqueue_allocation_watch()
	return _("Allocation check queued. Refresh TANeSW Settings in a minute to see the result.")


def _(text):
	return frappe._(text)


# --------------------------------------------------------------------------- main run
def watch_allocations():
	settings = frappe.get_single(SETTINGS)
	if not settings.enable_read_sync:
		return _record_run({"status": "disabled"})

	accounts = watcher_accounts(settings)
	if not accounts:
		return _record_run({"status": "not_configured"})

	result, account = _scan_using_accounts(accounts, add_days(nowdate(), -7), add_days(nowdate(), 30))
	if result is None:
		return _record_run({"status": "scan_failed"})

	initialized = cint(settings.allocation_watcher_initialized)
	pending = set(_load_pending(settings))  # MRNs that were unverified during the baseline
	unverified = [u.get("mrn") for u in (result.get("unverified") or []) if u.get("mrn")]
	stats = {
		"status": "ok",
		"account": account,
		"scanned": cint(result.get("scanned")),
		"unverified": len(unverified),
		"seeded": 0,
		"new": 0,
		"changed": 0,
		"unchanged": 0,
		"notified": 0,
	}
	alerts = []

	for row in result.get("content") or []:
		row.setdefault("facility_code", result.get("facility_code"))
		mrn = row.get("mrn")
		if not mrn:
			continue

		if not frappe.db.exists(DOCTYPE, mrn):
			silent = not initialized or mrn in pending
			event = "Baseline" if silent else "New Allocation"
			allocation = _insert_allocation(row, account, event)
			pending.discard(mrn)
			stats["seeded" if silent else "new"] += 1
			if not silent:
				alerts.append((allocation, event, None))
			continue

		allocation = frappe.get_doc(DOCTYPE, mrn)
		old_counts = (cint(allocation.bl_count), cint(allocation.container_count))
		new_counts = (cint(row.get("our_bl_count")), cint(row.get("our_cntr_count")))
		# A record first created from TANeSW's Expected ICD list (no B/L scan yet, no watcher_account) gets its
		# B/L counts silently the first time the scan sees it — that is not a change worth alerting on.
		first_scan = not allocation.watcher_account
		changed = old_counts != new_counts and not first_scan
		_update_allocation(allocation, row, account, changed)
		stats["changed" if changed else "unchanged"] += 1
		if changed and initialized:
			alerts.append((allocation, "Allocation Changed", old_counts))

	if not initialized:
		# Baseline is done once the scan worked; manifests TANeSW did not answer for are remembered so they are
		# seeded silently later instead of blocking initialisation forever (the previous rule: one unanswered
		# manifest in the 37-day window kept the watcher in baseline mode, so nobody was ever notified).
		pending.update(unverified)
		frappe.db.set_single_value(SETTINGS, "allocation_watcher_initialized", 1)
	_save_pending(pending)

	for allocation, event, old_counts in alerts:
		stats["notified"] += _queue_notification(allocation, event, old_counts) or 0

	if alerts and cint(frappe.db.get_single_value(SETTINGS, "enable_manifest_sync")):
		# a new or changed allocation: compare that vessel's manifest now (manifest_sync picks only changed vessels)
		from tanesw_integration.manifest_sync import enqueue_manifest_sync

		enqueue_manifest_sync()

	try:
		_watch_landed(accounts, stats)
	except Exception:
		stats["landed_check"] = "failed"
		_outage_log_error(title="TANeSW landed-container check failed", message=frappe.get_traceback())
		frappe.clear_messages()

	return _record_run(stats)


# --------------------------------------------------------------------------- containers ready to declare
def _watch_landed(accounts, stats):
	"""'Ready to declare' alerts: the same figures the New Declaration popup is built from.

	TANeSW's Expected ICD Transfer list gives, per manifest for our ICD, Total / Target / Declared, where Target =
	containers landed (Discharge Result Report approved) and Declared = containers already declared to us
	Target going up = new containers can now be declared.
	The first time a manifest's Target is seen it is recorded silently (baseline)."""
	from tanesw_integration.cargo import icd_expected_list
	from tanesw_integration.containers import _as_watcher

	rows, page = [], 0
	with _as_watcher(accounts) as account:
		if not account:
			stats["landed_check"] = "login_failed"
			return
		while page < 20:
			res = (
				icd_expected_list(
					add_days(nowdate(), -30), add_days(nowdate(), 7), "C", None, None, page, 100
				)
				or {}
			)
			rows += res.get("content") or []
			if page + 1 >= cint((res.get("page") or {}).get("totalPages") or 1):
				break
			page += 1

	# Int columns are created NOT NULL DEFAULT 0, so landed_count cannot tell "never seen" from "0 landed".
	# One explicit flag instead: the first run after deploy records every vessel's current Target silently;
	# after that, any rise (including 0 -> N on a vessel first seen later) is a real new landing.
	initialized = cint(frappe.db.get_single_value(SETTINGS, "landed_watch_initialized"))
	stats.update(
		{"landed_checked": len(rows), "landed_alerts": 0, "landed_baseline": 0 if initialized else 1}
	)
	for x in rows:
		mrn = x.get("mrn")
		if not mrn:
			continue
		landed, declared, total = cint(x.get("trgtCnt")), cint(x.get("dclrCnt")), cint(x.get("totCnt"))
		if frappe.db.exists(DOCTYPE, mrn):
			allocation = frappe.get_doc(DOCTYPE, mrn)
		else:  # in TANeSW's list for our ICD but not seen by the B/L scan yet: record it, no alert
			allocation = frappe.get_doc(
				{
					"doctype": DOCTYPE,
					"mrn": mrn,
					"first_seen": now_datetime(),
					"last_seen": now_datetime(),
					"last_changed": now_datetime(),
					"vessel_name": x.get("vsslNm"),
					"voyage_number": x.get("vygNo"),
					"arrival_date": getdate(x["arvlDt"]) if x.get("arvlDt") else None,
					"container_count": total,
					"last_event": "Baseline",
				}
			).insert(ignore_permissions=True)
		baseline = not initialized
		old_landed = cint(allocation.get("landed_count"))
		allocation.landed_count, allocation.declared_count = landed, declared
		allocation.available_count = max(landed - declared, 0)
		if not baseline and landed > old_landed:
			allocation.last_event = "Containers Landed"
			allocation.last_landed_change = now_datetime()
			allocation.save(ignore_permissions=True)
			stats["landed_alerts"] += 1
			stats["notified"] = stats.get("notified", 0) + (
				_queue_notification(allocation, "Containers Landed", (old_landed,)) or 0
			)
		else:
			allocation.save(ignore_permissions=True)

	if not initialized and rows:  # an empty answer is not a baseline: keep waiting for real figures
		frappe.db.set_single_value(SETTINGS, "landed_watch_initialized", 1)


def _record_run(stats):
	"""Leave a visible trace of every run on TANeSW Settings (the scheduled job keeps no log of its own)."""
	try:
		frappe.db.set_single_value(
			SETTINGS,
			{
				"allocation_last_run": now_datetime(),
				"allocation_last_result": json.dumps(stats, default=str),
			},
		)
	except Exception:
		frappe.log_error(
			title="TANeSW allocation watcher: could not record run", message=frappe.get_traceback()
		)
	return stats


def _load_pending(settings):
	try:
		return json.loads(settings.get("allocation_baseline_pending") or "[]")
	except Exception:
		return []


def _save_pending(pending):
	frappe.db.set_single_value(SETTINGS, "allocation_baseline_pending", json.dumps(sorted(pending)))


# --------------------------------------------------------------------------- scanning
def _scan_using_accounts(accounts, date_from, date_to):
	for account in accounts:
		try:
			return _scan_as_account(account, date_from, date_to), account
		except Exception:
			# log_error(title, message) — the old call passed them the other way round.
			_outage_log_error(
				title=f"TANeSW allocation scan failed for {account}", message=frappe.get_traceback()
			)
			frappe.clear_messages()
	return None, None


def _scan_as_account(account_name, date_from, date_to):
	from tanesw_integration.credentials import SHARED
	from tanesw_integration.session_utils import as_user

	if account_name == SHARED:
		with as_user("Administrator"):
			return manifest_info_list(date_from, date_to, our_only="ours", page=0, size=1000)
	account = frappe.get_doc("TANeSW User Account", account_name)
	if not account.enabled:
		raise frappe.ValidationError(f"TANeSW User Account {account_name} is disabled")

	from tanesw_integration.session_utils import as_user

	with as_user(account.user):
		return manifest_info_list(date_from, date_to, our_only="ours", page=0, size=1000)


# --------------------------------------------------------------------------- records
def _values(row, account, event):
	arrival = row.get("actlArvlDt") or row.get("arvlXptdDt")
	return {
		"vessel_name": row.get("vsslNm"),
		"voyage_number": row.get("voygNo") or row.get("vygNo"),
		"arrival_date": getdate(arrival) if arrival else None,
		"facility_code": row.get("facility_code"),
		"bl_count": cint(row.get("our_bl_count")),
		"container_count": cint(row.get("our_cntr_count")),
		"watcher_account": account,
		"last_event": event,
	}


def _insert_allocation(row, account, event):
	now = now_datetime()
	allocation = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"mrn": row.get("mrn"),
			"first_seen": now,
			"last_seen": now,
			"last_changed": now,
			**_values(row, account, event),
		}
	)
	allocation.insert(ignore_permissions=True)
	return allocation


def _update_allocation(allocation, row, account, changed):
	event = "Allocation Changed" if changed else allocation.last_event
	allocation.update(_values(row, account, event))
	allocation.last_seen = now_datetime()
	if changed:
		allocation.last_changed = allocation.last_seen
	allocation.save(ignore_permissions=True)


# --------------------------------------------------------------------------- notifications
def _recipients():
	"""Every enabled ERPNext user who works on TANeSW: holds the 'TANeSW User' role, or has an enabled
	TANeSW User Account (System Managers such as the app owner usually have the account, not the role)."""
	users = set(
		frappe.get_all("Has Role", filters={"role": "TANeSW User", "parenttype": "User"}, pluck="parent")
	)
	users |= set(frappe.get_all("TANeSW User Account", filters={"enabled": 1}, pluck="user"))
	users.discard(None)
	if not users:
		return []
	return frappe.get_all(
		"User",
		filters={"name": ["in", sorted(users)], "enabled": 1, "user_type": "System User"},
		pluck="name",
	)


def _email_recipients():
	"""Only the operations team is emailed: enabled system users holding the 'TANeSW Operations' role. Nobody holding
	it means no email (never a fall-back to every TANeSW user)."""
	from tanesw_integration.install import OPS_ROLE

	users = frappe.get_all("Has Role", filters={"role": OPS_ROLE, "parenttype": "User"}, pluck="parent")
	if not users:
		return []
	return frappe.get_all(
		"User",
		filters={"name": ["in", sorted(set(users))], "enabled": 1, "user_type": "System User"},
		pluck="name",
	)


def _subject(allocation, event, old_counts):
	name = allocation.vessel_name or allocation.mrn
	if event == "Containers Landed":
		new = cint(allocation.landed_count) - cint(old_counts[0])
		return (
			f"Ready to declare: {name} — {new} more container(s) landed, "
			f"{cint(allocation.available_count)} waiting for declaration"
		)
	if event == "New Allocation":
		return f"New vessel allocation: {name} — {allocation.bl_count} B/L, {allocation.container_count} containers"
	old_bl, old_containers = old_counts
	return (
		f"Vessel allocation updated: {name} — B/L {old_bl} to {allocation.bl_count}, "
		f"containers {old_containers} to {allocation.container_count}"
	)


def _queue_notification(allocation, event, old_counts=None):
	"""Bell notification + email. Frappe never emails 'Alert' notifications by itself, so the email is sent
	explicitly through the normal outgoing Email Queue. Returns the number of recipients."""
	from frappe.desk.doctype.notification_log.notification_log import make_notification_logs

	recipients = _recipients()
	if not recipients:
		return 0
	subject = _subject(allocation, event, old_counts)

	make_notification_logs(
		{
			"type": "Alert",
			"subject": subject[:140],
			"document_type": DOCTYPE,
			"document_name": allocation.name,
		},
		recipients,
	)

	email_to = (
		_email_recipients() if cint(frappe.db.get_single_value(SETTINGS, "email_allocation_alerts")) else []
	)
	if email_to:
		try:
			frappe.sendmail(
				recipients=email_to,
				subject=subject,
				message=_email_body(allocation, event, old_counts),
				reference_doctype=DOCTYPE,
				reference_name=allocation.name,
			)
		except Exception:
			# The bell notification already exists; a mail problem must not undo the run.
			frappe.log_error(title="TANeSW allocation email failed", message=frappe.get_traceback())
			frappe.clear_messages()
	return len(recipients)


def _email_body(allocation, event, old_counts):
	def e(v):
		return escape_html("" if v is None else str(v))

	rows = [
		("Vessel", allocation.vessel_name),
		("MRN", allocation.mrn),
		("Voyage", allocation.voyage_number),
		("Arrival", allocation.arrival_date),
		("Delivered to", allocation.facility_code),
	]
	if event == "Containers Landed":
		rows += [
			("Landed (Target)", f"{old_counts[0]} → {allocation.landed_count}"),
			("Already declared", allocation.declared_count),
			("Waiting for declaration", allocation.available_count),
			("Allocated (Total)", allocation.container_count),
		]
	elif event == "Allocation Changed" and old_counts:
		rows += [
			("B/Ls for us", f"{old_counts[0]} → {allocation.bl_count}"),
			("Containers for us", f"{old_counts[1]} → {allocation.container_count}"),
		]
	else:
		rows += [("B/Ls for us", allocation.bl_count), ("Containers for us", allocation.container_count)]
	table = "".join(
		f'<tr><td style="padding:4px 12px 4px 0;color:#666">{e(k)}</td><td style="padding:4px 0"><b>{e(v)}</b></td></tr>'
		for k, v in rows
	)
	manifest_url = get_url(f"/app/tanesw-cargo/cgme0101026q/{allocation.mrn}")
	record_url = get_url(f"/app/{frappe.scrub(DOCTYPE).replace('_', '-')}/{allocation.name}")
	heading = {
		"New Allocation": "New vessel allocation",
		"Containers Landed": "Containers ready to declare",
	}.get(event, "Vessel allocation updated")
	links = f'<a href="{e(manifest_url)}">Open the manifest\'s B/L list</a>'
	if event == "Containers Landed":
		links = (
			f'<a href="{e(get_url("/app/tanesw-cargo/cgme0301002q"))}">Open the ICD Transfer Declaration List</a> '
			"and press <b>New Declaration</b> to declare them &nbsp;·&nbsp; " + links
		)
	return f"""<p><b>{e(heading)}</b> — detected by the TANeSW allocation watcher.</p>
<table style="border-collapse:collapse;font-size:13px">{table}</table>
<p>{links} &nbsp;·&nbsp; <a href="{e(record_url)}">Allocation record</a></p>
<p style="color:#888;font-size:11px">Counts are B/Ls on this manifest whose place of delivery is our ICD, read from TANeSW.
You receive this because you are a TANeSW user in ERPNext.</p>"""
