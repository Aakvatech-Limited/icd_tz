# Copyright (c) 2026, ICD TZ and contributors
# For license information, please see license.txt

"""Historical physical yard occupancy, measured in container-days.

A container is counted from arrival_date (inclusive) until gate_out_date
(exclusive). Containers without a gate-out date remain occupied.
HBL / loose cargo records do not represent additional physical containers.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, get_first_day, get_last_day, getdate, today


def execute(filters=None):
    filters = frappe._dict(filters or {})
    start, end = get_period(filters)
    columns = get_columns()
    data = get_data(filters, start, end)
    chart = {
        "data": {
            "labels": [row["period"] for row in data],
            "datasets": [
                {"name": _("Average Occupancy"), "values": [row["average_occupancy"] for row in data]},
            ],
        },
        "type": "line",
        "height": 280,
    }
    return columns, data, None, chart


def get_period(filters):
    current = getdate(today())
    span = filters.get("time_span") or "This Month"

    if span == "Today":
        start, end = current, current
    elif span == "Yesterday":
        start = end = getdate(add_days(current, -1))
    elif span == "This Week":
        start, end = getdate(add_days(current, -current.weekday())), current
    elif span == "Last Week":
        start = getdate(add_days(current, -current.weekday() - 7))
        end = getdate(add_days(start, 6))
    elif span == "This Month":
        start, end = getdate(get_first_day(current)), current
    elif span == "Last Month":
        previous = add_months(current, -1)
        start, end = getdate(get_first_day(previous)), getdate(get_last_day(previous))
    elif span == "This Year":
        start, end = getdate(str(current.year) + "-01-01"), current
    elif span == "Period":
        if not filters.get("from_date") or not filters.get("to_date"):
            frappe.throw(_("From Date and To Date are required for Period."))
        start, end = getdate(filters.from_date), getdate(filters.to_date)
    else:
        frappe.throw(_("Invalid Time Span."))

    if start > end:
        frappe.throw(_("From Date cannot be after To Date."))
    if end > current:
        frappe.throw(_("To Date cannot be in the future."))
    return start, end


def get_columns():
    return [
        {"fieldname": "period", "label": _("Period"), "fieldtype": "Data", "width": 150},
        {"fieldname": "from_date", "label": _("From Date"), "fieldtype": "Date", "width": 115},
        {"fieldname": "to_date", "label": _("To Date"), "fieldtype": "Date", "width": 115},
        {"fieldname": "days", "label": _("Days"), "fieldtype": "Int", "width": 75},
        {"fieldname": "container_days", "label": _("Container-Days"), "fieldtype": "Int", "width": 140},
        {"fieldname": "average_occupancy", "label": _("Average Occupancy"), "fieldtype": "Float", "precision": 2, "width": 160},
        {"fieldname": "peak_occupancy", "label": _("Peak Occupancy"), "fieldtype": "Int", "width": 140},
        {"fieldname": "minimum_occupancy", "label": _("Minimum Occupancy"), "fieldtype": "Int", "width": 155},
        {"fieldname": "closing_occupancy", "label": _("Closing Occupancy"), "fieldtype": "Int", "width": 155},
    ]


def get_data(filters, start, end):
    container = frappe.qb.DocType("Container")
    query = (
        frappe.qb.from_(container)
        .select(container.arrival_date, container.gate_out_date)
        .where(container.has_hbl == 0)
        .where(container.arrival_date <= end)
    )

    if filters.get("company"):
        query = query.where(container.company == filters.company)
    if filters.get("container_type"):
        query = query.where(container.type_of_container == filters.container_type)

    events = {}
    opening = 0
    for record in query.run(as_dict=True):
        if not record.arrival_date:
            continue
        arrival = getdate(record.arrival_date)
        departure = getdate(record.gate_out_date) if record.gate_out_date else None

        # Gate-out marks the first day not occupied, not the last occupied day.
        if departure and (departure <= arrival or departure <= start):
            continue

        if arrival < start:
            opening += 1
        else:
            events[arrival] = events.get(arrival, 0) + 1

        if departure and departure <= end:
            events[departure] = events.get(departure, 0) - 1

    group_by = filters.get("group_by") or "Monthly"
    if group_by not in ("Daily", "Weekly", "Monthly", "Overall"):
        frappe.throw(_("Invalid Group By."))

    periods = {}
    order = []
    day = start
    occupancy = opening
    while day <= end:
        occupancy += events.get(day, 0)

        if group_by == "Daily":
            key = str(day)
        elif group_by == "Weekly":
            key = str(getdate(add_days(day, -day.weekday())))
        elif group_by == "Monthly":
            key = str(day)[:7]
        else:
            key = "Selected Period"

        if key not in periods:
            periods[key] = {
                "period": key,
                "from_date": day,
                "to_date": day,
                "days": 0,
                "container_days": 0,
                "peak_occupancy": occupancy,
                "minimum_occupancy": occupancy,
                "closing_occupancy": occupancy,
            }
            order.append(key)

        row = periods[key]
        row["days"] += 1
        row["container_days"] += occupancy
        row["peak_occupancy"] = max(row["peak_occupancy"], occupancy)
        row["minimum_occupancy"] = min(row["minimum_occupancy"], occupancy)
        row["closing_occupancy"] = occupancy
        row["to_date"] = day
        day = getdate(add_days(day, 1))

    data = []
    for key in order:
        row = periods[key]
        row["average_occupancy"] = round(row["container_days"] / row["days"], 2)
        data.append(row)
    return data
