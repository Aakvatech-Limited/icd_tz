// Copyright (c) 2025, elius mgani and contributors
// For license information, please see license.txt

frappe.query_reports["Current Container Stock"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      reqd: 1,
      default: frappe.defaults.get_user_default("Company"),
    },
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
