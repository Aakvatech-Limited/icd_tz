"""TANeSW vs ICD (icd_tz) reconciliation, per vessel, by vessel arrival date.

TANeSW side (stored by the background jobs, no live calls):
  Allocated / Landed / Declared  - TANeSW Vessel Allocation, refreshed every 15 minutes from the Expected ICD
                                   Transfer list (allocations.py)
  At Port / In Transit / Received / Diverted
                                 - TANeSW Container, one record per container from Cargo Tracking (containers.py)
ERP side (icd_tz, when installed on this site):
  On Manifest      - containers on the vessel's submitted Manifest whose Master B/L is delivered to our ICD
  Movement Orders  - submitted orders that name a container
  Received (ERP)   - containers with a submitted Container Reception; drafts counted separately

The two columns that matter:
  Allocation Gap = TANeSW Allocated - On Manifest   (manifest not uploaded, or B/Ls missing from it)
  Reception Gap  = TANeSW Received  - Received (ERP) (in our yard per TANeSW, no submitted reception yet)
Allocated = At Port + Not Yet Landed + In Transit + Received + Diverted is checked per vessel ("Balances").
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, nowdate

STATUS_KEYS = {
	"At Terminal": "at_port",
	"Not Discharged": "not_landed_tracked",
	"In Transit": "in_transit",
	"Received at ICD": "received",
	"Diverted": "diverted",
	"Removed": "removed",
}


def execute(filters=None):
	f = frappe._dict(filters or {})
	f.from_date = f.from_date or add_days(nowdate(), -30)
	f.to_date = f.to_date or nowdate()
	erp = "icd_tz" in frappe.get_installed_apps()
	data = get_data(f, erp)
	return get_columns(erp), data, None, get_chart(data, erp), get_summary(data, erp)


def get_columns(erp):
	def c(name, label, ftype="Int", w=100, **kw):
		return {"fieldname": name, "label": _(label), "fieldtype": ftype, "width": w, **kw}

	cols = [
		c("arrival_date", "Arrival", "Date", 95),
		c("vessel_name", "Vessel", "Data", 160),
		c("mrn", "MRN", "Data", 115),
		c("allocated", "Allocated (TANeSW)", w=110),
		c("landed", "Landed", w=75),
		c("declared", "Declared", w=80),
		c("at_port", "Still at Port", w=90),
		c("in_transit", "In Transit", w=80),
		c("received", "Received (TANeSW)", w=115),
		c("diverted", "Diverted to Other ICD", w=125),
		c("removed", "Removed From Our Allocation", w=150),
		c("tracked", "Containers Tracked", w=110),
		c("balances", "Balances", "Data", 80),
	]
	if erp:
		cols += [
			c("manifest", "Manifest", "Link", 130, options="Manifest"),
			c("on_manifest", "On Manifest (ERP)", w=110),
			c("allocation_gap", "Allocation Gap", w=100),
			c("orders", "Movement Orders", w=110),
			c("received_erp", "Received (ERP)", w=100),
			c("draft_receptions", "Draft Receptions", w=105),
			c("reception_gap", "Reception Gap", w=100),
			c("check", "Check", "Data", 230),
		]
	return cols


def get_data(f, erp):
	filters = {"arrival_date": ["between", [f.from_date, f.to_date]]}
	if f.mrn:
		filters["mrn"] = f.mrn.strip().upper()
	if f.vessel_name:
		filters["vessel_name"] = ["like", f"%{f.vessel_name.strip()}%"]
	vessels = frappe.get_all(
		"TANeSW Vessel Allocation",
		filters=filters,
		order_by="arrival_date desc, mrn",
		fields=["mrn", "vessel_name", "arrival_date", "container_count", "landed_count", "declared_count"],
	)
	if not vessels:
		return []
	mrns = [v.mrn for v in vessels]

	tracked = {}
	for b in frappe.get_all(
		"TANeSW Container",
		filters={"mrn": ["in", mrns]},
		fields=["mrn", "status", "removed_from_allocation_on"],
	):
		removed = b.removed_from_allocation_on and b.status not in ("Received at ICD", "Diverted")
		key = STATUS_KEYS.get("Removed" if removed else b.status)
		if key:
			counts = tracked.setdefault(b.mrn, {})
			counts[key] = counts.get(key, 0) + 1

	erp_rows = _erp_counts(mrns) if erp else {}
	data = []
	for v in vessels:
		t = tracked.get(v.mrn, {})
		row = frappe._dict(
			mrn=v.mrn,
			vessel_name=v.vessel_name,
			arrival_date=v.arrival_date,
			allocated=cint(v.container_count),
			landed=v.landed_count,
			declared=v.declared_count,
			in_transit=t.get("in_transit", 0),
			received=t.get("received", 0),
			diverted=t.get("diverted", 0),
			removed=t.get("removed", 0),
			tracked=sum(t.values()) - t.get("removed", 0),
		)
		row.at_port = (
			t.get("at_port", 0)
			if t
			else (
				max(cint(v.landed_count) - cint(v.declared_count), 0) if v.landed_count is not None else None
			)
		)
		not_landed = max(row.allocated - cint(v.landed_count), 0) if v.landed_count is not None else None
		if t and not_landed is not None:
			parts = (row.at_port or 0) + not_landed + row.in_transit + row.received + row.diverted
			row.balances = (
				_("Yes") if parts == row.allocated else _("Off by {0}").format(parts - row.allocated)
			)
		else:
			row.balances = _("Not tracked")
		if erp:
			e = erp_rows.get(v.mrn) or {}
			row.update(e)
			if e.get("manifest"):
				row.allocation_gap = row.allocated - cint(e.get("on_manifest"))
				row.reception_gap = row.received - cint(e.get("received_erp"))
			row.check = _check(row)
		data.append(row)
	return data


def _erp_counts(mrns):
	from tanesw_integration.api import _our_facility_code

	code = _our_facility_code()
	out = {}
	manifests = frappe.get_all(
		"Manifest",
		filters={"mrn": ["in", mrns], "docstatus": 1},
		fields=["name", "mrn"],
		order_by="creation desc",
	)
	by_name = {}
	for m in manifests:
		if m.mrn not in out:  # an amended manifest: the latest submitted one counts
			out[m.mrn] = {"manifest": m.name}
			by_name[m.name] = m.mrn
	if not by_name:
		return out
	names = list(by_name)

	from frappe.query_builder.functions import Count
	from pypika.functions import Upper

	CD, MB = frappe.qb.DocType("Containers Detail"), frappe.qb.DocType("Master BL")
	for r in (
		frappe.qb.from_(CD)
		.join(MB)
		.on((MB.parent == CD.parent) & (MB.m_bl_no == CD.m_bl_no))
		.select(CD.parent.as_("manifest"), Count(CD.container_no).distinct().as_("n"))
		.where(CD.parent.isin(names) & (Upper(MB.place_of_delivery) == code))
		.groupby(CD.parent)
		.run(as_dict=True)
	):
		out[by_name[r.manifest]]["on_manifest"] = cint(r.n)

	for r in frappe.get_all(
		"Container Movement Order",
		filters={"manifest": ["in", names], "docstatus": 1, "container_no": ["is", "set"]},
		fields=["manifest", "count(name) as n"],
		group_by="manifest",
	):
		out[by_name[r.manifest]]["orders"] = cint(r.n)

	received, drafts = {}, {}
	for r in frappe.get_all(
		"Container Reception",
		filters={"manifest": ["in", names], "docstatus": ["<", 2]},
		fields=["manifest", "container_no", "docstatus"],
	):
		if r.docstatus == 1:
			if r.container_no:  # COUNT(DISTINCT container_no) ignored empty numbers
				received.setdefault(r.manifest, set()).add(r.container_no)
			else:
				received.setdefault(r.manifest, set())
		else:
			drafts[r.manifest] = drafts.get(r.manifest, 0) + 1
	for name in names:
		if name in received or name in drafts:
			out[by_name[name]].update(
				received_erp=len(received.get(name, ())), draft_receptions=drafts.get(name, 0)
			)

	for e in out.values():
		for k in ("on_manifest", "orders", "received_erp", "draft_receptions"):
			e.setdefault(k, 0)
	return out


def _check(r):
	if not r.get("manifest"):
		return _("No submitted Manifest in ERP for this MRN")
	notes = []
	if r.allocation_gap:
		notes.append(
			_("{0} allocated not on the Manifest").format(r.allocation_gap)
			if r.allocation_gap > 0
			else _("Manifest has {0} more than TANeSW allocates").format(-r.allocation_gap)
		)
	if r.reception_gap and r.reception_gap > 0:
		notes.append(_("{0} received on TANeSW without a submitted reception").format(r.reception_gap))
	elif r.reception_gap and r.reception_gap < 0:
		notes.append(_("{0} receptions TANeSW does not show as received").format(-r.reception_gap))
	return "; ".join(notes) or _("OK")


def get_chart(data, erp):
	rows = [r for r in data if r.allocated][:15][::-1]
	if not rows:
		return None
	sets = [{"name": _("Received (TANeSW)"), "values": [r.received or 0 for r in rows]}]
	if erp:
		sets.append({"name": _("Received (ERP)"), "values": [r.get("received_erp") or 0 for r in rows]})
	sets += [
		{"name": _("Still at Port"), "values": [r.at_port or 0 for r in rows]},
		{"name": _("Diverted"), "values": [r.diverted or 0 for r in rows]},
	]
	return {
		"data": {"labels": [r.vessel_name or r.mrn for r in rows], "datasets": sets},
		"type": "bar",
		"height": 280,
	}


def get_summary(data, erp):
	def tot(k):
		return sum(cint(r.get(k)) for r in data)

	cards = [
		{"label": _("Allocated (TANeSW)"), "value": tot("allocated"), "datatype": "Int"},
		{"label": _("Still at Port"), "value": tot("at_port"), "datatype": "Int", "indicator": "Orange"},
		{"label": _("In Transit"), "value": tot("in_transit"), "datatype": "Int", "indicator": "Blue"},
		{"label": _("Received (TANeSW)"), "value": tot("received"), "datatype": "Int", "indicator": "Green"},
		{
			"label": _("Diverted to Other ICD"),
			"value": tot("diverted"),
			"datatype": "Int",
			"indicator": "Red",
		},
	]
	if erp:
		gap = tot("reception_gap")
		cards += [
			{
				"label": _("Received (ERP)"),
				"value": tot("received_erp"),
				"datatype": "Int",
				"indicator": "Green",
			},
			{
				"label": _("Reception Gap"),
				"value": gap,
				"datatype": "Int",
				"indicator": "Red" if gap > 0 else "Green",
			},
			{
				"label": _("Vessels Without Manifest"),
				"value": sum(1 for r in data if not r.get("manifest")),
				"datatype": "Int",
				"indicator": "Orange",
			},
		]
	return cards


def get_message(erp):
	erp_part = _(
		"<b>ERP side (icd_tz):</b> On Manifest = containers on the submitted Manifest delivered to our ICD; "
		"Received (ERP) = containers with a submitted Container Reception. <b>Allocation Gap</b> = TANeSW Allocated "
		"minus On Manifest. <b>Reception Gap</b> = TANeSW Received minus Received (ERP): a positive gap means boxes "
		"TANeSW shows in our yard with no submitted reception yet (check Draft Receptions first)."
	)
	no_erp = _("<b>ERP side:</b> icd_tz is not installed on this site, so only TANeSW figures are shown.")
	return "<br>".join(
		[
			_(
				"<b>What this shows:</b> per vessel arriving in the period, what TANeSW says about containers allocated to "
				"our ICD, next to what the ERP has recorded."
			),
			_(
				"<b>TANeSW side:</b> Allocated, Landed and Declared come from TANeSW's Expected ICD Transfer list "
				"(refreshed every 15 minutes). Still at Port, In Transit, Received and Diverted come from container "
				"tracking (hourly). A declared container can still be at the port until it gates out."
			),
			erp_part if erp else no_erp,
			_(
				"<b>Balances:</b> Yes when Still at Port + Not Yet Landed + In Transit + Received + Diverted = Allocated. "
				"'Not tracked' means container tracking has not read this vessel yet, so Still at Port is Landed minus "
				"Declared and may be understated."
			),
			_(
				"<b>Limits:</b> containers tracking has not reached yet (the hourly job reads up to 400 per run) are not in "
				"the tracking columns; a container whose B/L moved to another ICD shows as Diverted only once that ICD "
				"carries it in."
			),
		]
	)
