"""One row per container on our B/Ls: where it is, how long it has been (or was) at the port, and how much of that
was past the port's free days.

Port dwell = Discharge Result Report Approved (B21) -> Gate Out at the terminal (C61); for containers still at the
terminal it runs to the moment the report is opened. Free days and the Single / Double bands come from
port_storage.py (Local 5 / Transit 15, day 1 = discharge day). Data: TANeSW Container (synced hourly from Cargo
Tracking); Local / Transit from the ERP Master B/L.
"""

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now_datetime, nowdate

from tanesw_integration import port_storage as ps
from tanesw_integration.containers import dwell_days

LEFT_ALLOCATION = "Left our allocation"


def execute(filters=None):
	f = frappe._dict(filters or {})
	data = get_data(f)
	return get_columns(), data, None, None, get_summary(data)


def get_columns():
	def c(fn, label, ft="Data", w=120, **k):
		return {"fieldname": fn, "label": _(label), "fieldtype": ft, "width": w, **k}

	return [
		c("container_no", "Container No", w=130),
		c("bl_no", "B/L No", w=130),
		c("container_size", "Size", w=60),
		c("cargo_type", "Local / Transit", w=95),
		c("status", "Status", w=120),
		c("storage_status", "Port Storage", w=160),
		c("dwell_days", "Port Dwell (days)", "Float", 110, precision=1),
		c("port_days", "Port Days (Day 1 = Discharge)", "Int", 120),
		c("free_days", "Free Days", "Int", 80),
		c("free_until", "Free Until", "Date", 100),
		c("free_days_left", "Free Days Left", "Int", 100),
		c("days_over", "Days Over Free", "Int", 105),
		c("single_days", "Single Days", "Int", 90),
		c("double_days", "Double Days", "Int", 90),
		c("discharged_on", "Discharged", "Datetime", 150),
		c("declared", "Declared", "Check", 80),
		c("icd_declaration_no", "ICD Declaration No", w=180),
		c("gate_out_on", "Gate Out (Terminal)", "Datetime", 150),
		c("received_on", "Received at ICD", "Datetime", 150),
		c("terminal", "Terminal / Location", w=110),
		c("vessel_name", "Vessel", w=150),
		c("mrn", "MRN", "Link", 120, options="TANeSW Vessel Allocation"),
		c("last_event", "Last TANeSW Event", w=220),
		c("last_synced", "Last Synced", "Datetime", 150),
	]


def get_data(f):
	conds = {}
	if f.status:
		conds["status"] = f.status
	if f.mrn:
		conds["mrn"] = f.mrn.strip().upper()
	if f.vessel_name:
		conds["vessel_name"] = ["like", f"%{f.vessel_name}%"]
	if f.container_no:
		conds["container_no"] = ["like", f"%{f.container_no.strip().upper()}%"]
	if f.bl_no:
		conds["bl_no"] = ["like", f"%{f.bl_no.strip().upper()}%"]
	if f.from_date or f.to_date:
		conds["arrival_date"] = [
			"between",
			[f.from_date or add_days(nowdate(), -365), f.to_date or nowdate()],
		]

	rows = frappe.get_all(
		"TANeSW Container",
		filters=conds,
		fields=[
			"name",
			"container_no",
			"bl_no",
			"container_size",
			"status",
			"dwell_days",
			"discharged_on",
			"declared_on",
			"icd_declaration_no",
			"gate_out_on",
			"received_on",
			"terminal",
			"vessel_name",
			"mrn",
			"last_event",
			"last_synced",
			"removed_from_allocation_on",
		],
	)
	types = ps.cargo_types((r.mrn, r.bl_no) for r in rows)
	now = now_datetime()
	out = []
	for r in rows:
		if r.status == "At Terminal" and r.discharged_on:
			r.dwell_days = dwell_days(get_datetime(r.discharged_on), None, now)  # live, not as of last sync
		r.declared = 1 if r.declared_on else 0
		r.cargo_type = ps.cargo_type_of(types, r.mrn, r.bl_no)
		st = ps.storage(r.discharged_on, r.gate_out_on, r.cargo_type)
		if st:
			r.update(st)
		r.left_allocation = r.status == "Diverted" or bool(
			r.removed_from_allocation_on and r.status != "Received at ICD"
		)
		if r.left_allocation:
			r.storage_status = LEFT_ALLOCATION  # another ICD's (or nobody's) port bill, not ours
		if f.min_dwell and (r.dwell_days or 0) < float(f.min_dwell):
			continue
		if f.cargo_type and r.cargo_type != f.cargo_type:
			continue
		if f.storage_status and r.get("storage_status") != f.storage_status:
			continue
		if f.only_over_free and not (r.get("days_over") and not r.left_allocation):
			continue
		out.append(r)
	order = {"At Terminal": 0, "Not Discharged": 1, "In Transit": 2, "Received at ICD": 3, "Diverted": 4}
	out.sort(key=lambda r: (order.get(r.status, 9), -(r.get("days_over") or 0), -(r.dwell_days or 0)))
	return out


