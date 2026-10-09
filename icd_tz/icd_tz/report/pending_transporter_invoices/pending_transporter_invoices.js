// Copyright (c) 2026, elius mgani and contributors
// For license information, please see license.txt

frappe.query_reports["Pending Transporter Invoices"] = {
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
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      reqd: 1,
      default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      reqd: 1,
      default: frappe.datetime.get_today(),
    },
    {
      fieldname: "transporter",
      label: __("Transporter"),
      fieldtype: "Link",
      options: "Supplier",
      get_query: () => ({ filters: { is_transporter: 1 } }),
    },
    {
      fieldname: "manifest",
      label: __("Manifest"),
      fieldtype: "Link",
      options: "Manifest",
    },
  ],
};
