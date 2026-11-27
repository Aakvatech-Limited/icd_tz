"""TANeSW vs ERP anomalies -> Container Allocation Track log (replaces the GitHub delivery tracker and allocation daemon).

Runs at the end of every hourly container sync (containers.py), from data already stored: TANeSW Container (what
TANeSW says happened to each box) against icd_tz (Container, Container Reception, Sales Invoice). No TANeSW calls.

It writes the same DocType, one row per container number, with the same anomaly names and fields the GitHub flows
wrote, so Inventory Movement, Monthly Inventory Movement (+ Financial Translation), Yard Utilization and Yard and
Financial Pipeline keep reading it unchanged. A row whose problem is gone is set back to "In Normal Transit".

  Delivered on TANeSW (Not in ERP)  left our ICD on TANeSW, ERP not Delivered, invoice paid / empty box / never received
  Delivered Unbilled (Leakage)      left our ICD on TANeSW, ERP not Delivered, no submitted invoice
  Delivered Invoiced Unpaid         left our ICD on TANeSW and invoice outstanding; or ERP Delivered with an
                                    outstanding invoice posted in the last 120 days (the tracker's flag_delivered_unpaid)
  Diverted to Other ICD / Diverted Transit (Border)
                                    carried in at another ICD / a border post instead of ours
  Ghost Yard Arrival / Pending Submit
                                    in our yard on TANeSW for more than 12 h with no submitted Container Reception
                                    (none at all / only a draft)
  Stranded at Port                  still at the terminal past its free port days (Local 5 / Transit 15)

Switch on with "Track TANeSW Anomalies" in TANeSW Settings, and switch the GitHub workflows off the same day: two
writers on one row per container would overwrite each other.
"""

import json

import frappe
from frappe.query_builder import DocType, Order
from frappe.utils import add_days, cint, flt, get_datetime, now_datetime, nowdate, time_diff_in_hours

SETTINGS = "TANeSW Settings"
TRACK_LOG = "Container Allocation Track log"
NORMAL = "In Normal Transit"
NOT_IN_ERP, LEAKAGE, UNPAID = (
	"Delivered on TANeSW (Not in ERP)",
	"Delivered Unbilled (Leakage)",
	"Delivered Invoiced Unpaid",
)
DIVERTED, BORDER = "Diverted to Other ICD", "Diverted Transit (Border)"
GHOST, PENDING, STRANDED = "Ghost Yard Arrival", "Pending Submit", "Stranded at Port"
GHOST_GRACE_HOURS = 12
UNPAID_LOOKBACK_DAYS = 120
LOOKBACK_DAYS = 120  # tracked containers looked at: still open, or closed within this many days
BORDER_WORDS = ("BORDER", "TUNDUMA", "MUTUKULA")


def enabled():
	return (
		cint(frappe.db.get_single_value(SETTINGS, "enable_anomaly_tracking"))
		and frappe.db.exists("DocType", TRACK_LOG)
		and "icd_tz" in frappe.get_installed_apps()
	)


def track_anomalies():
	if not enabled():
		return {"status": "off"}
	from tanesw_integration import port_storage as ps

	tracked = _tracked()
	types = ps.cargo_types((t.mrn, t.bl_no) for t in tracked)
	verdicts = {}
	for t in tracked:
		# Local 5 / Transit 15 per box (port_storage.py), not the single ICD Setting figure
		v = classify(t, ps.FREE_DAYS.get(ps.cargo_type_of(types, t.mrn, t.bl_no), ps.FREE_DAYS[ps.LOCAL]))
		if v:
			verdicts[t.container_no] = v  # oldest vessel first: the latest visit of a box wins
	for v in delivered_unpaid():
		verdicts.setdefault(v["container_no"], v)
		if verdicts[v["container_no"]]["anomaly_type"] == NORMAL:
			verdicts[v["container_no"]] = v

	counts = {}
	for _cntr, v in verdicts.items():
		if _upsert(v):
			counts[v["anomaly_type"]] = counts.get(v["anomaly_type"], 0) + 1
	counts["cleared_stale"] = _clear_stale(verdicts)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background job: keep each finished vessel if a later one fails
	result = {
		"status": "ok",
		"free_port_days": "Local 5 / Transit 15",
		"written": counts,
		"open": {
			a: frappe.db.count(TRACK_LOG, {"anomaly_type": a})
			for a in (NOT_IN_ERP, LEAKAGE, UNPAID, DIVERTED, BORDER, GHOST, PENDING, STRANDED)
		},
	}
	frappe.db.set_single_value(
		SETTINGS, {"anomaly_last_run": now_datetime(), "anomaly_last_result": json.dumps(result, default=str)}
	)
	return result


