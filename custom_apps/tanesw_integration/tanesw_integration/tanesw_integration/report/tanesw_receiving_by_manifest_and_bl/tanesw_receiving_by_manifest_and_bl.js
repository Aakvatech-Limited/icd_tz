frappe.query_reports["TANeSW Receiving by Manifest and BL"] = {
	filters: [
		{ fieldname: "from_date", label: __("Vessel Arrival From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -30), reqd: 1 },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "mrn", label: __("MRN"), fieldtype: "Data" },
		{ fieldname: "bl_no", label: __("B/L No"), fieldtype: "Data" },
		{ fieldname: "status", label: __("B/L Status"), fieldtype: "Select", options: ["", "Complete", "Partial", "Not Started"] },
	],
	tree: true,
	name_field: "id",
	parent_field: "parent_id",
	initial_depth: 0,
	formatter(value, row, column, data, default_formatter) {
		// TANeSW and ERP text is shown as text, never as HTML (Frappe's Data formatter does not escape)
		const text = ["Data", "Small Text", "Text", "Long Text"].includes(column.fieldtype || "Data");
		value = default_formatter(text && typeof value === "string" ? frappe.utils.escape_html(value) : value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "bl_status" && data.indent === 1) {
			const color = { Complete: "green", Partial: "orange", "Not Started": "blue" }[data.bl_status] || "gray";
			return `<span class="indicator-pill ${color}">${value}</span>`;
		}
		if (column.fieldname === "check" && data.check) return `<span style="color:var(--red-600)">${value}</span>`;
		if (data.indent === 0 && column.fieldname === "label") return `<b>${value}</b>`;
		return value;
	},
};
