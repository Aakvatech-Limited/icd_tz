// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gate Pass", {
	refresh(frm) {
        frm.trigger("set_filters");
        frm.trigger("add_gate_person_buttons");
	},
    onload: (frm) => {
        frm.trigger("set_filters");
    },
    set_filters: (frm) => {
        frm.set_query("clearing_agent", () => {
            return {
                filters: {
                    "disabled": 0,
                    "c_and_f_company": frm.doc.c_and_f_company
                }
            }
        });
    },
    action_for_missing_booking: (frm) => {
        if (frm.doc.action_for_missing_booking) {
            frm.set_value("missing_booking_allowed_by", frappe.session.user_fullname);
            frm.refresh_field("missing_booking_allowed_by");
        } else {
            frm.set_value("missing_booking_allowed_by", "");
            frm.refresh_field("missing_booking_allowed_by");
        }
    },



    add_gate_person_buttons: (frm) => {
        // Only show buttons for submitted gate passes that are not yet confirmed
        if (frm.doc.docstatus === 1 && frm.doc.workflow_state !== 'Gate Out Confirmed') {

            // Check if gate pass has expired
            let is_expired = false;
            if (frm.doc.expiry_date && frm.doc.expiry_time) {
                let expiry_datetime = new Date(frm.doc.expiry_date + ' ' + frm.doc.expiry_time);
                let current_datetime = new Date();
                is_expired = current_datetime > expiry_datetime;
            }

            if (is_expired) {
                // Show Cancel button for expired gate passes
                frm.add_custom_button(__('Cancel Expired Gate Pass'), function() {
                    frappe.confirm(
                        __('This Gate Pass has expired. Are you sure you want to cancel it?'),
                        function() {
                            frappe.call({
                                method: "frappe.client.cancel",
                                args: {
                                    doctype: "Gate Pass",
                                    name: frm.doc.name
                                },
                                callback: function(r) {
                                    if (!r.exc) {
                                        frappe.msgprint(__("Gate Pass cancelled successfully"));
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }, __('Gate Person Actions')).addClass('btn-danger');

                // Show expiry warning
                frm.dashboard.add_comment(__('Warning: This Gate Pass has expired!'), 'red', true);

            } else {
                // Show expiry info for valid gate passes
                if (frm.doc.expiry_date && frm.doc.expiry_time) {
                    let expiry_datetime = new Date(frm.doc.expiry_date + ' ' + frm.doc.expiry_time);
                    frm.dashboard.add_comment(__('Gate Pass expires on: ') + expiry_datetime.toLocaleString(), 'blue', true);
                }
            }
        }
    }
});
