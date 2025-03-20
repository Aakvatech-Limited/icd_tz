// Copyright (c) 2025, elius mgani and contributors
// For license information, please see license.txt

frappe.query_reports["Current Container Stock"] = {
  filters: [
    {
      fieldname: "status_filter",
      label: __("Status Filter"),
      fieldtype: "Select",
      options: ["", "In House", "Delivered"],
      default: "In House",
      reqd: 0,
    },
  ],
};
