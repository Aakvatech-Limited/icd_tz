"""Number cards on the TANeSW home page that one filter on one DocType cannot express."""

import frappe
from frappe.utils import get_first_day, nowdate

from tanesw_integration.hints import JSONish, Scalar


@frappe.whitelist(methods=["POST"])
def delivered_this_month(filters: JSONish | None = None):
	"""Boxes TANeSW shows LEAVING our ICD this month (TANeSW Container.left_icd_on): to their consignee, or on to
	another facility by a Simple Transfer, which is an ordinary exit of a box that was ours."""
	start = get_first_day(nowdate())
	return {
		"value": frappe.db.count("TANeSW Container", {"left_icd_on": [">=", start]}),
		"fieldtype": "Int",
		"route": ["List", "TANeSW Container"],
		"route_options": {"left_icd_on": [">=", str(start)]},
	}


# --------------------------------------------------------------------------- TANeSW Dashboard page (date range)
# One call returns every figure on the tanesw-dashboard page for a date range. Box counts are split Local / Transit
# (port_storage.py: ERP Master B/L IM / TR). "Now" figures (still at port, over free days) ignore the range.

RANGE_LOOKBACK_DAYS = 120  # boxes older than this before the range start are only read if still open


def _split(rows):
	out = {"total": len(rows), "Local": 0, "Transit": 0, "Unknown": 0}
	for r in rows:
		out[r.cargo_type] = out.get(r.cargo_type, 0) + 1
	return out


def _in(value, start, end):
	from frappe.utils import getdate

	return bool(value) and start <= getdate(value) <= end


def target_for(kpi_code, company, start, end):
	"""KPI Target for a date range: each month's target, pro-rated by the days of that month inside the range.
	None when the KPI Target form is not installed or no month in the range has a target."""
	from frappe.utils import add_days, date_diff, get_first_day, get_last_day, getdate

	if not frappe.db.exists("DocType", "KPI Target"):
		return None
	start, end = getdate(start), getdate(end)
	total, found, month = 0.0, False, get_first_day(start)
	while month <= end:
		last = get_last_day(month)
		value = frappe.db.get_value(
			"KPI Target",
			{
				"kpi_code": kpi_code,
				"company": company,
				"fiscal_year": str(month.year),
				"month": f"{month.month:02d}",
			},
			"target_value",
		)
		if value:
			found = True
			days_in = date_diff(min(last, end), max(month, start)) + 1
			total += float(value) * days_in / (date_diff(last, month) + 1)
		month = add_days(last, 1)
	return round(total) if found else None


