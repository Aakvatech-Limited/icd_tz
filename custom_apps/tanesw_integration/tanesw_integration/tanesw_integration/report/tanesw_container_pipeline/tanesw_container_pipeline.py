"""TANeSW Container Pipeline: every box allocated to us, from landing at the port to the ERP Reception.

Vessel rows count boxes per stage; each box row says its stage and how long it has been there. Stages come from TANeSW
Cargo Tracking (TANeSW Container, kept current by the container sync); the ERP columns from icd_tz.
  Not landed yet        -> no Discharge Result Report
  Landed, to declare    -> discharged, no ICD Transfer Declaration yet  (port free days running)
  Declared, waiting     -> declared to us, not yet out of the terminal  (truck not there yet)
  Picked up, on the road-> Gate Out at the terminal, not carried in yet
  Received              -> Carry In at our ICD
  Left our allocation   -> diverted / removed from our B/Ls
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowdate

from tanesw_integration import port_storage as ps

NOT_LANDED, TO_DECLARE, WAITING, ON_ROAD, RECEIVED, LEFT = (
	"Not landed yet",
	"Landed, to declare",
	"Declared, waiting for pick-up",
	"Picked up, on the road",
	"Received",
	"Left our allocation",
)
STAGES = (NOT_LANDED, TO_DECLARE, WAITING, ON_ROAD, RECEIVED, LEFT)
WAIT_PICKUP_HOURS = 24  # declared to us but no truck at the terminal for longer than this
ON_ROAD_HOURS = 12  # out of the terminal but not at our gate after this long


def execute(filters=None):
	f = frappe._dict(filters or {})
	now = now_datetime()
	free_days = _free_days()
	vessels = _vessels(f)
	if not vessels:
		return columns(), [], None, None, summary([], free_days)
	boxes = frappe.get_all(
		"TANeSW Container",
		filters={"mrn": ["in", list(vessels)]},
		fields=[
			"name",
			"mrn",
			"container_no",
			"bl_no",
			"status",
			"discharged_on",
			"declared_on",
			"gate_out_on",
			"received_on",
			"diverted_to",
			"removed_from_allocation_on",
			"terminal",
		],
		order_by="mrn, bl_no, container_no",
	)
	erp = _erp(vessels)
	types = ps.cargo_types((b.mrn, b.bl_no) for b in boxes)

	by_vessel = {m: [] for m in vessels}
	for b in boxes:
		b.stage, b.since, b.age_hours = stage_of(b, now)
		b.erp_order = (b.mrn, b.container_no) in erp["orders"]
		b.erp_reception = (b.mrn, b.container_no) in erp["receptions"]
		# Local 5 / Transit 15 per box (port_storage.py); the ICD Setting figure is only for the summary label
		b.free_days = ps.FREE_DAYS.get(ps.cargo_type_of(types, b.mrn, b.bl_no), ps.FREE_DAYS[ps.LOCAL])
		b.flag = flag_of(b, b.free_days)
		by_vessel[b.mrn].append(b)

	data = []
	for mrn, v in vessels.items():
		rows = by_vessel.get(mrn) or []
		if (
			f.get("open_only")
			and rows
			and all((r.stage in (RECEIVED, LEFT) and r.erp_reception) or r.stage == LEFT for r in rows)
		):
			continue
		count = {s: sum(1 for r in rows if r.stage == s) for s in STAGES}
		flags = [r for r in rows if r.flag]
		data.append(
			{
				"id": mrn,
				"parent_id": None,
				"indent": 0,
				"label": f"{v.vessel_name or ''} ({mrn})",
				"arrival_date": v.arrival_date,
				"manifest": erp["manifests"].get(mrn),
				"allocated": len([r for r in rows if r.stage != LEFT]),
				"to_declare": count[TO_DECLARE],
				"waiting": count[WAITING],
				"on_road": count[ON_ROAD],
				"received": count[RECEIVED],
				"not_landed": count[NOT_LANDED],
				"left": count[LEFT],
				"orders": sum(1 for r in rows if r.erp_order),
				"receptions": sum(1 for r in rows if r.erp_reception),
				"check": _("{0} need attention").format(len(flags)) if flags else "",
			}
		)
		if f.get("stage"):
			rows = [r for r in rows if r.stage == f.stage]
		for r in rows:
			data.append(
				{
					"id": r.name,
					"parent_id": mrn,
					"indent": 1,
					"label": r.container_no,
					"bl_no": r.bl_no,
					"stage": r.stage,
					"since": r.since,
					"age": _age(r.age_hours),
					"age_hours": r.age_hours,
					"orders": 1 if r.erp_order else 0,
					"receptions": 1 if r.erp_reception else 0,
					"check": r.flag or "",
				}
			)
	return columns(), data, None, chart(data), summary(boxes, free_days)


# --------------------------------------------------------------------------- stages
def stage_of(b, now):
	"""(stage, since, hours in that stage) of one box."""
	if b.status == "Diverted" or (b.removed_from_allocation_on and b.status != "Received at ICD"):
		return LEFT, b.removed_from_allocation_on or b.get("diverted_on"), None
	if b.status == "Received at ICD" or b.received_on:
		return RECEIVED, b.received_on, None
	if b.gate_out_on:
		return ON_ROAD, b.gate_out_on, _hours(b.gate_out_on, now)
	if b.declared_on:
		return WAITING, b.declared_on, _hours(b.declared_on, now)
	if b.discharged_on:
		return TO_DECLARE, b.discharged_on, _hours(b.discharged_on, now)
	return NOT_LANDED, None, None


def flag_of(b, free_days):
	if b.stage == TO_DECLARE and b.age_hours is not None:
		left = free_days - b.age_hours / 24
		if left <= 0:
			return _("Past the port's {0} free days: storage is being charged").format(free_days)
		if left <= 2:
			return _("{0} free day(s) left at the port: declare it").format(int(left) + 1)
	if b.stage == WAITING and (b.age_hours or 0) > WAIT_PICKUP_HOURS:
		return _("Declared {0} ago, no truck has taken it").format(_age(b.age_hours))
	if b.stage == ON_ROAD and (b.age_hours or 0) > ON_ROAD_HOURS:
		return _("Left the port {0} ago, not at our gate").format(_age(b.age_hours))
	if b.stage == RECEIVED and not b.erp_reception:
		return _("Received in TANeSW, no Container Reception in the ERP")
	if b.stage in (WAITING, ON_ROAD) and not b.erp_order:
		return _("No Movement Order in the ERP")
	return None


def _hours(since, now):
	return round(max((now - get_datetime(since)).total_seconds(), 0) / 3600, 1) if since else None


def _age(hours):
	if hours is None:
		return ""
	return f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.1f} days"


# --------------------------------------------------------------------------- data
def _vessels(f):
	conds = {}
	if f.get("mrn"):
		conds["mrn"] = f.mrn.strip().upper()
	else:
		conds["arrival_date"] = [
			"between",
			[f.from_date or add_days(nowdate(), -30), f.to_date or add_days(nowdate(), 14)],
		]
	rows = frappe.get_all(
		"TANeSW Vessel Allocation",
		filters=conds,
		fields=["mrn", "vessel_name", "arrival_date"],
		order_by="arrival_date desc",
	)
	return {r.mrn: r for r in rows}


def _erp(vessels):
	manifests = {}
	for m in frappe.get_all(
		"Manifest",
		filters={"mrn": ["in", list(vessels)], "docstatus": ["<", 2]},
		fields=["name", "mrn"],
		order_by="creation asc",
	):
		manifests[m.mrn] = m.name  # latest wins
	by_name = {v: k for k, v in manifests.items()}
	orders, receptions = set(), set()
	if by_name:
		for o in frappe.get_all(
			"Container Movement Order",
			filters={"manifest": ["in", list(by_name)], "docstatus": 1, "container_no": ["is", "set"]},
			fields=["manifest", "container_no"],
		):
			orders.add((by_name[o.manifest], (o.container_no or "").upper()))
		for r in frappe.get_all(
			"Container Reception",
			filters={"manifest": ["in", list(by_name)], "docstatus": 1},
			fields=["manifest", "container_no"],
		):
			receptions.add((by_name[r.manifest], (r.container_no or "").upper()))
	return {"manifests": manifests, "orders": orders, "receptions": receptions}


def _free_days():
	from tanesw_integration.anomalies import port_free_days

	try:
		return port_free_days()
	except Exception:
		return 7


# --------------------------------------------------------------------------- output
def columns():
	def c(fieldname, label, fieldtype="Data", width=100, **kw):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width, **kw}

	return [
		c("label", "Vessel / Container", width=230),
		c("arrival_date", "Arrival", "Date", 95),
		c("manifest", "Manifest", "Link", 125, options="Manifest"),
		c("allocated", "Allocated", "Int", 80),
		c("not_landed", "Not Landed", "Int", 85),
		c("to_declare", "To Declare", "Int", 85),
		c("waiting", "Declared, Waiting Pick-up", "Int", 120),
		c("on_road", "On the Road", "Int", 90),
		c("received", "Received", "Int", 80),
		c("left", "Left Our Allocation", "Int", 105),
		c("orders", "Movement Orders (ERP)", "Int", 110),
		c("receptions", "Receptions (ERP)", "Int", 100),
		c("bl_no", "B/L No", width=110),
		c("stage", "Stage", width=190),
		c("since", "In Stage Since", "Datetime", 140),
		c("age", "Time in Stage", width=95),
		c("check", "Check", width=330),
	]


def summary(boxes, free_days):
	open_ = [b for b in boxes if getattr(b, "stage", None)]

	def n(pred):
		return sum(1 for b in open_ if pred(b))

	return [
		{
			"label": _("To Declare"),
			"value": n(lambda b: b.stage == TO_DECLARE),
			"indicator": "orange",
			"datatype": "Int",
		},
		{
			"label": _("Past Port Free Days"),
			"value": n(lambda b: b.stage == TO_DECLARE and (b.age_hours or 0) / 24 > b.free_days),
			"indicator": "red",
			"datatype": "Int",
		},
		{
			"label": _("Declared, Waiting Pick-up"),
			"value": n(lambda b: b.stage == WAITING),
			"indicator": "blue",
			"datatype": "Int",
		},
		{
			"label": _("Waiting Over {0} h").format(WAIT_PICKUP_HOURS),
			"value": n(lambda b: b.stage == WAITING and (b.age_hours or 0) > WAIT_PICKUP_HOURS),
			"indicator": "red",
			"datatype": "Int",
		},
		{
			"label": _("On the Road"),
			"value": n(lambda b: b.stage == ON_ROAD),
			"indicator": "blue",
			"datatype": "Int",
		},
		{
			"label": _("On the Road Over {0} h").format(ON_ROAD_HOURS),
			"value": n(lambda b: b.stage == ON_ROAD and (b.age_hours or 0) > ON_ROAD_HOURS),
			"indicator": "red",
			"datatype": "Int",
		},
		{
			"label": _("Received, No ERP Reception"),
			"value": n(lambda b: b.stage == RECEIVED and not b.erp_reception),
			"indicator": "orange",
			"datatype": "Int",
		},
		{
			"label": _("Left Our Allocation"),
			"value": n(lambda b: b.stage == LEFT),
			"indicator": "gray",
			"datatype": "Int",
		},
	]


def chart(data):
	vessels = [d for d in data if d["indent"] == 0 and (d["to_declare"] or d["waiting"] or d["on_road"])][:12]
	if not vessels:
		return None
	return {
		"data": {
			"labels": [d["label"].split(" (")[0] for d in vessels],
			"datasets": [
				{"name": _("To Declare"), "values": [d["to_declare"] for d in vessels]},
				{"name": _("Waiting Pick-up"), "values": [d["waiting"] for d in vessels]},
				{"name": _("On the Road"), "values": [d["on_road"] for d in vessels]},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
		"colors": ["#f39c12", "#3498db", "#8e44ad"],
	}
