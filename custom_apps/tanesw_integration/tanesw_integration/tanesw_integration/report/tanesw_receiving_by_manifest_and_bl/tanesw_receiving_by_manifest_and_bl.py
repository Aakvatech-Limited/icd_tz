"""TANeSW Receiving by Manifest & B/L: how far each manifest and each B/L has been received at our ICD.

Three levels in one tree: Manifest -> Master B/L -> container. Built only from what the background jobs already store
(TANeSW Container: status and event dates per box) plus icd_tz (Movement Order, Container Reception) when installed,
so it makes no TANeSW calls.

B/L status (diverted boxes are left out of the count: they will never reach us):
  Complete     every box of the B/L is received at our ICD (TANeSW)
  Partial      some received, some still at port / on the road
  Not started  none received yet
Last box in = when the B/L's last box was received (TANeSW). Storage for the B/L counts from its last box, so this is
the storage start date; "Storage date (ERP)" is the received date on the B/L's submitted receptions, and they should
agree. Reception Gap = received per TANeSW minus received in ERP (submitted Container Reception).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, get_datetime, getdate, nowdate

COMPLETE, PARTIAL, NOT_STARTED = "Complete", "Partial", "Not Started"


def execute(filters=None):
	f = frappe._dict(filters or {})
	f.from_date = f.from_date or add_days(nowdate(), -30)
	f.to_date = f.to_date or nowdate()
	erp = "icd_tz" in frappe.get_installed_apps()
	data, bls = get_data(f, erp)
	return get_columns(erp), data, None, None, get_summary(bls, erp)


def get_columns(erp):
	def c(name, label, ftype="Int", w=95, **kw):
		return {"fieldname": name, "label": _(label), "fieldtype": ftype, "width": w, **kw}

	cols = [
		c("label", "Manifest / B/L / Container", "Data", 230),
		c("vessel_name", "Vessel", "Data", 140),
		c("arrival_date", "Arrival", "Date", 90),
		c("bl_status", "Status", "Data", 100),
		c("boxes", "Boxes"),
		c("at_port", "At Port", w=75),
		c("in_transit", "On the Road", w=90),
		c("received", "Received (TANeSW)", w=115),
		c("diverted", "Diverted / Removed", w=110),
		c("first_in", "First Box In", "Datetime", 140),
		c("last_in", "Last Box In (storage start)", "Datetime", 160),
		c("days_open", "Days Partly Received", w=110),
	]
	if erp:
		cols += [
			c("received_erp", "Received (ERP)", w=105),
			c("reception_gap", "Reception Gap", w=100),
			c("storage_date_erp", "Storage Date (ERP)", "Date", 120),
			c("movement_order", "Movement Order", "Link", 150, options="Container Movement Order"),
			c("container_reception", "Container Reception", "Link", 150, options="Container Reception"),
		]
	cols.append(c("check", "Check", "Data", 260))
	return cols


def get_data(f, erp):
	vf = {"arrival_date": ["between", [f.from_date, f.to_date]]}
	if f.mrn:
		vf["mrn"] = f.mrn.strip().upper()
	vessels = {
		v.mrn: v
		for v in frappe.get_all(
			"TANeSW Vessel Allocation", filters=vf, fields=["mrn", "vessel_name", "arrival_date"]
		)
	}
	if not vessels:
		return [], []
	cf = {"mrn": ["in", list(vessels)]}
	if f.bl_no:
		cf["bl_no"] = f.bl_no.strip().upper()
	boxes = frappe.get_all(
		"TANeSW Container",
		filters=cf,
		order_by="mrn, bl_no, container_no",
		fields=[
			"name",
			"mrn",
			"bl_no",
			"container_no",
			"status",
			"freight_indicator",
			"received_on",
			"gate_out_on",
			"removed_from_allocation_on",
		],
	)
	for b in (
		boxes
	):  # TANeSW took it off our allocation and no ICD has it yet: not expected here, like a diverted box
		if b.removed_from_allocation_on and b.status not in ("Received at ICD", "Diverted"):
			b.status = "Removed From Our Allocation"
	erp_box = _erp_boxes(list(vessels)) if erp else {}

	# group: manifest -> B/L -> boxes
	tree = {}
	for b in boxes:
		tree.setdefault(b.mrn, {}).setdefault(b.bl_no or _("(no B/L)"), []).append(b)

	data, all_bls, today = [], [], getdate(nowdate())
	for mrn in sorted(
		tree, key=lambda m: (vessels[m].arrival_date or getdate("1900-01-01"), m), reverse=True
	):
		v = vessels[mrn]
		bl_rows = []
		for bl, items in sorted(tree[mrn].items()):
			r = _bl_row(mrn, bl, items, erp, erp_box, today)
			if f.status and r.bl_status != f.status:
				continue
			bl_rows.append((r, items))
		if not bl_rows:
			continue
		m = _sum_row([r for r, _ in bl_rows], erp)
		m.update(
			id=mrn,
			parent_id=None,
			indent=0,
			label=f"{mrn}",
			vessel_name=v.vessel_name,
			arrival_date=v.arrival_date,
			bl_status=_("{0} of {1} B/Ls complete").format(
				sum(1 for r, _ in bl_rows if r.bl_status == COMPLETE), len(bl_rows)
			),
		)
		if erp:
			m.check = (
				""
				if not m.reception_gap
				else _("{0} received on TANeSW without a submitted reception").format(m.reception_gap)
				if m.reception_gap > 0
				else _("{0} receptions TANeSW does not show as received").format(-m.reception_gap)
			)
		data.append(m)
		for r, items in bl_rows:
			all_bls.append(r)
			data.append(r)
			for b in items:
				data.append(_box_row(r.id, b, erp, erp_box))
	return data, all_bls


def _bl_row(mrn, bl, items, erp, erp_box, today):
	def count(s):
		return sum(1 for b in items if b.status == s)

	r = frappe._dict(
		id=f"{mrn}|{bl}",
		parent_id=mrn,
		indent=1,
		label=bl,
		boxes=len(items),
		at_port=count("At Terminal") + count("Not Discharged"),
		in_transit=count("In Transit"),
		received=count("Received at ICD"),
		diverted=count("Diverted") + count("Removed From Our Allocation"),
	)
	expected = r.boxes - r.diverted
	ins = sorted(
		get_datetime(b.received_on) for b in items if b.status == "Received at ICD" and b.received_on
	)
	r.first_in = ins[0] if ins else None
	r.bl_status = COMPLETE if expected and r.received >= expected else PARTIAL if r.received else NOT_STARTED
	r.last_in = ins[-1] if ins and r.bl_status == COMPLETE else None
	r.days_open = date_diff(today, r.first_in) if r.bl_status == PARTIAL and r.first_in else None
	notes = []
	if erp:
		e = [erp_box.get((mrn, b.container_no)) or {} for b in items]
		r.received_erp = sum(1 for x in e if x.get("received"))
		r.reception_gap = r.received - r.received_erp
		dates = [x["received_date"] for x in e if x.get("received_date")]
		r.storage_date_erp = max(dates) if dates else None
		if r.reception_gap > 0:
			notes.append(_("{0} in the yard per TANeSW, no submitted reception").format(r.reception_gap))
		if (
			r.bl_status == COMPLETE
			and r.storage_date_erp
			and r.last_in
			and getdate(r.storage_date_erp) != getdate(r.last_in)
		):
			notes.append(
				_("Storage date in ERP {0} is not the last box's arrival {1}").format(
					r.storage_date_erp, getdate(r.last_in)
				)
			)
	if r.bl_status == PARTIAL:
		notes.append(_("{0} box(es) still to come").format(r.at_port + r.in_transit))
	if r.diverted:
		notes.append(_("{0} diverted or removed from our allocation").format(r.diverted))
	r.check = "; ".join(notes)
	return r


def _box_row(parent, b, erp, erp_box):
	r = frappe._dict(
		id=f"{parent}|{b.container_no}",
		parent_id=parent,
		indent=2,
		label=f"{b.container_no}{' (LCL)' if (b.freight_indicator or '').upper() == 'LCL' else ''}",
		bl_status=_(b.status),
		boxes=1,
		first_in=b.received_on if b.status == "Received at ICD" else None,
	)
	if erp:
		e = erp_box.get((b.mrn, b.container_no)) or {}
		r.update(
			movement_order=e.get("order"),
			container_reception=e.get("reception"),
			storage_date_erp=e.get("received_date"),
			received_erp=1 if e.get("received") else 0,
		)
		if b.status == "Received at ICD" and not e.get("received"):
			r.check = (
				_("In the yard per TANeSW, no submitted reception")
				if not e.get("reception")
				else _("Reception is still a draft")
			)
	return r


def _sum_row(rows, erp):
	keys = ["boxes", "at_port", "in_transit", "received", "diverted"] + (
		["received_erp", "reception_gap"] if erp else []
	)
	return frappe._dict({k: sum(cint(r.get(k)) for r in rows) for k in keys})


def _erp_boxes(mrns):
	"""(mrn, container) -> movement order, reception, received?, received date -- from icd_tz."""
	out = {}
	manifests = frappe.get_all(
		"Manifest",
		filters={"mrn": ["in", mrns], "docstatus": 1},
		fields=["name", "mrn"],
		order_by="creation desc",
	)
	by_name = {}
	for m in manifests:
		by_name.setdefault(m.name, m.mrn)
	if not by_name:
		return out
	names = list(by_name)
	for o in frappe.get_all(
		"Container Movement Order",
		filters={"manifest": ["in", names], "docstatus": 1, "container_no": ["is", "set"]},
		fields=["name", "manifest", "container_no"],
		order_by="creation asc",
	):
		out.setdefault((by_name[o.manifest], o.container_no), {}).setdefault("order", o.name)
	for rc in frappe.get_all(
		"Container Reception",
		filters={"manifest": ["in", names], "docstatus": ["<", 2]},
		fields=["name", "manifest", "container_no", "docstatus", "received_date"],
		order_by="docstatus desc",
	):
		e = out.setdefault((by_name[rc.manifest], rc.container_no), {})
		if rc.docstatus == 1 and not e.get("received"):
			e.update(received=1, reception=rc.name, received_date=rc.received_date)
		e.setdefault("reception", rc.name)
	return out


def get_summary(bls, erp):
	def n(s):
		return sum(1 for r in bls if r.bl_status == s)

	waiting = sum(r.at_port + r.in_transit for r in bls if r.bl_status == PARTIAL)
	cards = [
		{"label": _("B/Ls Complete"), "value": n(COMPLETE), "datatype": "Int", "indicator": "Green"},
		{"label": _("B/Ls Partly Received"), "value": n(PARTIAL), "datatype": "Int", "indicator": "Orange"},
		{"label": _("B/Ls Not Started"), "value": n(NOT_STARTED), "datatype": "Int", "indicator": "Blue"},
		{
			"label": _("Boxes Still to Come on Partly Received B/Ls"),
			"value": waiting,
			"datatype": "Int",
			"indicator": "Red" if waiting else "Green",
		},
	]
	if erp:
		gap = sum(cint(r.get("reception_gap")) for r in bls)
		cards.append(
			{
				"label": _("Received Without ERP Reception"),
				"value": gap,
				"datatype": "Int",
				"indicator": "Red" if gap > 0 else "Green",
			}
		)
	return cards


def get_message(erp):
	return (
		"<b>"
		+ _("How to read this")
		+ "</b>: "
		+ _(
			"one row per manifest (vessel); expand it for its B/Ls, expand a B/L for its containers. A B/L is Complete "
			"when every box has been received at our ICD (TANeSW), Partial while some are still at the port or on the "
			"road. Storage for a B/L counts from its last box, shown as 'Last Box In'. Diverted boxes are not expected "
			"here and are left out of the count."
		)
		+ (
			" "
			+ _(
				"Received (ERP) counts submitted Container Receptions; the Check column flags boxes in the yard without one "
				"and B/Ls whose ERP storage date is not the last box's arrival."
			)
			if erp
			else ""
		)
		+ "<br><i>"
		+ _(
			"Source: TANeSW container tracking, refreshed every 15 minutes (status every 5 minutes from carry-ins); "
			"arrival date filter applies to the vessel."
		)
		+ "</i>"
	)