def port_free_days(company=None):
	"""Last 'Free' day of the port storage bands in ICD Setting ; 7 if none is set."""
	name = frappe.db.get_value("ICD Setting", {"company": company} if company else {}, "name")
	if name:
		free = [
			cint(r.to)
			for r in frappe.get_all(
				"ICD TZ Port Storage Detail",
				filters={"parent": name, "parenttype": "ICD Setting", "charge": "Free"},
				fields=["to"],
			)
		]
		if free:
			return max(free)
	return 7


def _tracked():
	since = add_days(nowdate(), -LOOKBACK_DAYS)
	return frappe.get_all(
		"TANeSW Container",
		or_filters={"tracking_complete": 0, "modified": [">=", since]},
		fields=[
			"name",
			"container_no",
			"mrn",
			"bl_no",
			"crn",
			"status",
			"terminal",
			"dwell_days",
			"last_event",
			"last_event_on",
			"discharged_on",
			"received_on",
			"left_icd_on",
			"left_icd_event",
			"diverted_to",
			"diverted_on",
			"arrival_date",
			"tracking_complete",
			"lcl_lots",
		],
		order_by="arrival_date asc, modified asc",
	)


def classify(t, free_days, now=None):
	"""One TANeSW Container record -> Track log verdict (anomaly or normal)."""
	now = now or now_datetime()
	v = {
		"container_no": t.container_no,
		"m_bl_no": t.bl_no,
		"mrn": t.mrn,
		"crn": t.crn,
		"manifest_arrival_date": t.arrival_date,
		"operating_facility": t.terminal,
		"last_customs_event": t.last_event,
		"event_date": t.last_event_on,
		"is_diverted": 0,
		"diverted_to": None,
		"anomaly_type": NORMAL,
		"erp_status": None,
		"action_required": f"Normal ({t.status})",
	}

	if t.status == "Diverted":
		to = t.diverted_to or "another ICD"
		border = any(w in to.upper() for w in BORDER_WORDS)
		v.update(
			anomaly_type=BORDER if border else DIVERTED,
			is_diverted=1,
			diverted_to=to,
			operating_facility=to,
			event_date=t.diverted_on,
			erp_status=f"Processed at {to}"[:140],
			action_required=f"Exclude from our backlog: carried in at {to} on TANeSW.",
		)
		return v

	erp = erp_side(t.container_no, t.mrn)
	v["erp_status"] = erp["status"]

	if t.left_icd_on:
		if erp["status"] == "Delivered":
			return v  # both agree; an unpaid invoice is caught by delivered_unpaid()
		when = str(t.left_icd_on)[:16]
		v.update(event_date=t.left_icd_on, last_customs_event=t.left_icd_event or t.last_event)
		if not erp["containers"]:
			v.update(
				anomaly_type=NOT_IN_ERP,
				action_required=(
					f"Left our ICD on TANeSW {when} but NO Container "
					"Reception exists in the ERP. Confirm receipt or investigate."
				),
			)
		elif erp["empty"]:
			v.update(
				anomaly_type=NOT_IN_ERP,
				action_required=(
					f"Empty container left our ICD on TANeSW {when}; ERP "
					f"status '{erp['status']}'. Create Gate Pass / mark Delivered (no billing expected)."
				),
			)
		elif not erp["invoice"]:
			v.update(
				anomaly_type=LEAKAGE,
				action_required=(
					f"Left our ICD on TANeSW {when} with NO submitted Sales "
					"Invoice. Immediate billing investigation required."
				),
			)
		elif erp["outstanding"] > 0.5:
			v.update(
				anomaly_type=UNPAID,
				action_required=(
					f"Left our ICD on TANeSW {when}. Invoice {erp['invoice']} "
					f"has {erp['outstanding']:,.2f} outstanding. ERP status '{erp['status']}'."
				),
			)
		else:
			v.update(
				anomaly_type=NOT_IN_ERP,
				action_required=(
					f"Left our ICD on TANeSW {when}. Invoice "
					f"{erp['invoice']} paid. ERP status '{erp['status']}': create Gate Pass / mark Delivered."
				),
			)
		return v

	lots = lot_problems(t)
	if lots:
		worst = min(lots, key=lambda p: SEVERITY.index(p["kind"]))
		lines = "; ".join(
			f"HBL {p['h_bl_no']} left {str(p['left_on'])[:16]}, ERP '{p['status']}', "
			+ (
				f"invoice {p['invoice']} outstanding {p['outstanding']:,.2f}"
				if p["invoice"]
				else "no invoice"
			)
			for p in lots
		)
		v.update(
			anomaly_type=worst["kind"],
			event_date=worst["left_on"],
			erp_status=worst["status"],
			last_customs_event="LCL cargo carried out (House B/L)",
			action_required=f"LCL cargo left our ICD on TANeSW but is not Delivered in the ERP: {lines}"[
				:1000
			],
		)
		return v

	if t.status == "Received at ICD" and t.received_on:
		hours = time_diff_in_hours(now, get_datetime(t.received_on))
		if hours >= GHOST_GRACE_HOURS and not erp["submitted_reception"]:
			if erp["draft_reception"]:
				v.update(
					anomaly_type=PENDING,
					event_date=t.received_on,
					erp_status=f"Draft CR: {erp['draft_reception']}",
					action_required=f"In our yard on TANeSW {hours:.0f} h: submit draft reception {erp['draft_reception']}.",
				)
			else:
				v.update(
					anomaly_type=GHOST,
					event_date=t.received_on,
					erp_status="In Yard on TANeSW, no ERP reception",
					action_required=f"In our yard on TANeSW for {hours:.0f} h with no Container Reception in the ERP.",
				)
		return v

	if t.status == "At Terminal" and flt(t.dwell_days) > free_days:
		band = "double" if flt(t.dwell_days) > free_days + 7 else "single"
		v.update(
			anomaly_type=STRANDED,
			event_date=t.discharged_on,
			erp_status=f"At terminal {flt(t.dwell_days):.1f} days",
			action_required=(
				f"At the port terminal {flt(t.dwell_days):.1f} days, past the {free_days} free days: "
				f"port storage now charged at the {band} rate. Arrange pick-up."
			),
		)
	return v


