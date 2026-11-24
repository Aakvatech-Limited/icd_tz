"""Containers allocated to our ICD per vessel / manifest: landed, declared, still at port, received.

Headline figures are TANeSW's own Expected ICD Transfer list (CGME-0301-001Q), read live for the date range:
  Total    = containers allocated to our ICD on the manifest
  Target   = containers already LANDED (discharged) and available to declare
  Declared = containers declared to our ICD: taken / in transit or already received
and Not yet landed = Total - Target.

Target = containers with B21 Discharge Result
Report Approved, Declared = containers with F03 ICD Transfer Declaration Approved. But a
declared container is not always gone: some declared boxes have not gated out of the terminal yet.
So "Still at Port" = landed - gated out (C61) whenever container tracking covers the vessel, and only falls back to
Target - Declared when it does not.

TANeSW's Expected ICD Transfer list only holds vessels that still have containers to transfer: a finished vessel
drops off it, while Manifest Information "Our Cargo" still shows it.
Allocation therefore comes from Manifest Information ("Our Cargo": Master B/Ls delivered to our ICD and their
containers) for EVERY vessel arriving in the range. TANeSW's list only adds Landed / Declared, for vessels still on it;
for finished vessels those are blank. The "Master B/Ls" column counts our B/Ls only.

Container-level tracking (TANeSW Container, synced hourly by containers.py) adds what TANeSW's list cannot:
how many declared containers have actually arrived (Carry-In approved) and how long containers sit at the port.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowdate

from tanesw_integration.credentials import watcher_accounts


def execute(filters=None):
	f = frappe._dict(filters or {})
	f.from_date = f.from_date or add_days(nowdate(), -30)
	f.to_date = f.to_date or nowdate()
	data, note = get_data(f)
	return get_columns(), data, note, get_chart(data), get_summary(data)


def get_columns():
	def c(fn, label, ft="Int", w=105, **k):
		return {"fieldname": fn, "label": _(label), "fieldtype": ft, "width": w, **k}

	return [
		c("arrival_date", "Arrival", "Date", 100),
		c("vessel_name", "Vessel", "Data", 170),
		c("voyage_number", "Voyage", "Data", 85),
		c("mrn", "MRN", "Data", 115),
		c("bl_count", "Master B/Ls", w=85),
		c("total", "Allocated (Total)", w=100),
		c("landed", "Landed (Target)", w=100),
		c("not_landed", "Not Yet Landed", w=100),
		c("declared", "Declared (Taken)", w=105),
		c("at_port", "Still at Port", w=95),
		c("declared_waiting", "Declared, Not Yet Gated Out", w=150),
		c("received", "Received at ICD", w=105),
		c("in_transit", "In Transit", w=85),
		c("diverted", "Diverted to Other ICD", w=125),
		c("removed", "Removed From Our Allocation", w=150),
		c("pct_declared", "% Declared", "Percent", 90),
		c("avg_dwell", "Avg Port Dwell (days)", "Float", 120, precision=1),
		c("max_dwell", "Max Port Dwell (days)", "Float", 120, precision=1),
	]


def get_data(f):
	note = None
	rows = {}
	try:
		for x in _expected_list(f):
			mrn = x.get("mrn")
			if not mrn:
				continue
			total, landed, declared = cint(x.get("totCnt")), cint(x.get("trgtCnt")), cint(x.get("dclrCnt"))
			rows[mrn] = frappe._dict(
				{
					"arrival_date": getdate(x["arvlDt"]) if x.get("arvlDt") else None,
					"vessel_name": x.get("vsslNm"),
					"voyage_number": x.get("vygNo"),
					"mrn": mrn,
					"bl_count": cint(x.get("mblCnt")),
					"total": total,
					"landed": landed,
					"declared": declared,
					"not_landed": max(total - landed, 0),
					"at_port": max(landed - declared, 0),
					"source": "TANeSW",
				}
			)
	except Exception:
		frappe.log_error(
			title="TANeSW Container Allocation report: expected list failed", message=frappe.get_traceback()
		)
		frappe.clear_messages()
		note = _("TANeSW did not answer: showing the last synced figures only.")

	# Vessels with our cargo that are no longer on TANeSW's list (finished) or not on it yet: Manifest Information.
	try:
		unverified = _add_manifest_vessels(f, rows)
		if unverified:
			note = (note + " " if note else "") + _(
				"{0} manifest(s) could not be checked on TANeSW and are left out: {1}"
			).format(len(unverified), ", ".join(u.get("mrn") or "" for u in unverified[:10]))
	except Exception:
		frappe.log_error(
			title="TANeSW Container Allocation report: manifest information failed",
			message=frappe.get_traceback(),
		)
		frappe.clear_messages()
		note = (note + " " if note else "") + _(
			"Manifest Information did not answer: finished vessels may be missing."
		)

	# Vessels the allocation watcher knows that TANeSW's list does not show (not yet arrived, or TANeSW down).
	conds = {"arrival_date": ["between", [f.from_date, f.to_date]]}
	for v in frappe.get_all(
		"TANeSW Vessel Allocation",
		filters=conds,
		fields=["name", "vessel_name", "voyage_number", "arrival_date", "container_count"],
	):
		if v.name not in rows:
			rows[v.name] = frappe._dict(
				{
					"arrival_date": v.arrival_date,
					"vessel_name": v.vessel_name,
					"voyage_number": v.voyage_number,
					"mrn": v.name,
					"bl_count": None,
					"total": cint(v.container_count),
					"landed": None,
					"declared": None,
					"not_landed": None,
					"at_port": None,
					"source": "Watcher",
				}
			)

	if f.vessel_name:
		rows = {k: r for k, r in rows.items() if f.vessel_name.lower() in (r.vessel_name or "").lower()}
	if f.mrn:
		rows = {k: r for k, r in rows.items() if k == f.mrn.strip().upper()}

	_add_tracking(rows)
	data = sorted(rows.values(), key=lambda r: (r.arrival_date or getdate("1900-01-01")), reverse=True)
	for r in data:
		r.pct_declared = (
			round(100.0 * r.declared / r.total, 1) if r.total and r.declared is not None else None
		)
	return data, note


def _expected_list(f):
	"""TANeSW Expected ICD Transfer list for the range, read with the background watcher account (report users
	don't need their own TANeSW login)."""
	from tanesw_integration.cargo import icd_expected_list
	from tanesw_integration.containers import _as_watcher

	s = frappe.get_single("TANeSW Settings")
	accounts = watcher_accounts(s)
	out, page = [], 0
	with _as_watcher(accounts) as account:
		if not account:
			raise frappe.ValidationError("No enabled watcher account")
		while page < 20:
			res = icd_expected_list(str(f.from_date), str(f.to_date), "C", f.mrn, None, page, 100) or {}
			out += res.get("content") or []
			if page + 1 >= cint((res.get("page") or {}).get("totalPages") or 1):
				break
			page += 1
	return out


def _add_manifest_vessels(f, rows):
	"""Vessels with our cargo arriving in the range (Manifest Information, "Our Cargo") that the Expected ICD Transfer
	list did not return. Returns the manifests TANeSW could not verify, so the report can say so."""
	from tanesw_integration.cargo import manifest_info_list
	from tanesw_integration.containers import _as_watcher

	s = frappe.get_single("TANeSW Settings")
	accounts = watcher_accounts(s)
	with _as_watcher(accounts) as account:
		if not account:
			raise frappe.ValidationError("No enabled watcher account")
		res = (
			manifest_info_list(str(f.from_date), str(f.to_date), "mrn", f.mrn, 0, 1000, our_only="ours") or {}
		)
	for x in res.get("content") or []:
		mrn = x.get("mrn")
		if not mrn:
			continue
		if (
			mrn in rows
		):  # on TANeSW's list: keep its Landed / Declared, take our B/Ls and containers from the manifest
			r = rows[mrn]
			r.bl_count, r.total = cint(x.get("our_bl_count")), cint(x.get("our_cntr_count"))
			if r.landed is not None:
				r.not_landed = max(r.total - r.landed, 0)
			continue
		arrived = x.get("actlArvlDt") or x.get("arvlXptdDt")
		rows[mrn] = frappe._dict(
			{
				"arrival_date": getdate(arrived) if arrived else None,
				"vessel_name": x.get("vsslNm"),
				"voyage_number": None,
				"mrn": mrn,
				"bl_count": cint(x.get("our_bl_count")),
				"total": cint(x.get("our_cntr_count")),
				"landed": None,
				"declared": None,
				"not_landed": None,
				"at_port": None,
				"source": "Manifest",
			}
		)
	return res.get("unverified") or []


def _add_tracking(rows):
	"""Container-level figures. "Still at Port" is only taken from tracking when tracking has read at least as many
	landed containers as TANeSW reports landed — a partially synced vessel (detail-call cap, a B/L that failed)
	keeps TANeSW's Target - Declared instead of an understated count."""
	if not rows:
		return
	from tanesw_integration.containers import dwell_days

	now = now_datetime()
	agg = {}
	for c in frappe.get_all(
		"TANeSW Container",
		filters={"mrn": ["in", list(rows)]},
		fields=["mrn", "status", "dwell_days", "declared_on", "discharged_on", "removed_from_allocation_on"],
	):
		a = agg.setdefault(
			c.mrn,
			{
				"received": 0,
				"in_transit": 0,
				"at_terminal": 0,
				"declared_waiting": 0,
				"diverted": 0,
				"removed": 0,
				"landed_tracked": 0,
				"dwell": [],
			},
		)
		if c.removed_from_allocation_on and c.status not in ("Received at ICD", "Diverted"):
			a["removed"] += 1  # TANeSW took it off our allocation; not carried in anywhere yet
			continue
		if c.status == "Received at ICD":
			a["received"] += 1
		elif c.status == "In Transit":
			a["in_transit"] += 1
		elif c.status == "Diverted":
			a["diverted"] += 1
		elif c.status == "At Terminal":
			a["at_terminal"] += 1
			if c.declared_on:
				a["declared_waiting"] += 1
		if c.status != "Not Discharged":
			a["landed_tracked"] += 1
			dwell = (
				dwell_days(get_datetime(c.discharged_on), None, now)  # live, as in TANeSW Container Dwell
				if c.status == "At Terminal" and c.discharged_on
				else c.dwell_days
			)
			if dwell is not None:
				a["dwell"].append(flt(dwell))
	for mrn, r in rows.items():
		a = agg.get(mrn)
		r.received = a["received"] if a else None
		r.in_transit = a["in_transit"] if a else None
		r.diverted = a["diverted"] if a else None
		r.removed = a["removed"] if a else None
		r.declared_waiting = a["declared_waiting"] if a else None
		r.tracked = a["landed_tracked"] if a else 0
		if a and r.landed is not None and a["landed_tracked"] >= r.landed:
			r.at_port = a["at_terminal"]  # complete: landed and not gated out (declared or not)
			r.at_port_source = "tracking"
		elif a and r.landed is not None:
			r.at_port_source = "partial"
		r.avg_dwell = round(sum(a["dwell"]) / len(a["dwell"]), 1) if a and a["dwell"] else None
		r.max_dwell = round(max(a["dwell"]), 1) if a and a["dwell"] else None


def get_chart(data):
	rows = [r for r in data if r.landed is not None][:15][::-1]
	if not rows:
		return None
	return {
		"data": {
			"labels": [r.vessel_name or r.mrn for r in rows],
			"datasets": [
				{"name": _("Declared (Taken)"), "values": [r.declared or 0 for r in rows]},
				{"name": _("Still at Port"), "values": [r.at_port or 0 for r in rows]},
				{"name": _("Not Yet Landed"), "values": [r.not_landed or 0 for r in rows]},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
		"height": 260,
	}


def get_summary(data):
	def tot(k):
		return sum(r.get(k) or 0 for r in data)

	return [
		{"label": _("Vessels"), "value": len(data), "datatype": "Int"},
		{"label": _("Allocated"), "value": tot("total"), "datatype": "Int"},
		{"label": _("Landed"), "value": tot("landed"), "datatype": "Int"},
		{"label": _("Declared (Taken)"), "value": tot("declared"), "datatype": "Int", "indicator": "Blue"},
		{"label": _("Still at Port"), "value": tot("at_port"), "datatype": "Int", "indicator": "Orange"},
		{
			"label": _("Received at ICD (tracked)"),
			"value": tot("received"),
			"datatype": "Int",
			"indicator": "Green",
		},
		{
			"label": _("Diverted to Other ICD"),
			"value": tot("diverted"),
			"datatype": "Int",
			"indicator": "Red",
		},
		{
			"label": _("Removed From Our Allocation"),
			"value": tot("removed"),
			"datatype": "Int",
			"indicator": "Red",
		},
	]
