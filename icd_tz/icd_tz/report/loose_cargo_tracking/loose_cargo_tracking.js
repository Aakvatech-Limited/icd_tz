// Copyright (c) 2025, elius mgani and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Loose Cargo Tracking"] = {
  filters: [
    {
      fieldname: "report_type",
      label: "Report Type",
      fieldtype: "Select",
      options: [
        "Current Loose Stock",
        "Exited Loose Cargo",
        "Received Loose Cargo",
      ],
      default: "Current Loose Stock",
      reqd: 1,
    },
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
    {
      fieldname: "bl_no",
      label: "M B/L Number",
      fieldtype: "Data",
    },
  ],

  onload: function (report) {
    // Optional: Add any additional setup or event listeners
    report.page.add_inner_button(__("Refresh"), function () {
      report.refresh();
    });
  },
};
