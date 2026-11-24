frappe.query_reports["TANeSW Reception Date Check"] = {
	filters: [
		{ fieldname: "from_date", label: __("Posted From"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{
			fieldname: "status", label: __("Status"), fieldtype: "Select",
			options: ["", "Matches", "Posted Late", "Posted Early", "Time Differs", "No TANeSW Carry-In"],
		},
		{ fieldname: "only_storage_lost", label: __("Only Storage Starting Late"), fieldtype: "Check" },
		{ fieldname: "manifest", label: __("Manifest"), fieldtype: "Link", options: "Manifest" },
		{ fieldname: "mrn", label: __("MRN"), fieldtype: "Data" },
		{ fieldname: "container_no", label: __("Container"), fieldtype: "Data" },
		{ fieldname: "clerk", label: __("Clerk"), fieldtype: "Link", options: "Employee" },
	],
	formatter(value, row, column, data, default_formatter) {
		// TANeSW and ERP text is shown as text, never as HTML (Frappe's Data formatter does not escape)
		const text = ["Data", "Small Text", "Text", "Long Text"].includes(column.fieldtype || "Data");
		value = default_formatter(text && typeof value === "string" ? frappe.utils.escape_html(value) : value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "status") {
			const color = {
				"Matches": "green", "Posted Late": "red", "Posted Early": "orange", "Time Differs": "orange",
				"No TANeSW Carry-In": "gray",
			}[data.status] || "gray";
			return `<span class="indicator-pill ${color}">${value}</span>`;
		}
		if (column.fieldname === "storage_days_lost" && data.storage_days_lost > 0)
			return `<span style="color: var(--red-600); font-weight: 600">${value}</span>`;
		return value;
	},
};