@frappe.whitelist(methods=["POST"])
def get_dashboard(
	from_date: Scalar | None = None, to_date: Scalar | None = None, company: Scalar | None = None
):
	from frappe.utils import add_days, get_datetime, getdate, now_datetime

	from tanesw_integration import port_storage as ps
	from tanesw_integration.containers import dwell_days

	frappe.has_permission("TANeSW Container", "read", throw=True)
	start = getdate(from_date or get_first_day(nowdate()))
	end = getdate(to_date or nowdate())
	if end < start:
		start, end = end, start
	company = (
		company
		or frappe.defaults.get_user_default("Company")
		or frappe.defaults.get_global_default("company")
	)

	from frappe.query_builder import DocType
	from frappe.query_builder.functions import Coalesce, Count, Sum

	T = DocType("TANeSW Container")
	since = add_days(start, -RANGE_LOOKBACK_DAYS)
	boxes = (
		frappe.qb.from_(T)
		.select(
			T.name,
			T.container_no,
			T.mrn,
			T.bl_no,
			T.vessel_name,
			T.status,
			T.arrival_date,
			T.discharged_on,
			T.declared_on,
			T.gate_out_on,
			T.received_on,
			T.left_icd_on,
			T.diverted_on,
			T.removed_from_allocation_on,
		)
		.where(
			(Coalesce(T.arrival_date, "2000-01-01") >= since)
			| T.status.isin(["Not Discharged", "At Terminal", "In Transit"])
			| (
				Coalesce(
					T.received_on, T.left_icd_on, T.diverted_on, T.removed_from_allocation_on, "2000-01-01"
				)
				>= since
			)
		)
		.run(as_dict=True)
	)
	types = ps.cargo_types((b.mrn, b.bl_no) for b in boxes)
	now, today = now_datetime(), getdate(nowdate())
	for b in boxes:
		b.cargo_type = ps.cargo_type_of(types, b.mrn, b.bl_no)
		b.left = b.status == "Diverted" or bool(
			b.removed_from_allocation_on and b.status != "Received at ICD"
		)
		b.port = ps.storage(b.discharged_on, b.gate_out_on, b.cargo_type, today=today)

	def pick(pred):
		return [b for b in boxes if pred(b)]

	allocated = pick(lambda b: _in(b.arrival_date, start, end) and not b.removed_from_allocation_on)
	received = pick(lambda b: _in(b.received_on, start, end))
	delivered = pick(lambda b: _in(b.left_icd_on, start, end))
	diverted = pick(lambda b: b.status == "Diverted" and _in(b.diverted_on, start, end))
	removed = pick(lambda b: b.status != "Received at ICD" and _in(b.removed_from_allocation_on, start, end))

	at_port = pick(lambda b: b.status == "At Terminal" and b.port and not b.left)
	over_now = [b for b in at_port if b.port.storage_status == ps.CHARGED]
	ending = [b for b in at_port if b.port.storage_status == ps.ENDING]
	left_late = pick(lambda b: b.port and not b.left and b.port.days_over and _in(b.gate_out_on, start, end))

	def avg(rows):
		return (
			round(sum(dwell_days(get_datetime(b.discharged_on), None, now) for b in rows) / len(rows), 1)
			if rows
			else 0
		)

	alloc_target = target_for("allocation", company, start, end)
	recv_target = target_for("receiving", company, start, end)

	def pct(v, t):
		return round(100.0 * v / t, 1) if t else None

	late = (
		frappe.db.count(
			"TANeSW Reception Date Check",
			{"status": "Posted Late", "posting_date": ["between", [start, end]]},
		)
		if frappe.db.exists("DocType", "TANeSW Reception Date Check")
		else 0
	)
	R = DocType("TANeSW Reception Date Check")
	lost = (
		(
			frappe.qb.from_(R)
			.select(Coalesce(Sum(R.storage_days_lost), 0))
			.where((R.storage_days_lost > 0) & R.posting_date.between(start, end))
			.run()[0][0]
		)
		if frappe.db.exists("DocType", "TANeSW Reception Date Check")
		else 0
	)
	anomalies = {}
	if frappe.db.exists("DocType", "Container Allocation Track log"):
		L = DocType("Container Allocation Track log")
		for a, n in (
			frappe.qb.from_(L)
			.select(L.anomaly_type, Count("*"))
			.where(L.anomaly_type.isnotnull() & (L.anomaly_type != "In Normal Transit"))
			.groupby(L.anomaly_type)
			.run()
		):
			anomalies[a] = n

	days = []
	d = start
	while d <= end:
		days.append(d)
		d = add_days(d, 1)
	per_day = {
		t: [sum(1 for b in received if b.cargo_type == t and getdate(b.received_on) == x) for x in days]
		for t in (ps.LOCAL, ps.TRANSIT, ps.UNKNOWN)
	}

	rng = {"from_date": str(start), "to_date": str(end)}
	from tanesw_integration import outage

	return {
		"tanesw_paused": outage.status(),
		"from_date": str(start),
		"to_date": str(end),
		"company": company,
		"targets_available": frappe.db.exists("DocType", "KPI Target") is not None,
		"movement": [
			{
				"key": "allocated",
				"label": "Allocated (vessel arrived)",
				"split": _split(allocated),
				"target": alloc_target,
				"pct": pct(len(allocated), alloc_target),
				"report": "TANeSW Container Allocation",
				"filters": rng,
			},
			{
				"key": "received",
				"label": "Received at our ICD",
				"split": _split(received),
				"target": recv_target,
				"pct": pct(len(received), recv_target),
				"report": "TANeSW Container Dwell",
				"filters": {"status": "Received at ICD"},
			},
			{
				"key": "delivered",
				"label": "Left our ICD",
				"split": _split(delivered),
				"list": "TANeSW Container",
				"list_filters": {"left_icd_on": ["between", [str(start), str(end)]]},
			},
			{
				"key": "diverted",
				"label": "Diverted to another ICD",
				"split": _split(diverted),
				"bad": True,
				"report": "TANeSW Diverted Containers",
				"filters": rng,
			},
			{
				"key": "removed",
				"label": "Removed from our allocation",
				"split": _split(removed),
				"bad": True,
				"list": "TANeSW Container",
				"list_filters": {"removed_from_allocation_on": ["between", [str(start), str(end)]]},
			},
		],
		"port_now": [
			{
				"key": "at_port",
				"label": "Still at the port",
				"split": _split(at_port),
				"report": "TANeSW Container Dwell",
				"filters": {"status": "At Terminal"},
			},
			{
				"key": "over_now",
				"label": "Over free days now",
				"split": _split(over_now),
				"bad": True,
				"report": "TANeSW Container Dwell",
				"filters": {"status": "At Terminal", "storage_status": ps.CHARGED},
			},
			{
				"key": "ending",
				"label": f"Free days end in {ps.WARN_DAYS} days or less",
				"split": _split(ending),
				"warn": True,
				"report": "TANeSW Container Dwell",
				"filters": {"status": "At Terminal", "storage_status": ps.ENDING},
			},
			{
				"key": "avg_dwell",
				"label": "Avg days at the port",
				"value_only": True,
				"values": {
					"Local": avg([b for b in at_port if b.cargo_type == ps.LOCAL]),
					"Transit": avg([b for b in at_port if b.cargo_type == ps.TRANSIT]),
				},
			},
		],
		"port_range": [
			{
				"key": "left_late",
				"label": "Left the port after free days",
				"split": _split(left_late),
				"bad": True,
				"report": "TANeSW Container Dwell",
				"filters": {"status": "", "storage_status": ps.LEFT_CHARGED},
			},
			{
				"key": "chargeable",
				"label": "Chargeable port days (Single / Double)",
				"value_only": True,
				"values": {
					"Single": sum(b.port.single_days for b in left_late),
					"Double": sum(b.port.double_days for b in left_late),
				},
			},
		],
		"attention": [
			{
				"label": "Landed, not declared",
				"value": sum(1 for b in at_port if not b.declared_on),
				"report": "TANeSW Container Pipeline",
				"filters": {"stage": "Landed, to declare"},
			},
			{
				"label": "Declared, not gated out",
				"value": sum(1 for b in at_port if b.declared_on),
				"report": "TANeSW Container Pipeline",
				"filters": {"stage": "Declared, waiting for pick-up"},
			},
			{
				"label": "Carry-in exceptions",
				"value": frappe.db.count("TANeSW Carry In Container", {"link_status": "Exception"}),
				"list": "TANeSW Carry In Container",
				"list_filters": {"link_status": "Exception"},
			},
			{
				"label": "Receptions posted late (range)",
				"value": late,
				"report": "TANeSW Reception Date Check",
				"filters": dict(rng, status="Posted Late"),
			},
			{
				"label": "Storage days lost, late posting (range)",
				"value": int(lost),
				"report": "TANeSW Reception Date Check",
				"filters": dict(rng, only_storage_lost=1),
			},
		]
		+ [
			{
				"label": a,
				"value": n,
				"list": "Container Allocation Track log",
				"list_filters": {"anomaly_type": a},
			}
			for a, n in sorted(anomalies.items())
		],
		"chart_received": {
			"labels": [x.strftime("%d %b") for x in days],
			"datasets": [
				{"name": t, "values": per_day[t]}
				for t in (ps.LOCAL, ps.TRANSIT, ps.UNKNOWN)
				if any(per_day[t])
			],
		},
	}


