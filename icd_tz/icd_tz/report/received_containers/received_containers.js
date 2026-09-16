// Copyright (c) 2025, elius mgani and contributors
// For license information, please see license.txt
/* eslint-disable */

// Copyright (c) 2024, ICD TZ and contributors
// For license information, please see license.txt

frappe.query_reports["Received Containers"] = {
  filters: [
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      default: frappe.datetime.get_today(),
    },
    {
      fieldname: "bl_no",
      label: __("M B/L No."),
      fieldtype: "Data",
    },
  ],
};
