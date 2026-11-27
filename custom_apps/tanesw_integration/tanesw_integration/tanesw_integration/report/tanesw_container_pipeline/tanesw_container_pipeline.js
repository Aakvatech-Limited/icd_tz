frappe.query_reports["TANeSW Container Pipeline"] = {
	filters: [
		{ fieldname: "from_date", label: __("Vessel Arrival From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -30), reqd: 1 },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), 14), reqd: 1 },
		{ fieldname: "mrn", label: __("MRN"), fieldtype: "Data" },
		{
			fieldname: "stage", label: __("Show Boxes In Stage"), fieldtype: "Select",
			options: ["", "Not landed yet", "Landed, to declare", "Declared, waiting for pick-up", "Picked up, on the road",
				"Received", "Left our allocation"],
		},
		{ fieldname: "open_only", label: __("Open Vessels Only"), fieldtype: "Check", default: 1 },
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
		if (data.indent === 0 && column.fieldname === "label") return `<b>${value}</b>`;
		if (column.fieldname === "stage" && data.stage) {
			const color = {
				"Landed, to declare": "orange", "Declared, waiting for pick-up": "blue", "Picked up, on the road": "purple",
				"Received": "green", "Left our allocation": "gray", "Not landed yet": "gray",
			}[data.stage] || "gray";
			return `<span class="indicator-pill ${color}">${value}</span>`;
		}
		if (column.fieldname === "check" && data.check) return `<span style="color: var(--red-600)">${value}</span>`;
		if (column.fieldname === "to_declare" && data.indent === 0 && data.to_declare) return `<b style="color: var(--orange-600)">${value}</b>`;
		return value;
	},
};
