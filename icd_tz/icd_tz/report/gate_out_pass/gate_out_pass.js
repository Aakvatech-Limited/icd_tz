// Copyright (c) 2025, elius mgani and contributors
// For license information, please see license.txt

frappe.query_reports["Gate Out Pass"] = {
  filters: [
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      reqd: 1,
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      reqd: 1,
    },
    {
      fieldname: "m_bl_no",
      label: __("M B/L No"),
      fieldtype: "Data",
      reqd: 0,
    },
    {
      fieldname: "h_bl_no",
      label: __("H B/L No"),
      fieldtype: "Data",
      reqd: 0,
    },
  ],
};
