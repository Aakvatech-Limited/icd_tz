"""TANeSW Summary: the TANeSW figures for a date range, Local vs Transit, against the KPI Target.

Rows come from dashboard.get_dashboard (the same numbers as the workspace cards, but for any dates) plus one ERP row:
boxes that left our ICD by a confirmed Gate Out, whatever their vessel. TANeSW only tracks vessels from the last
45 days, so its 'Left our ICD' misses older stock; the ERP row shows the whole yard.
"""

import frappe
from frappe import _
from frappe.utils import get_first_day, getdate, nowdate

from tanesw_integration import dashboard
from tanesw_integration import port_storage as ps


def execute(filters=None):
	f = frappe._dict(filters or {})
	start = getdate(f.from_date or get_first_day(nowdate()))
	end = getdate(f.to_date or nowdate())
	d = dashboard.get_dashboard(str(start), str(end), f.company)
	gone = dashboard.erp_gate_outs(start, end, f.company or d["company"])
	rows = build_rows(d, gone)
	return columns(), rows, None, chart(d), summary(d, gone)


def _split_row(section, label, split, tone="", target=None, pct=None):
	split = split or {}
	return {
		"section": section,
		"measure": label,
		"total": split.get("total", 0),
		"local": split.get(ps.LOCAL, 0),
		"transit": split.get(ps.TRANSIT, 0),
		"unknown": split.get(ps.UNKNOWN, 0),
		"target": target,
		"pct": pct,
		"tone": tone,
	}


def build_rows(d, gone):
	rows = []
	sec = _("Container movement")
	for item in d["movement"]:
		label = item["label"]
		if item["key"] == "delivered":
			label = _("Left our ICD (TANeSW-tracked vessels)")
		rows.append(
			_split_row(
				sec,
				_(label),
				item.get("split"),
				"bad" if item.get("bad") else "",
				item.get("target"),
				item.get("pct"),
			)
		)
		if item["key"] == "delivered":
			rows.append(_split_row(sec, _("Left our ICD (ERP gate-outs, every box)"), gone))
	sec = _("At the port now")
	for item in d["port_now"]:
		if item.get("split"):
			tone = "bad" if item.get("bad") else ("warn" if item.get("warn") else "")
			rows.append(_split_row(sec, _(item["label"]), item["split"], tone))
	sec = _("Left the port in the period")
	for item in d["port_range"]:
		if item.get("split"):
			rows.append(_split_row(sec, _(item["label"]), item["split"], "bad"))
		elif item.get("values"):
			for band, days in item["values"].items():
				rows.append(
					{
						"section": sec,
						"measure": _("Chargeable port days: {0}").format(_(band)),
						"total": days,
						"tone": "bad" if days else "",
					}
				)
	sec = _("Needs attention")
	for item in d["attention"]:
		rows.append(
			{
				"section": sec,
				"measure": _(item["label"]),
				"total": item.get("value") or 0,
				"tone": "bad" if item.get("value") else "",
			}
		)
	return rows


def columns():
	def c(fn, label, ft="Int", w=110, **k):
		return {"fieldname": fn, "label": _(label), "fieldtype": ft, "width": w, **k}

	return [
		c("section", "Section", "Data", 190),
		c("measure", "Measure", "Data", 320),
		c("total", "Total"),
		c("local", "Local"),
		c("transit", "Transit"),
		c("unknown", "Unknown", w=90),
		c("target", "Target"),
		c("pct", "% of Target", "Percent", 110),
	]


def summary(d, gone):
	by_key = {i["key"]: i for i in d["movement"]}
	avg = next((i for i in d["port_now"] if i["key"] == "avg_dwell"), {}).get("values", {})
	over = next((i for i in d["port_now"] if i["key"] == "over_now"), {}).get("split", {})
	cards = []
	for key, label in (("allocated", "Allocated"), ("received", "Received")):
		item = by_key.get(key, {})
		value = item.get("split", {}).get("total", 0)
		pct = item.get("pct")
		cards.append(
			{
				"label": _(label) + (f" ({pct}% of target)" if pct is not None else ""),
				"value": value,
				"datatype": "Int",
				"indicator": "Green" if (pct or 0) >= 100 else ("Orange" if pct else "Blue"),
			}
		)
	cards += [
		{"label": _("Left our ICD (ERP)"), "value": gone["total"], "datatype": "Int", "indicator": "Blue"},
		{
			"label": _("Over Free Days Now"),
			"value": over.get("total", 0),
			"datatype": "Int",
			"indicator": "Red" if over.get("total") else "Green",
		},
		{"label": _("Avg Days at Port: Local"), "value": avg.get("Local", 0), "datatype": "Float"},
		{"label": _("Avg Days at Port: Transit"), "value": avg.get("Transit", 0), "datatype": "Float"},
	]
	return cards


def chart(d):
	data = d.get("chart_received") or {}
	if not data.get("datasets"):
		return None
	return {
		"data": data,
		"type": "bar",
		"barOptions": {"stacked": 1},
		"colors": ["#2490ef", "#7c3aed", "#9ca3af"],
	}
