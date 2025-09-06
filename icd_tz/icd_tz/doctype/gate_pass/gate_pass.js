// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gate Pass", {
	refresh(frm) {
        frm.trigger("set_filters");
        frm.trigger("add_custom_buttons");
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

    add_custom_buttons: (frm) => {
        // Add Gate Out Confirm button for submitted documents that are not yet confirmed
        if (frm.doc.docstatus === 1 && frm.doc.workflow_state !== 'Gate Out Confirmed') {
            frm.add_custom_button(__('Gate Out Confirm'), function() {
                frappe.confirm(
                    __('Are you sure you want to confirm the gate out for this container?'),
                    function() {
                        frappe.call({
                            method: "gate_out_confirm",
                            doc: frm.doc,
                            callback: function(r) {
                                if (!r.exc) {
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            }, __('Workflow Actions')).addClass('btn-primary');
        }
    }
});
