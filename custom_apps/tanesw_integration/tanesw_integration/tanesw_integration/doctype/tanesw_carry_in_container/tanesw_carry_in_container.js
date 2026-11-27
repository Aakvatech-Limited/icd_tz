frappe.ui.form.on("TANeSW Carry In Container", {
	refresh(frm) {
		const open = (label, doctype, name) => name && frm.add_custom_button(__(label), () => frappe.set_route("Form", doctype, name), __("Open"));
		open("Manifest", "Manifest", frm.doc.manifest);
		open("Movement Order", "Container Movement Order", frm.doc.movement_order);
		open("Container Reception", "Container Reception", frm.doc.container_reception);
		const color = { "Reception Submitted": "green", "Reception Drafted": "orange", "Order Linked": "blue", "Waiting for Order": "orange", "Exception": "red" }[frm.doc.link_status];
		if (frm.doc.link_message) frm.dashboard.set_headline_alert(frappe.utils.escape_html(frm.doc.link_message), color);
		if (frm.doc.transport_check === "Differs") frm.dashboard.add_comment(frappe.utils.escape_html(frm.doc.transport_note), "orange", true);
	},
});