SEVERITY = [LEAKAGE, UNPAID, NOT_IN_ERP]


def lot_problems(t):
	"""LCL cargo lots (House B/Ls) that left our ICD on TANeSW while their ERP cargo-lot Container is not Delivered,
	each judged by its own invoice (Sales Invoice.h_bl_no, as the old tracker did; line container_id as fallback)."""
	left = [l for l in json.loads(t.get("lcl_lots") or "[]") if l.get("left_on")]
	if not left:
		return []
	manifests = frappe.get_all("Manifest", filters={"mrn": t.mrn, "docstatus": 1}, pluck="name") or ["-"]
	has_hbl_col = frappe.db.has_column("Sales Invoice", "h_bl_no")
	out = []
	for l in left:
		lot = frappe.db.get_value(
			"Container",
			{
				"container_no": t.container_no,
				"h_bl_no": l["h_bl_no"],
				"manifest": ["in", manifests],
				"docstatus": ["<", 2],
			},
			["name", "status"],
			as_dict=True,
		)
		if not lot or lot.status == "Delivered":
			continue
		SI, SII = DocType("Sales Invoice"), DocType("Sales Invoice Item")
		on_line = SI.name.isin(frappe.qb.from_(SII).select(SII.parent).where(SII.container_id == lot.name))
		match = (on_line | (SI.h_bl_no == l["h_bl_no"])) if has_hbl_col else on_line
		inv = (
			frappe.qb.from_(SI)
			.select(SI.name, SI.outstanding_amount)
			.where((SI.docstatus == 1) & (SI.is_return == 0) & match)
			.run(as_dict=True)
		)
		outstanding = sum(flt(i.outstanding_amount) for i in inv)
		kind = LEAKAGE if not inv else (UNPAID if outstanding > 0.5 else NOT_IN_ERP)
		out.append(
			{
				"kind": kind,
				"h_bl_no": l["h_bl_no"],
				"left_on": get_datetime(l["left_on"]),
				"status": lot.status,
				"invoice": inv[0].name if inv else None,
				"outstanding": outstanding,
			}
		)
	return out


