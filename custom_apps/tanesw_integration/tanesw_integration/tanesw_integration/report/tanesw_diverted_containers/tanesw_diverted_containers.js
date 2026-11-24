frappe.query_reports["TANeSW Diverted Containers"] = {
	filters: [
		{ fieldname: "from_date", label: __("Detected From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -30), reqd: 1 },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "mrn", label: __("MRN"), fieldtype: "Data" },
		{ fieldname: "manifest", label: __("Manifest"), fieldtype: "Link", options: "Manifest" },
		{ fieldname: "change_type", label: __("Change"), fieldtype: "Select", options: ["", "Removed", "Added"] },
		{
			fieldname: "outcome", label: __("Outcome"), fieldtype: "Select",
			options: ["", "Not traced yet", "Diverted to another ICD", "Moved to a port facility", "Moved elsewhere",
				"Simple Transfer (still ours)", "Back on our allocation", "Added to our allocation"],
		},
		{ fieldname: "new_place", label: __("Went To"), fieldtype: "Data" },
		{ fieldname: "container_no", label: __("Container"), fieldtype: "Data" },
	],
	formatter(value, row, column, data, default_formatter) {
		// TANeSW and ERP text is shown as text, never as HTML (Frappe's Data formatter does not escape)
		const text = ["Data", "Small Text", "Text", "Long Text"].includes(column.fieldtype || "Data");
		value = default_formatter(text && typeof value === "string" ? frappe.utils.escape_html(value) : value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "outcome") {
			const color = {
				"Diverted to another ICD": "red", "Moved to a port facility": "orange", "Moved elsewhere": "orange",
				"Back on our allocation": "green", "Added to our allocation": "green", "Not traced yet": "gray",
				"Simple Transfer (still ours)": "green",
			}[data.outcome] || "gray";
			return `<span class="indicator-pill ${color}">${value}</span>`;
		}
		if (column.fieldname === "manifest_action" && (data.manifest_action || "").startsWith("Kept: Movement"))
			return `<span style="color: var(--red-600)">${value}</span>`;
		return value;
	},
};
