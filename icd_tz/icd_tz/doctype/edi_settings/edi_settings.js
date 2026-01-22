// Copyright (c) 2025, Administrator and contributors
// For license information, please see license.txt

frappe.ui.form.on("EDI Settings", {
	test_connection(frm) {
		// This is triggered when the button field is clicked
		try_edi_connection(frm);
	}
});

function try_edi_connection(frm) {
	// Validate required fields before testing
	if (!frm.doc.url) {
		frappe.msgprint(__("Please enter a URL"));
		return;
	}
	if (!frm.doc.user) {
		frappe.msgprint(__("Please enter a User"));
		return;
	}
	if (!frm.doc.port) {
		frappe.msgprint(__("Please enter a Port"));
		return;
	}
	
	// Check authentication requirements
	if (frm.doc.authentication_method === "Password" && !frm.doc.password) {
		frappe.msgprint(__("Please enter a Password"));
		return;
	}
	if (frm.doc.authentication_method === "Key" && !frm.doc.authentication_key) {
		frappe.msgprint(__("Please enter an Authentication Key"));
		return;
	}
	
	// Save the document first if it has unsaved changes
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the document before testing the connection"));
		return;
	}
	
	frappe.show_alert({
		message: __("Testing connection..."),
		indicator: "blue"
	});
	
	frappe.call({
		method: "try_edi_connection",
		doc: frm.doc,
		freeze: true,
		freeze_message: __("Testing EDI connection..."),
		callback: function(r) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					title: __("Success"),
					message: r.message.message,
					indicator: "green"
				});
			}
		},
		error: function(r) {
			// Error is already handled by frappe.throw in Python
		}
	});
}
