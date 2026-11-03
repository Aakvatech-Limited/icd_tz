frappe.query_reports["ICD Average Container Occupancy"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
        },
        {
            fieldname: "time_span",
            label: __("Time Span"),
            fieldtype: "Select",
            options: ["Today", "Yesterday", "This Week", "Last Week", "This Month", "Last Month", "This Year", "Period"],
            default: "This Month",
            reqd: 1,
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            depends_on: "eval:doc.time_span == 'Period'",
            mandatory_depends_on: "eval:doc.time_span == 'Period'",
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            depends_on: "eval:doc.time_span == 'Period'",
            mandatory_depends_on: "eval:doc.time_span == 'Period'",
        },
        {
            fieldname: "group_by",
            label: __("Group By"),
            fieldtype: "Select",
            options: ["Daily", "Weekly", "Monthly", "Overall"],
            default: "Monthly",
            reqd: 1,
        },
        {
            fieldname: "container_type",
            label: __("Container Type"),
            fieldtype: "Data",
        },
    ],
};
