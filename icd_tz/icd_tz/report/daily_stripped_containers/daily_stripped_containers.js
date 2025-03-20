// Copyright (c) 2025, elius mgani and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Daily Stripped Containers"] = {
    "filters": [
        {
            "fieldname": "from_date",
            "label": "From Date",
            "fieldtype": "Date",
            "reqd":1
        },
        {
            "fieldname": "to_date",
            "label": "To Date",
            "fieldtype": "Date"
        },
        {
            "fieldname": "m_bl_no",
            "label": "M B/L Number",
            "fieldtype": "Data"
        }
    ]
};