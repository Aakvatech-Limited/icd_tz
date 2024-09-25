// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("In Yard Container Booking", {
	refresh(frm) {
		frm.trigger("set_filters");
        frm.trigger("create_container_inspection");
	},
    onload: (frm) => {
        if (!frm.doc.company) {
            frm.set_value("company", frappe.defaults.get_user_default("Company"));
        }
		frm.trigger("set_filters");
        
        frm.trigger("create_container_inspection");
    },
	set_filters: (frm) => {
		frm.set_query("c_and_f_company", () => {
			return {
				filters: {
					"disabled": 0
				}
			};
		});
		frm.set_query("c_and_f_agent", () => {
			return {
				filters: {
					"disabled": 0,
					"c_and_f_company": frm.doc.c_and_f_company
				}
			};
		});
	},
	create_container_inspection: (frm) => {
		if (!frm.doc.container_inspection & frm.doc.docstatus == 1) {
			frm.add_custom_button(__('Create Container Inspection'), () => {
				frappe.new_doc('Container Inspection', {
					"in_yard_container_booking": frm.doc.name,
					"consignee": frm.doc.consignee,
					"clearing_agent": frm.doc.c_and_f_agent,
					"c_and_f_company": frm.doc.c_and_f_company,
					"container_no": frm.doc.container_no,
                    "inspection_date": frm.doc.booking_date + " " + frm.doc.booking_time,
				}, doc => {});
			}).addClass('btn-primary');
		}
	}
});
