// Copyright (c) 2025, elius mgani and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Revenue Summary"] = {
  filters: [
    {
      fieldname: "from_date",
      label: "From Date",
      fieldtype: "Date",
      reqd: 1,
    },
    {
      fieldname: "to_date",
      label: "To Date",
      fieldtype: "Date",
      reqd: 1,
    },
    // {

    // 	"fieldname": "currency",
    // 	"label": __("Currency"),
    // 	"fieldtype": "Select",
    // 	"options": erpnext.get_presentation_currency_list(),

    // },
    {
      fieldname: "m_bl_no",
      label: "M B/L No",
      fieldtype: "Data",
    },
    {
      fieldname: "currency",
      label: "Currency",
      fieldtype: "Link",
      options: "Currency",
    },
  ],
};