def erp_side(container_no, mrn):
	"""The ERP's view of one box on one manifest: containers, status, receptions, invoice, outstanding."""
	out = {
		"containers": [],
		"status": "Not Received in ERP",
		"empty": 0,
		"invoice": None,
		"outstanding": 0.0,
		"submitted_reception": None,
		"draft_reception": None,
	}
	manifests = frappe.get_all("Manifest", filters={"mrn": mrn, "docstatus": 1}, pluck="name")
	if not manifests:
		out["status"] = "No Manifest in ERP"
		return out
	rows = frappe.get_all(
		"Container",
		filters={"container_no": container_no, "manifest": ["in", manifests], "docstatus": ["<", 2]},
		fields=["name", "status", "has_hbl", "is_empty_container"],
	)
	out["containers"] = [r.name for r in rows]
	shell = next((r for r in rows if not cint(r.has_hbl)), rows[0] if rows else None)
	if shell:
		out["status"] = shell.status
		out["empty"] = cint(shell.is_empty_container)
	for r in frappe.get_all(
		"Container Reception",
		filters={"container_no": container_no, "manifest": ["in", manifests], "docstatus": ["<", 2]},
		fields=["name", "docstatus"],
	):
		out["submitted_reception" if r.docstatus == 1 else "draft_reception"] = r.name
	if out["containers"]:
		SI, SII = DocType("Sales Invoice"), DocType("Sales Invoice Item")
		inv = (
			frappe.qb.from_(SI)
			.join(SII)
			.on(SII.parent == SI.name)
			.select(SI.name, SI.outstanding_amount)
			.where(
				(SI.docstatus == 1)
				& (SI.is_return == 0)
				& (SII.container_id.isin(out["containers"]) | (SII.container_no == container_no))
			)
			.groupby(SI.name, SI.outstanding_amount)
			.orderby(SI.outstanding_amount, order=Order.desc)
			.run(as_dict=True)
		)
		if inv:
			out["invoice"] = inv[0].name
			out["outstanding"] = sum(flt(i.outstanding_amount) for i in inv)
	return out