def erp_gate_outs(start, end, company=None):
	"""Boxes that left our ICD by a confirmed Gate Out between start and end, split Local / Transit. Counted once per
	manifest and container (an LCL box has a gate pass per House B/L). Covers every box, tracked by TANeSW or not."""
	from tanesw_integration import port_storage as ps

	out = {"total": 0, ps.LOCAL: 0, ps.TRANSIT: 0, ps.UNKNOWN: 0}
	if not frappe.db.exists("DocType", "Gate Pass"):
		return out
	filters = {"docstatus": 1, "gate_out_date": ["between", [f"{start} 00:00:00", f"{end} 23:59:59"]]}
	if company:
		filters["company"] = company
	if frappe.db.has_column("Gate Pass", "workflow_state"):  # live runs the Gate Pass workflow; dev has none
		filters["workflow_state"] = "Gate Out Confirmed"
	boxes = {}
	for r in frappe.get_all("Gate Pass", filters=filters, fields=["manifest", "container_no", "m_bl_no"]):
		boxes.setdefault((r.manifest, (r.container_no or "").upper()), r.m_bl_no)
	if not boxes:
		return out
	mrn_of = dict(
		frappe.get_all(
			"Manifest",
			filters={"name": ["in", list({m for m, _c in boxes if m})]},
			fields=["name", "mrn"],
			as_list=True,
		)
	)
	types = ps.cargo_types((mrn_of.get(m), bl) for (m, _c), bl in boxes.items())
	for (m, _c), bl in boxes.items():
		out[ps.cargo_type_of(types, mrn_of.get(m), bl)] += 1
	out["total"] = len(boxes)
	return out
