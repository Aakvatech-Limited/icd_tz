# Copyright (c) 2026, ICD TZ and contributors
# For license information, please see license.txt

"""Permission-aware Container calendar events showing physical yard occupancy."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today


@frappe.whitelist()
def get_events(start, end, filters=None):
    """Return all-day stays overlapping the requested calendar window.

    Arrival is inclusive and gate-out is exclusive. Open stays are shown
    through today, not projected into the future. HBL entries are excluded
    because they are not additional physical containers.
    """
    if not frappe.has_permission("Container", "read"):
        frappe.throw(_("Not permitted to view Containers."), frappe.PermissionError)

    first = getdate(start)
    last_exclusive = getdate(end)
    if last_exclusive <= first:
        return []

    conditions = [
        ["Container", "has_hbl", "=", 0],
        ["Container", "arrival_date", "<", str(last_exclusive)],
        ["Container", "arrival_date", "is", "set"],
    ]
    selected = frappe.parse_json(filters) if filters else []
    if isinstance(selected, dict):
        for fieldname, value in selected.items():
            if fieldname not in ("company", "status"):
                continue
            if value:
                conditions.append(["Container", fieldname, "=", value])
    elif isinstance(selected, list):
        # Keep only explicitly supported filters. All query values remain
        # parameterized by Frappe's permission-aware get_list.
        for criterion in selected:
            if not isinstance(criterion, (list, tuple)):
                continue
            if len(criterion) == 4:
                doctype, fieldname, operator, value = criterion
                if doctype != "Container":
                    continue
            elif len(criterion) == 3:
                fieldname, operator, value = criterion
            else:
                continue
            if fieldname in ("company", "status") and operator == "=" and value:
                conditions.append(["Container", fieldname, "=", value])

    records = frappe.get_list(
        "Container",
        fields=["name", "container_no", "arrival_date", "gate_out_date", "status"],
        filters=conditions,
        or_filters=[
            ["Container", "gate_out_date", ">", str(first)],
            ["Container", "gate_out_date", "is", "not set"],
        ],
        order_by="arrival_date asc",
        limit_page_length=0,
    )

    today_exclusive = getdate(add_days(today(), 1))
    events = []
    for record in records:
        arrival = getdate(record.arrival_date)
        departure = getdate(record.gate_out_date) if record.gate_out_date else today_exclusive
        if departure <= arrival or departure <= first:
            continue
        # Do not extend an undelivered container beyond the current day.
        if not record.gate_out_date:
            departure = min(departure, last_exclusive)
        title = record.container_no or record.name
        if record.status:
            title += " (" + record.status + ")"
        events.append(
            {
                "name": record.name,
                "start": str(arrival),
                "end": str(departure),
                "title": title,
                "status": record.status,
                "all_day": 1,
            }
        )
    return events
