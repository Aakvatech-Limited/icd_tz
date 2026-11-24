"""TANeSW Diverted Containers: every box that left (or joined) our allocation after the vessel was allocated to us,
where it went and what happened to the ERP Manifest. Rows come from TANeSW Allocation Change (manifest_sync.py)."""

import frappe
from frappe import _

from tanesw_integration.manifest_sync import BACK, KEPT_ORDER, TO_ICD, TO_PORT, TRANSFERRED_OUT


def execute(filters=None):
	f = frappe._dict(filters or {})
	conds = {"detected_on": ["between", [f"{f.from_date} 00:00:00", f"{f.to_date} 23:59:59"]]}
	for k in ("mrn", "manifest", "outcome", "change_type", "container_no"):
		if f.get(k):
			conds[k] = f.get(k).strip() if isinstance(f.get(k), str) else f.get(k)
	if f.get("new_place"):
		conds["new_place"] = ["like", f"%{f.new_place}%"]
	rows = frappe.get_all(
		"TANeSW Allocation Change",
		filters=conds,
		order_by="detected_on desc",
		fields=[
			"name",
			"detected_on",
			"vessel_name",
			"mrn",
			"manifest",
			"bl_no",
			"container_no",
			"change_type",
			"outcome",
			"new_place",
			"new_place_code",
			"moved_on",
			"carried_in_at",
			"carried_in_on",
			"manifest_action",
			"movement_order",
			"container",
			"reception",
		],
	)
	return columns(), rows, None, chart(rows), summary(rows)


def columns():
	def c(fieldname, label, fieldtype="Data", width=120, **kw):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width, **kw}

	return [
		c("detected_on", "Detected On", "Datetime", 145),
		c("vessel_name", "Vessel", width=150),
		c("mrn", "MRN", width=110),
		c("manifest", "Manifest", "Link", 130, options="Manifest"),
		c("bl_no", "B/L No", width=110),
		c("container_no", "Container", width=115),
		c("change_type", "Change", width=80),
		c("outcome", "Outcome", width=175),
		c("new_place", "Went To", width=190),
		c("moved_on", "Move Approved", "Datetime", 140),
		c("carried_in_at", "Carried In At", width=170),
		c("carried_in_on", "Carried In On", "Datetime", 140),
		c("manifest_action", "ERP Manifest", width=230),
		c("movement_order", "Movement Order", "Link", 140, options="Container Movement Order"),
		c("container", "Container Record", "Link", 140, options="Container"),
	]


def summary(rows):
	[r for r in rows if r.change_type == "Removed" and r.outcome == TRANSFERRED_OUT]
	removed = [r for r in rows if r.change_type == "Removed" and r.outcome not in (BACK, TRANSFERRED_OUT)]
	places = {r.new_place for r in removed if r.outcome == TO_ICD and r.new_place}
	return [
		{
			"label": _("Left Our Allocation"),
			"value": len(removed),
			"indicator": "red" if removed else "green",
			"datatype": "Int",
		},
		{
			"label": _("Diverted to Other ICDs"),
			"value": sum(1 for r in removed if r.outcome == TO_ICD),
			"indicator": "red",
			"datatype": "Int",
		},
		{"label": _("Other ICDs Involved"), "value": len(places), "indicator": "orange", "datatype": "Int"},
		{
			"label": _("Moved to Port Facilities"),
			"value": sum(1 for r in removed if r.outcome == TO_PORT),
			"indicator": "orange",
			"datatype": "Int",
		},
		{
			"label": _("Still at the Port"),
			"value": sum(1 for r in removed if not r.carried_in_on),
			"indicator": "blue",
			"datatype": "Int",
		},
		{
			"label": _("Diverted After a Movement Order"),
			"value": sum(1 for r in removed if r.manifest_action == KEPT_ORDER),
			"indicator": "red",
			"datatype": "Int",
		},
		{
			"label": _("Added to Our Allocation"),
			"value": sum(1 for r in rows if r.change_type == "Added"),
			"indicator": "green",
			"datatype": "Int",
		},
	]


def chart(rows):
	count = {}
	for r in rows:
		if r.change_type == "Removed" and r.outcome not in (BACK, TRANSFERRED_OUT):
			key = r.new_place or _("Not traced yet")
			count[key] = count.get(key, 0) + 1
	if not count:
		return None
	top = sorted(count.items(), key=lambda x: -x[1])[:10]
	return {
		"data": {
			"labels": [k for k, _v in top],
			"datasets": [{"name": _("Boxes"), "values": [v for _k, v in top]}],
		},
		"type": "bar",
		"colors": ["#8e44ad"],
	}
