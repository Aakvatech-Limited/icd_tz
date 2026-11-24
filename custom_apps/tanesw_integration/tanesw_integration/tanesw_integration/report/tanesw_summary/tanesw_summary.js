frappe.query_reports["TANeSW Summary"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "company", label: __("Company (targets)"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company") },
	],
	formatter(value, row, column, data, default_formatter) {
		// TANeSW and ERP text is shown as text, never as HTML (Frappe's Data formatter does not escape)
		const text = ["Data", "Small Text", "Text", "Long Text"].includes(column.fieldtype || "Data");
		value = default_formatter(text && typeof value === "string" ? frappe.utils.escape_html(value) : value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "total" && data.total > 0) {
			if (data.tone === "bad") return `<span style="color:var(--red-600,#dc2626);font-weight:700">${value}</span>`;
			if (data.tone === "warn") return `<span style="color:var(--orange-600,#d97706);font-weight:700">${value}</span>`;
			return `<b>${value}</b>`;
		}
		if (column.fieldname === "pct" && data.pct !== null && data.pct !== undefined) {
			const c = data.pct >= 100 ? "green" : data.pct >= 80 ? "orange" : "red";
			return `<span class="indicator-pill ${c}">${value}</span>`;
		}
		return value;
	},
};
