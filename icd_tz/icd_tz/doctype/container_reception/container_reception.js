// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on('Container Reception', {
    setup: (frm) => {
        frm.trigger("get_countries_of_destination");
    },
	refresh: (frm) => {
		frm.trigger("set_queries");
	},
	onload: (frm) => {
        if (!frm.doc.company) {
            frm.set_value("company", frappe.defaults.get_user_default("Company"));
            console.log("Company: ", frm.doc.company);
        }

		frm.trigger("set_queries");
	},
    set_queries: (frm) => {
        frm.set_query("movement_order", () => {
            return {
                filters: {
                    docstatus: 1
                }
            };
        });
        frm.set_query("cleck", () => {
            return {
                filters: {
                    "status": "Active"
                }
            }
        });
        frm.set_query("security_officer", () => {
            return {
                filters: {
                    "disabled": 0
                }
            }
        });
    },
    container_no: (frm) => {
        if (frm.doc.manifest && frm.doc.container_no) {
            frappe.call({
                method: "icd_tz.icd_tz.doctype.container_reception.container_reception.get_container_details",
                args: {
                    manifest: frm.doc.manifest,
                    container_no: frm.doc.container_no
                },
                callback: (r) => {
                    if (r.message) {
                        let data = r.message;
                        
                        frm.set_value("size", data.container_size)
                        frm.set_value("volume", data.volume)
                        frm.set_value("volume", data.volume)
                        frm.set_value("weight", data.weight)
                        frm.set_value("weight_unit", data.weight_unit)
                        frm.set_value("seal_no_1", data.seal_no1)
                        frm.set_value("seal_no_2", data.seal_no2)
                        frm.set_value("seal_no_3", data.seal_no3)
                        frm.set_value("abbr_for_destination", data.abbr_for_destination)
                        frm.refresh_fields();
                    }
                }
            });
        }
    },
    get_countries_of_destination: (frm) => {
        frappe.call({
            method: "icd_tz.icd_tz.doctype.container_reception.container_reception.get_country_of_destination",
            args: {},
            callback: (r) => {
                console.log(r)

                if (r.message) {
                    frm.set_df_property("country_of_destination", "options", r.message);
                    frm.refresh_field("country_of_destination");
                }
            }
        });
    }
});
