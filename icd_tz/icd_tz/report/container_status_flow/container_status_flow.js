// Copyright (c) 2026, ICD TZ and contributors
// For license information, please see license.txt

frappe.query_reports["Container Status Flow"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      reqd: 1,
      default: frappe.defaults.get_user_default("Company"),
    },
  ],
};
