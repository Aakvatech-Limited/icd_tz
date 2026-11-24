frappe.ui.form.on("TANeSW User Account", {
	refresh(frm) {
		if (!frm.is_new()) {
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
								message: __("TANeSW 2-step handshake completed. Token length: {0}", [r.message.token_length])
							});
							frm.reload_doc();
						}
					},
					error() {
						frappe.msgprint({
							title: __("Connection Failed"),
							indicator: "red",
							message: __("Check your TANeSW credentials and try again.")
						});
						frm.reload_doc();
					}
				});
			});
		}
	}
});