def get_summary(data):
	ours = [r for r in data if not r.left_allocation]
	at_t = [r for r in ours if r.status == "At Terminal"]

	def by(rows, t):
		return [r for r in rows if r.cargo_type == t]

	def avg(rows):
		return round(sum(r.dwell_days or 0 for r in rows) / len(rows), 1) if rows else 0

	over_now = [r for r in at_t if r.get("storage_status") == ps.CHARGED]
	ending = [r for r in at_t if r.get("storage_status") == ps.ENDING]
	over_all = [r for r in ours if r.get("days_over")]

	def count(s):
		return sum(1 for r in data if r.status == s)

	unknown = sum(1 for r in ours if r.discharged_on and r.cargo_type == ps.UNKNOWN)
	cards = [
		{
			"label": _("At Terminal: Local"),
			"value": len(by(at_t, ps.LOCAL)),
			"datatype": "Int",
			"indicator": "Orange",
		},
		{
			"label": _("At Terminal: Transit"),
			"value": len(by(at_t, ps.TRANSIT)),
			"datatype": "Int",
			"indicator": "Orange",
		},
		{
			"label": _("Over Free Days Now: Local"),
			"value": len(by(over_now, ps.LOCAL)),
			"datatype": "Int",
			"indicator": "Red" if by(over_now, ps.LOCAL) else "Green",
		},
		{
			"label": _("Over Free Days Now: Transit"),
			"value": len(by(over_now, ps.TRANSIT)),
			"datatype": "Int",
			"indicator": "Red" if by(over_now, ps.TRANSIT) else "Green",
		},
		{
			"label": _("Free Days End in {0} Days or Less").format(ps.WARN_DAYS),
			"value": len(ending),
			"datatype": "Int",
			"indicator": "Orange" if ending else "Green",
		},
		{"label": _("Avg Dwell at Terminal: Local"), "value": avg(by(at_t, ps.LOCAL)), "datatype": "Float"},
		{
			"label": _("Avg Dwell at Terminal: Transit"),
			"value": avg(by(at_t, ps.TRANSIT)),
			"datatype": "Float",
		},
		{
			"label": _("Chargeable Days (Single / Double)"),
			"value": f"{sum(r.single_days for r in over_all)} / {sum(r.double_days for r in over_all)}",
			"datatype": "Data",
			"indicator": "Red" if over_all else "Green",
		},
		{"label": _("In Transit"), "value": count("In Transit"), "datatype": "Int", "indicator": "Blue"},
		{
			"label": _("Received at ICD"),
			"value": count("Received at ICD"),
			"datatype": "Int",
			"indicator": "Green",
		},
		{
			"label": _("Diverted to Other ICD"),
			"value": count("Diverted"),
			"datatype": "Int",
			"indicator": "Red",
		},
	]
	if unknown:
		cards.append(
			{
				"label": _("Local / Transit Unknown (no ERP B/L)"),
				"value": unknown,
				"datatype": "Int",
				"indicator": "Gray",
			}
		)
	return cards
