frappe.ui.form.on("TANeSW Settings", {
	refresh(frm) {
		if (frappe.user.has_role("System Manager")) {
			frm.add_custom_button(__("Run ICD Link Now"), () =>
				frappe.call({ method: "tanesw_integration.icd_link.run_now", freeze: true })
					.then(r => frappe.show_alert({ message: r.message, indicator: "blue" }, 8)));
			frm.add_custom_button(__("Run Container Tracking Now"), () =>
				frappe.call({ method: "tanesw_integration.containers.run_now", freeze: true })
					.then(r => frappe.show_alert({ message: r.message, indicator: "blue" }, 8)));
			frm.add_custom_button(__("Run Allocation Check Now"), () =>
				frappe.call({ method: "tanesw_integration.allocations.run_now", freeze: true })
					.then(r => frappe.show_alert({ message: r.message, indicator: "blue" }, 8)));
		}
		frm.add_custom_button(__("Test Connection"), function () {
			frappe.call({
				method: "tanesw_integration.api.test_connection",
				freeze: true,
				freeze_message: __("Authenticating with TANeSW..."),
				callback(r) {
					if (r.message && r.message.status === "ok") {
						frappe.msgprint({
							title: __("Success"),
							indicator: "green",
							message: __("TANeSW handshake OK. Token length: {0}", [r.message.token_length])
						});
					}
				},
				error() {
					frappe.msgprint({
						title: __("Failed"),
						indicator: "red",
						message: __("Connection failed. Check settings and user account.")
					});
				}
			});
		});
	}
});