def delivered_unpaid():
	"""ERP Delivered boxes whose invoice is still outstanding (the tracker's flag_delivered_unpaid)."""
	SI, SII, C, M = (
		DocType("Sales Invoice"),
		DocType("Sales Invoice Item"),
		DocType("Container"),
		DocType("Manifest"),
	)
	rows = (
		frappe.qb.from_(SI)
		.join(SII)
		.on(SII.parent == SI.name)
		.join(C)
		.on(C.name == SII.container_id)
		.left_join(M)
		.on(M.name == C.manifest)
		.select(
			C.container_no,
			C.m_bl_no,
			C.status,
			C.gate_out_date,
			M.mrn,
			SI.name.as_("invoice"),
			SI.outstanding_amount,
			SI.currency,
			SI.grand_total,
			SI.customer,
		)
		.where(
			(SI.docstatus == 1)
			& (SI.is_return == 0)
			& (SI.outstanding_amount > 0.5)
			& (SI.posting_date >= add_days(nowdate(), -UNPAID_LOOKBACK_DAYS))
			& (C.status == "Delivered")
		)
		.groupby(C.container_no, SI.name)
		.run(as_dict=True)
	)
	out = []
	for r in rows:
		gate_out = str(r.gate_out_date or "")[:10]
		out.append(
			{
				"container_no": r.container_no,
				"m_bl_no": r.m_bl_no,
				"mrn": r.mrn,
				"erp_status": r.status,
				"anomaly_type": UNPAID,
				"event_date": r.gate_out_date,
				"last_customs_event": "ERP Gate Out",
				"is_diverted": 0,
				"action_required": (
					f"Left the yard {gate_out} (ERP Delivered) with invoice {r.invoice} "
					f"unpaid ({r.currency} {flt(r.grand_total):,.2f}, {r.customer}). Collect, or record the waiver / "
					"cancel a duplicate invoice."
				),
			}
		)
	return out


def _upsert(v):
	"""Write one verdict. Returns True when an anomaly row was written. Normal containers only touch an existing
	row (to clear it); they never create one, so the log stays a list of problems."""
	name = v["container_no"]
	if not name:
		return False
	exists = frappe.db.exists(TRACK_LOG, name)
	values = {k: val for k, val in v.items() if k != "container_no"}
	values.update(sync_status="Synced", last_sync_date=now_datetime())
	for k in ("erp_status", "operating_facility", "last_customs_event", "diverted_to"):
		if values.get(k):
			values[k] = str(values[k])[:140]
	if v["anomaly_type"] == NORMAL:
		if exists and frappe.db.get_value(TRACK_LOG, name, "anomaly_type") != NORMAL:
			frappe.db.set_value(TRACK_LOG, name, values)
		return False
	if exists:
		frappe.db.set_value(TRACK_LOG, name, values)
	else:
		# db_insert, as the rows the GitHub flows wrote: "Delivered Invoiced Unpaid" is used by every writer and by
		# the reports but is missing from the DocType's option list, which a full save
		# would refuse
		doc = frappe.get_doc({"doctype": TRACK_LOG, "container_no": name, **values})
		doc.name = name
		doc.creation = doc.modified = now_datetime()
		doc.owner = doc.modified_by = frappe.session.user
		doc.db_insert()
	return True


def _clear_stale(verdicts):
	"""Rows flagged earlier (by this job or the GitHub flows) for containers that got no verdict this run: clear the
	ones the ERP has since resolved, as the old tracker's cleanup did. Diversions are kept (they stay true)."""
	cleared = 0
	unpaid_now = {v["container_no"] for v in delivered_unpaid()}
	for r in frappe.get_all(
		TRACK_LOG,
		filters={
			"anomaly_type": ["in", [NOT_IN_ERP, LEAKAGE, UNPAID, GHOST, PENDING, STRANDED]],
			"container_no": ["not in", list(verdicts) or ["-"]],
		},
		fields=["name", "anomaly_type"],
	):
		delivered = frappe.db.exists(
			"Container", {"container_no": r.name, "status": "Delivered", "docstatus": ["<", 2]}
		)
		received = frappe.db.exists("Container Reception", {"container_no": r.name, "docstatus": 1})
		resolved = (
			(r.anomaly_type in (NOT_IN_ERP, LEAKAGE) and delivered)
			or (r.anomaly_type == UNPAID and r.name not in unpaid_now and delivered)
			or (r.anomaly_type in (GHOST, PENDING) and received)
			or r.anomaly_type == STRANDED  # only ever set from live tracking; untracked now means it moved on
		)
		if resolved:
			frappe.db.set_value(
				TRACK_LOG,
				r.name,
				{
					"anomaly_type": NORMAL,
					"sync_status": "Synced",
					"last_sync_date": now_datetime(),
					"action_required": f"Resolved (was {r.anomaly_type})",
				},
			)
			cleared += 1
	return cleared
