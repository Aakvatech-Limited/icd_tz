// Display scheduled inspections from In Yard Container Booking.
// Calendar events are informational; scheduling changes belong in the booking.
frappe.views.calendar["In Yard Container Booking"] = {
    field_map: {
        id: "name",
        start: "start",
        end: "end",
        title: "title",
        allDay: "all_day",
        convertToUserTz: "convert_to_user_tz",
    },
    get_events_method:
        "icd_tz.icd_tz.doctype.in_yard_container_booking.in_yard_container_booking_calendar.get_events",
    options: {
        editable: false,
        selectable: false,
        droppable: false,
    },
};
