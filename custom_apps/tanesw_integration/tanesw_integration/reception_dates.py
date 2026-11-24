"""Container Reception date vs TANeSW carry-in date -> TANeSW Reception Date Check (one row per reception).

Why: icd_tz stamps a reception's Posting Date with the day it is TYPED IN (before_save: posting_date = nowdate()),
and its Received Date (storage start) follows the Posting Date once that is 48 h or more after the Ship D/C Date
(ICD Setting received_date_threshold_hours). The clerk does type the real gate time into ICD Time In, but a box
carried in at 22:37 on the 14th and entered on the 16th starts storage on the 16th: two free days the customer never
had. Receptions posted one to three days after the carry-in are common, and each such day is storage not charged.

Hourly, when "Check Reception Dates Against TANeSW" is ticked in TANeSW Settings and icd_tz is installed:
  for every submitted Container Reception of the last LOOKBACK_DAYS whose box TANeSW tracks for that MRN, compare
  Posting Date + ICD Time In with the TANeSW carry-in at our ICD (TANeSW Container.received_on, the 'Carry In Report
  Approved' event; else the carry-in report's own time in TANeSW Carry In Container) and record:
    Matches / Posted Late / Posted Early / Time Differs (same day, more than TIME_TOLERANCE_HOURS apart) /
    No TANeSW Carry-In (TANeSW tracks the box but shows no carry-in at our ICD)
  plus the Received Date the B/L should have (icd_tz's own rule: storage counts from the B/L's LAST box, so the
  latest carry-in on the B/L, with the same 48 h threshold) and the storage days that shift costs.
  Read-only for submitted receptions: icd_tz has no way to correct a Posting Date after submit and this app never
  writes its tables directly, so they are flagged for Operations/Finance, not changed.

Prevention, on every Container Reception save/submit (doc_events validate), by "On Reception Save":
  Off     nothing.
  Warn    tells the clerk the TANeSW carry-in date when the Posting Date differs.
  Correct sets Posting Date + ICD Time In to the TANeSW carry-in and lets icd_tz recompute the Received Date with
          its own method (set_received_date), so its 48 h rule still decides the storage start.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime, nowdate

SETTINGS = "TANeSW Settings"
DOCTYPE = "TANeSW Reception Date Check"
RECEPTION = "Container Reception"
JOB_ID = "tanesw_reception_dates"
LOOKBACK_DAYS = 45
TIME_TOLERANCE_HOURS = 3
DEFAULT_THRESHOLD_HOURS = 48  # icd_tz's ICD Setting default; read per company below
MATCHES, LATE, EARLY, TIME_DIFFERS, NO_CARRY_IN = (
	"Matches",
	"Posted Late",
	"Posted Early",
	"Time Differs",
	"No TANeSW Carry-In",
)


def enabled():
	return bool(
		cint(frappe.db.get_single_value(SETTINGS, "enable_reception_date_check"))
		and "icd_tz" in frappe.get_installed_apps()
	)


def enqueue_reception_date_check():
	if enabled():
		frappe.enqueue(
			"tanesw_integration.reception_dates.check_reception_dates",
			queue="long",
			timeout=1500,
			job_id=JOB_ID,
			deduplicate=True,
		)


@frappe.whitelist(methods=["POST"])
def run_now():
	frappe.only_for("System Manager")
	frappe.enqueue(
		"tanesw_integration.reception_dates.check_reception_dates",
		queue="long",
		timeout=1500,
		job_id=JOB_ID,
		deduplicate=True,
		force=True,
	)
	return _("Reception date check queued. Refresh TANeSW Settings in a minute to see the result.")


# --------------------------------------------------------------------------- background job
def check_reception_dates(force=False):
	if not (enabled() or force):
		return {"status": "off"}
	receptions = _receptions()
	carry = carry_in_times({(r.mrn, r.container_no) for r in receptions if r.mrn})
	tracked = tracked_boxes({r.mrn for r in receptions if r.mrn})
	bl_last = last_carry_in_per_bl(receptions, carry)
	stats = {
		"checked": 0,
		MATCHES: 0,
		LATE: 0,
		EARLY: 0,
		TIME_DIFFERS: 0,
		NO_CARRY_IN: 0,
		"storage_days_lost": 0,
	}
	for r in receptions:
		key = (r.mrn, r.container_no)
		if key not in tracked:
			continue  # vessel or box not tracked on TANeSW: nothing to compare with
		v = compare(r, carry.get(key), bl_last.get((r.manifest, r.m_bl_no)), threshold_hours(r.company))
		_upsert(v)
		stats["checked"] += 1
		stats[v["status"]] += 1
		stats["storage_days_lost"] += max(v.get("storage_days_lost") or 0, 0)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background job: keep each finished reception if a later one fails
	_record(stats)
	return stats


def _receptions():
	CR, M = frappe.qb.DocType("Container Reception"), frappe.qb.DocType("Manifest")
	return (
		frappe.qb.from_(CR)
		.join(M)
		.on(M.name == CR.manifest)
		.select(
			CR.name,
			CR.container_no,
			CR.manifest,
			M.mrn,
			CR.m_bl_no,
			CR.freight_indicator,
			CR.company,
			CR.posting_date,
			CR.icd_time_in,
			CR.received_date,
			CR.ship_dc_date,
			CR.clerk,
		)
		.where((CR.docstatus == 1) & (CR.posting_date >= add_days(nowdate(), -LOOKBACK_DAYS)))
		.run(as_dict=True)
	)


def carry_in_times(keys):
	"""(mrn, container) -> (carry-in datetime, source). The tracking event wins; the carry-in report (5-minute job)
	fills boxes the hourly tracking has not reached yet."""
	if not keys:
		return {}
	mrns = list({k[0] for k in keys})
	out = {}
	for r in frappe.get_all(
		"TANeSW Carry In Container",
		filters={"mrn": ["in", mrns], "entry_confirmed": 1, "carry_in_on": ["is", "set"]},
		fields=["mrn", "container_no", "carry_in_on"],
		order_by="carry_in_on asc",
	):
		out.setdefault((r.mrn, r.container_no), (get_datetime(r.carry_in_on), "Carry-In Report"))
	for r in frappe.get_all(
		"TANeSW Container",
		filters={"mrn": ["in", mrns], "received_on": ["is", "set"]},
		fields=["mrn", "container_no", "received_on"],
	):
		out[(r.mrn, r.container_no)] = (get_datetime(r.received_on), "TANeSW Tracking")
	return {k: v for k, v in out.items() if k in keys}


def tracked_boxes(mrns):
	if not mrns:
		return set()
	rows = frappe.get_all(
		"TANeSW Container", filters={"mrn": ["in", list(mrns)]}, fields=["mrn", "container_no"]
	)
	rows += frappe.get_all(
		"TANeSW Carry In Container", filters={"mrn": ["in", list(mrns)]}, fields=["mrn", "container_no"]
	)
	return {(r.mrn, r.container_no) for r in rows}


def last_carry_in_per_bl(receptions, carry):
	"""(manifest, B/L) -> latest arrival date of its boxes: the TANeSW carry-in, or the Posting Date where TANeSW has
	none. icd_tz starts storage for the whole B/L from its last box."""
	out = {}
	for r in receptions:
		c = carry.get((r.mrn, r.container_no))
		d = c[0].date() if c else getdate(r.posting_date)
		k = (r.manifest, r.m_bl_no)
		if k not in out or d > out[k]:
			out[k] = d
	return out


def threshold_hours(company):
	cache = getattr(frappe.local, "tanesw_rd_threshold", None)
	if cache is None:
		cache = frappe.local.tanesw_rd_threshold = {}
	if company not in cache:
		v = None
		if frappe.db.exists("DocType", "ICD Setting"):
			v = frappe.db.get_value("ICD Setting", {"company": company}, "received_date_threshold_hours")
		cache[company] = cint(v) if v not in (None, "") else DEFAULT_THRESHOLD_HOURS
	return cache[company]


def received_date_rule(arrival_date, ship_dc_date, threshold):
	"""icd_tz's get_received_date, on dates: the arrival date once it is `threshold` hours or more after the Ship D/C
	Date, otherwise the Ship D/C Date. Re-stated here (this app does not import icd_tz internals)."""
	if not ship_dc_date:
		return getdate(arrival_date)
	a, s = getdate(arrival_date), getdate(ship_dc_date)
	return a if (a - s).days * 24 >= threshold else s


def compare(r, carry, bl_last, threshold):
	"""One reception against its TANeSW carry-in -> the values of its Reception Date Check row."""
	v = {
		"reception": r.name,
		"container_no": r.container_no,
		"manifest": r.manifest,
		"mrn": r.mrn,
		"m_bl_no": r.m_bl_no,
		"freight_indicator": r.freight_indicator,
		"clerk": r.clerk,
		"posting_date": r.posting_date,
		"icd_time_in": r.icd_time_in,
		"erp_received_date": r.received_date,
		"ship_dc_date": r.ship_dc_date,
		"checked_on": now_datetime(),
		"carry_in_on": None,
		"carry_in_source": None,
		"days_late": None,
		"hours_off": None,
		"expected_received_date": None,
		"storage_days_lost": None,
	}
	if not carry:
		v["status"] = NO_CARRY_IN
		return v
	at, source = carry
	v.update(carry_in_on=at, carry_in_source=source)
	posted = getdate(r.posting_date)
	v["days_late"] = (posted - at.date()).days
	erp_at = get_datetime(f"{posted} {r.icd_time_in}") if r.icd_time_in else None
	v["hours_off"] = round((erp_at - at).total_seconds() / 3600, 1) if erp_at else None
	if v["days_late"] > 0:
		v["status"] = LATE
	elif v["days_late"] < 0:
		v["status"] = EARLY
	elif v["hours_off"] is not None and abs(v["hours_off"]) > TIME_TOLERANCE_HOURS:
		v["status"] = TIME_DIFFERS
	else:
		v["status"] = MATCHES
	expected = received_date_rule(bl_last or at.date(), r.ship_dc_date, threshold)
	v["expected_received_date"] = expected
	if r.received_date:
		v["storage_days_lost"] = (getdate(r.received_date) - expected).days
	return v


def _upsert(v):
	name = frappe.db.exists(DOCTYPE, v["reception"])
	doc = frappe.get_doc(DOCTYPE, name) if name else frappe.new_doc(DOCTYPE)
	doc.update(v)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.save()
	return doc.name


def _record(stats):
	try:
		frappe.db.set_single_value(
			SETTINGS,
			{
				"reception_date_last_run": now_datetime(),
				"reception_date_last_result": json.dumps(stats, default=str),
			},
		)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background job: keep each finished reception if a later one fails
	except Exception:
		frappe.log_error(
			title="TANeSW: reception date check status not saved", message=frappe.get_traceback()
		)


# --------------------------------------------------------------------------- on save / submit (doc_events)
def on_reception_validate(doc, method=None):
	"""Container Reception validate (runs on save and on submit). Never blocks: a failure here is logged."""
	try:
		if not cint(frappe.db.get_single_value(SETTINGS, "enable_reception_date_check")):
			return  # off until 'Check Reception Dates Against TANeSW' is ticked (like every other feature)
		mode = frappe.db.get_single_value(SETTINGS, "reception_date_on_save") or "Off"
		if mode == "Off" or doc.docstatus == 2 or not doc.container_no or not doc.manifest:
			return
		if (
			doc.docstatus == 1
			and not doc.is_new()
			and frappe.db.get_value(RECEPTION, doc.name, "docstatus") == 1
		):
			return  # already submitted: only the hourly job looks at it
		mrn = frappe.db.get_value("Manifest", doc.manifest, "mrn")
		carry = carry_in_times({(mrn, doc.container_no)}).get((mrn, doc.container_no)) if mrn else None
		if not carry:
			return
		at = carry[0]
		if doc.ship_dc_date and at.date() < getdate(doc.ship_dc_date):
			return  # a carry-in before discharge belongs to an earlier visit of the box
		if getdate(doc.posting_date or nowdate()) == at.date():
			return  # icd_tz fills an empty Posting Date with today
		if mode == "Correct":
			old = doc.posting_date
			doc.posting_date = at.date()
			doc.icd_time_in = at.strftime("%H:%M:%S")
			if hasattr(doc, "set_received_date"):
				doc.set_received_date()  # icd_tz's own rule decides the storage start
			frappe.msgprint(
				_("Posting Date set to {0} {1}, the TANeSW carry-in of {2} (was {3}).").format(
					frappe.bold(at.date()), at.strftime("%H:%M"), doc.container_no, old or _("empty")
				),
				indicator="blue",
				alert=True,
			)
		else:
			frappe.msgprint(
				_(
					"TANeSW shows {0} carried in on {1} at {2}, but the Posting Date is {3}. Storage "
					"starts from the Posting Date, so check it before submitting."
				).format(
					frappe.bold(doc.container_no),
					frappe.bold(at.date()),
					at.strftime("%H:%M"),
					frappe.bold(doc.posting_date or nowdate()),
				),
				title=_("Reception date differs from TANeSW"),
				indicator="orange",
			)
	except Exception:
		frappe.log_error(title="TANeSW: reception date check on save failed", message=frappe.get_traceback())
