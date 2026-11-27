frappe.query_reports["TANeSW Container Dwell"] = {
	filters: [
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nAt Terminal\nNot Discharged\nIn Transit\nReceived at ICD\nDiverted", default: "At Terminal" },
		{ fieldname: "cargo_type", label: __("Local / Transit"), fieldtype: "Select", options: "\nLocal\nTransit\nUnknown" },
		{
			fieldname: "storage_status", label: __("Port Storage"), fieldtype: "Select",
			options: "\nWithin free days\nFree days ending\nOver free days\nLeft within free days\nLeft after free days\nLeft our allocation",
		},
		{ fieldname: "only_over_free", label: __("Only Boxes Over Free Days"), fieldtype: "Check" },
		{ fieldname: "mrn", label: __("MRN"), fieldtype: "Link", options: "TANeSW Vessel Allocation" },
		{ fieldname: "vessel_name", label: __("Vessel"), fieldtype: "Data" },
		{ fieldname: "container_no", label: __("Container No"), fieldtype: "Data" },
		{ fieldname: "bl_no", label: __("B/L No"), fieldtype: "Data" },
		{ fieldname: "from_date", label: __("Vessel Arrival From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Vessel Arrival To"), fieldtype: "Date" },
		{ fieldname: "min_dwell", label: __("Min Dwell (days)"), fieldtype: "Float" },
	],
	formatter(value, row, column, data, default_formatter) {
		// TANeSW and ERP text is shown as text, never as HTML (Frappe's Data formatter does not escape)
		const text = ["Data", "Small Text", "Text", "Long Text"].includes(column.fieldtype || "Data");
		value = default_formatter(text && typeof value === "string" ? frappe.utils.escape_html(value) : value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "storage_status" && data.storage_status) {
			const c = {
				"Within free days": "green", "Free days ending": "orange", "Over free days": "red",
				"Left within free days": "gray", "Left after free days": "red", "Left our allocation": "gray",
			}[data.storage_status] || "gray";
			return `<span class="indicator-pill ${c}">${value}</span>`;
		}
		if (["days_over", "single_days", "double_days"].includes(column.fieldname) && data[column.fieldname] > 0)
			return `<span style="color:var(--red-600,#dc2626);font-weight:700">${value}</span>`;
		if (column.fieldname === "free_days_left" && data.free_days_left !== null && data.free_days_left !== undefined
				&& data.free_days_left <= 2)
			return `<span style="color:var(--orange-600,#d97706);font-weight:700">${value}</span>`;
		if (column.fieldname === "status") {
			const c = { "At Terminal": "orange", "In Transit": "blue", "Received at ICD": "green", "Not Discharged": "gray", "Diverted": "red" }[data.status] || "gray";
			return `<span class="indicator-pill ${c}">${value}</span>`;
		}
		if (column.fieldname === "container_no" && data.name)
			return `<a href="/app/tanesw-container/${encodeURIComponent(data.name)}">${value}</a>`;
		return value;
	},
};
