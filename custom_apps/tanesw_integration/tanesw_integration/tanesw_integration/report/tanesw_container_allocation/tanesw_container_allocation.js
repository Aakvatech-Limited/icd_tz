frappe.query_reports["TANeSW Container Allocation"] = {
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
		if (column.fieldname === "at_port" && data.at_port_source !== "tracking" && data.at_port != null) {
			const why = data.at_port_source === "partial"
				? __("Container tracking has read {0} of {1} landed containers so far: showing Target - Declared until it is complete.", [data.tracked || 0, data.landed])
				: __("Container tracking not synced yet: Target - Declared. Declared containers may still be at the terminal.");
			value = `<span title="${why}">${value}*</span>`;
		}
		if (column.fieldname === "declared_waiting" && data.declared_waiting > 0) return `<span style="color:var(--red-600,#dc2626);font-weight:700" title="${__("Declared to our ICD but not yet out of the terminal")}">${value}</span>`;
		if (column.fieldname === "at_port" && data.at_port > 0) return `<span style="color:var(--orange-600,#d97706);font-weight:700">${value}</span>`;
		if (column.fieldname === "declared" && data.total && data.declared >= data.total) return `<span style="color:var(--green-600,#16a34a);font-weight:700">${value}</span>`;
		if (column.fieldname === "vessel_name" && data.source === "Manifest")
			return `${value} <span class="text-muted" title="${__("No longer on TANeSW's Expected ICD Transfer list (all transferred, or transfer closed). Allocated is from Manifest Information; TANeSW no longer gives Landed / Declared for it.")}">(finished)</span>`;
		if (column.fieldname === "vessel_name" && data.source === "Watcher")
			return `${value} <span class="text-muted" title="${__("Not in TANeSW's Expected ICD Transfer list yet (not arrived, or TANeSW did not answer). Allocated count is from our B/L scan.")}">(not arrived)</span>`;
		if (column.fieldname === "mrn" && value)
			return `<a href="/app/tanesw-cargo/cgme0101026q/${encodeURIComponent(data.mrn)}">${value}</a>`;
		return value;
	},
	onload(report) {
		report.page.add_inner_button(__("Container Dwell Report"), () => {
			const f = report.get_values() || {};
			frappe.set_route("query-report", "TANeSW Container Dwell", f.mrn ? { mrn: f.mrn } : {});
		});
	},
};
