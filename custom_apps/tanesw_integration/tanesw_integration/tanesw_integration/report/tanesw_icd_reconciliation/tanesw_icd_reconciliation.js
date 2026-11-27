frappe.query_reports["TANeSW ICD Reconciliation"] = {
	filters: [
		{ fieldname: "from_date", label: __("Arrival From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -30), reqd: 1 },
		{ fieldname: "to_date", label: __("Arrival To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "vessel_name", label: __("Vessel"), fieldtype: "Data" },
		{ fieldname: "mrn", label: __("MRN"), fieldtype: "Data" },
	],
	formatter(value, row, column, data, default_formatter) {
		// TANeSW and ERP text is shown as text, never as HTML (Frappe's Data formatter does not escape)
		const text = ["Data", "Small Text", "Text", "Long Text"].includes(column.fieldtype || "Data");
		value = default_formatter(text && typeof value === "string" ? frappe.utils.escape_html(value) : value, row, column, data);
		if (!data) return value;
		const strong = (color) => `<span style="color:var(--${color}-600);font-weight:700">${value}</span>`;
		if (["allocation_gap", "reception_gap"].includes(column.fieldname) && data[column.fieldname]) return strong("red");
		if (column.fieldname === "diverted" && data.diverted > 0) return strong("red");
		if (column.fieldname === "at_port" && data.at_port > 0) return strong("orange");
		if (column.fieldname === "balances" && data.balances && data.balances.startsWith("Off")) return strong("red");
		if (column.fieldname === "check" && data.check && data.check !== __("OK")) return strong("red");
		if (column.fieldname === "check" && data.check === __("OK")) return strong("green");
		return value;
	},
	onload(report) {
		report.page.add_inner_button(__("Container Allocation"), () => frappe.set_route("query-report", "TANeSW Container Allocation"));
		report.page.add_inner_button(__("Carry-In Links"), () => frappe.set_route("List", "TANeSW Carry In Container"));
	},
};
