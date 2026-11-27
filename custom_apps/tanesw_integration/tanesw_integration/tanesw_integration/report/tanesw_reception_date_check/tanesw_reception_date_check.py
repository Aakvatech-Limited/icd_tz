"""TANeSW Reception Date Check: every submitted Container Reception against its TANeSW carry-in, with the storage
days a late Posting Date costs. Rows come from TANeSW Reception Date Check (reception_dates.py, hourly)."""

import frappe
from frappe import _

from tanesw_integration.reception_dates import EARLY, LATE, MATCHES, NO_CARRY_IN, TIME_DIFFERS


def execute(filters=None):
	f = frappe._dict(filters or {})
	conds = {"posting_date": ["between", [f.from_date, f.to_date]]}
	for k in ("status", "manifest", "mrn", "container_no", "clerk"):
		if f.get(k):
			conds[k] = f.get(k).strip() if isinstance(f.get(k), str) else f.get(k)
	if f.get("only_storage_lost"):
		conds["storage_days_lost"] = [">", 0]
	rows = frappe.get_all(
		"TANeSW Reception Date Check",
		filters=conds,
		order_by="posting_date desc, carry_in_on desc",
		fields=[
			"reception",
			"container_no",
			"manifest",
			"mrn",
			"m_bl_no",
			"freight_indicator",
			"clerk",
			"status",
			"carry_in_on",
			"carry_in_source",
			"posting_date",
			"icd_time_in",
			"days_late",
			"hours_off",
			"ship_dc_date",
			"erp_received_date",
			"expected_received_date",
			"storage_days_lost",
			"checked_on",
		],
	)
	return columns(), rows, None, chart(rows), summary(rows)


def columns():
	def c(fieldname, label, fieldtype="Data", width=120, **kw):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width, **kw}

	return [
		c("reception", "Container Reception", "Link", 150, options="Container Reception"),
		c("container_no", "Container", width=115),
		c("freight_indicator", "FCL/LCL", width=70),
		c("status", "Status", width=150),
		c("carry_in_on", "TANeSW Carry-In", "Datetime", 150),
		c("posting_date", "ERP Posting Date", "Date", 110),
		c("icd_time_in", "ERP Time In", "Time", 90),
		c("days_late", "Days Late", "Int", 80),
		c("hours_off", "Hours Off", "Float", 80),
		c("ship_dc_date", "Ship D/C", "Date", 100),
		c("erp_received_date", "ERP Storage Start", "Date", 120),
		c("expected_received_date", "Storage Should Start", "Date", 130),
		c("storage_days_lost", "Storage Days Lost", "Int", 110),
		c("m_bl_no", "B/L No", width=110),
		c("manifest", "Manifest", "Link", 130, options="Manifest"),
		c("clerk", "Clerk", "Link", 120, options="Employee"),
		c("carry_in_source", "Carry-In From", width=120),
	]


def summary(rows):
	n = len(rows)

	def count(s):
		return sum(1 for r in rows if r.status == s)

	lost = [r for r in rows if (r.storage_days_lost or 0) > 0]
	compared = n - count(NO_CARRY_IN)
	return [
		{"label": _("Receptions Checked"), "value": n, "indicator": "blue", "datatype": "Int"},
		{
			"label": _("Same Day as TANeSW (%)"),
			"value": round(100.0 * count(MATCHES) / compared, 1) if compared else 0,
			"indicator": "green" if compared and count(MATCHES) / compared >= 0.95 else "orange",
			"datatype": "Float",
		},
		{
			"label": _("Posted Late"),
			"value": count(LATE),
			"indicator": "red" if count(LATE) else "green",
			"datatype": "Int",
		},
		{
			"label": _("Storage Starts Late (boxes)"),
			"value": len(lost),
			"indicator": "red" if lost else "green",
			"datatype": "Int",
		},
		{
			"label": _("Storage Days Lost"),
			"value": sum(r.storage_days_lost for r in lost),
			"indicator": "red" if lost else "green",
			"datatype": "Int",
		},
		{
			"label": _("Posted Early / Time Differs"),
			"value": count(EARLY) + count(TIME_DIFFERS),
			"indicator": "orange",
			"datatype": "Int",
		},
		{
			"label": _("No TANeSW Carry-In"),
			"value": count(NO_CARRY_IN),
			"indicator": "gray",
			"datatype": "Int",
		},
	]


def chart(rows):
	days = {}
	for r in rows:
		if r.status == LATE:
			days[r.posting_date] = days.get(r.posting_date, 0) + 1
	if not days:
		return None
	keys = sorted(days)
	return {
		"data": {
			"labels": [str(k) for k in keys],
			"datasets": [{"name": _("Posted late"), "values": [days[k] for k in keys]}],
		},
		"type": "bar",
		"colors": ["#e74c3c"],
	}
