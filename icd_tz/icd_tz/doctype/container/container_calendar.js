// Historical yard occupancy: arrival inclusive, gate-out exclusive.
// Calendar events are read-only; edit the underlying Container to change dates.
frappe.views.calendar["Container"] = {
    field_map: {
        start: "start",
        end: "end",
        id: "name",
        title: "title",
        allDay: "all_day",
        status: "status",
    },
    get_events_method: "icd_tz.icd_tz.doctype.container.container_calendar.get_events",
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
        },
        {
            fieldname: "status",
            label: __("Status"),
            fieldtype: "Select",
            options: ["", "In Yard", "At Booking", "At Inspection", "At Payments", "At Gatepass", "At Gate Confirmation", "Delivered"],
        },
    ],
};
