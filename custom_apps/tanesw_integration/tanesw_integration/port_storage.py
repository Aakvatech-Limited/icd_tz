"""Port storage at the terminal (DP World / TEAGTL): the one place the rule lives.

Rule:
  - Day 1 is the discharge day (TANeSW B21 Discharge Result Report Approved).
  - Free days: Local 5, Transit 15. Then 7 Single days, then Double.
      Local:   Free 1-5,  Single 6-12,  Double 13+
      Transit: Free 1-15, Single 16-22, Double 23+
  - Charged only while the box is at the port: the count stops at the terminal Gate Out (C61),
    which is when the box is handed to our driver. The gate-out day counts as a port day.
Local vs Transit comes from the ERP Master B/L cargo classification (IM = Local, TR = Transit).
A box whose B/L is not on an ERP Manifest is "Unknown" and is held to the Local 5 days (the earlier warning).
"""

import frappe
from frappe.utils import add_days, date_diff, getdate, nowdate

LOCAL, TRANSIT, UNKNOWN = "Local", "Transit", "Unknown"
FREE_DAYS = {LOCAL: 5, TRANSIT: 15}
SINGLE_BAND_DAYS = 7
WARN_DAYS = 2  # "free days end soon" when this many days or fewer are left

WITHIN, ENDING, CHARGED, LEFT_FREE, LEFT_CHARGED = (
	"Within free days",
	"Free days ending",
	"Over free days",
	"Left within free days",
	"Left after free days",
)


def classify(code):
	code = (code or "").strip().upper()
	return TRANSIT if code == "TR" else LOCAL if code == "IM" else UNKNOWN


def cargo_types(pairs):
	"""{(MRN, B/L No): Local | Transit} from the ERP Master B/Ls of those MRNs. Missing pairs are Unknown."""
	mrns = tuple({(m or "").upper() for m, _b in pairs if m})
	if not mrns:
		return {}
	from frappe.query_builder import Order

	MBL, M = frappe.qb.DocType("Master BL"), frappe.qb.DocType("Manifest")
	rows = (
		frappe.qb.from_(MBL)
		.join(M)
		.on(M.name == MBL.parent)
		.select(M.mrn, MBL.m_bl_no, MBL.cargo_classification)
		.where((M.docstatus < 2) & M.mrn.isin(list(mrns)))
		.orderby(M.docstatus, order=Order.desc)
		.orderby(M.creation, order=Order.desc)
		.run(as_dict=True)
	)
	out = {}
	for r in rows:
		key = ((r.mrn or "").upper(), (r.m_bl_no or "").strip().upper())
		out.setdefault(key, classify(r.cargo_classification))  # submitted / latest manifest wins
	return out


def cargo_type_of(types, mrn, bl_no):
	return types.get(((mrn or "").upper(), (bl_no or "").strip().upper()), UNKNOWN)


def storage(discharged_on, gate_out_on, cargo_type, today=None):
	"""Port storage position of one box, or None when it has not been discharged."""
	if not discharged_on:
		return None
	start = getdate(discharged_on)
	at_port = not gate_out_on
	end = getdate(today or nowdate()) if at_port else getdate(gate_out_on)
	days = max(date_diff(end, start) + 1, 0)
	free = FREE_DAYS.get(cargo_type, FREE_DAYS[LOCAL])
	over = max(days - free, 0)
	single = min(over, SINGLE_BAND_DAYS)
	left = free - days if at_port else None
	if at_port:
		status = CHARGED if over else (ENDING if left is not None and left <= WARN_DAYS else WITHIN)
	else:
		status = LEFT_CHARGED if over else LEFT_FREE
	return frappe._dict(
		port_days=days,
		free_days=free,
		free_until=add_days(start, free - 1),
		days_over=over,
		single_days=single,
		double_days=over - single,
		free_days_left=left,
		at_port=at_port,
		storage_status=status,
	)
