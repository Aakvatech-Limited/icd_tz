# Copyright (c) 2026, ICD TZ and contributors
# For license information, please see license.txt

"""Permission-aware inspection booking calendar.

Booking inspection_date is the scheduled date. The existing Container
Inspection document is linked where present, but does not create a second
booking entry.
"""

import frappe
from frappe import _
from frappe.utils import getdate


@frappe.whitelist()
def get_events(start, end, filters=None, **kwargs):
    if not frappe.has_permission("In Yard Container Booking", "read"):
        frappe.throw(_("Not permitted to view Container Bookings."), frappe.PermissionError)

    first, last = getdate(start), getdate(end)
    if last <= first:
        return []

    conditions = [
        ["inspection_date", ">=", str(first)],
        ["inspection_date", "<", str(last)],
        ["docstatus", "!=", 2],
    ]

    selected = frappe.parse_json(filters) if filters else []
    allowed = ("company", "inspection_location", "c_and_f_company", "clearing_agent")
    if isinstance(selected, dict):
        for fieldname in allowed:
            if selected.get(fieldname):
                conditions.append([fieldname, "=", selected[fieldname]])
    elif isinstance(selected, list):
        for item in selected:
            if not isinstance(item, (list, tuple)):
                continue
            if len(item) == 4 and item[0] == "In Yard Container Booking":
                fieldname, operator, value = item[1:]
            elif len(item) == 3:
                fieldname, operator, value = item
            else:
                continue
            if fieldname in allowed and operator == "=" and value:
                conditions.append([fieldname, "=", value])

    records = frappe.get_list(
        "In Yard Container Booking",
        fields=[
            "name",
            "container_no",
            "container_id",
            "inspection_date",
            "inspection_location",
            "container_inspection",
            "is_additional_booking",
            "docstatus",
        ],
        filters=conditions,
        order_by="inspection_date asc",
        limit_page_length=0,
    )

    events = []
    for row in records:
        label = row.container_no or row.container_id or row.name
        if row.inspection_location:
            label += " - " + row.inspection_location
        if row.is_additional_booking:
            label += " (Repeat)"
        if row.container_inspection:
            label += " (Inspection created)"
        events.append(
            {
                "name": row.name,
                "start": str(row.inspection_date),
                "end": str(row.inspection_date),
                "title": label,
                "all_day": 1,
                "convert_to_user_tz": 0,
                "docstatus": row.docstatus,
            }
        )
    return events
