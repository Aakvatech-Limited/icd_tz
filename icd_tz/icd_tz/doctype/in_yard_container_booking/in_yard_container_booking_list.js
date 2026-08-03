frappe.listview_settings['In Yard Container Booking'] = {
    add_fields: ['container_no', 'doctype'],
    hide_name_column: true,

    onload: (listview) => {
        $('button[data-label="Add In Yard Container Booking"]').hide();

        listview.page.add_inner_button(__("Create Bulk Container"), () => {
            show_dialog(listview);
        }).removeClass("btn-default").addClass("btn-info btn-sm");

        listview.page.add_inner_button(__("View Booking Report"), () => {
            frappe.set_route("query-report", "Container Booking");
        }).removeClass("btn-default").addClass("btn-secondary btn-sm");
    },
    button: {
        show: function(doc) {
            return doc.docstatus === 0;
        },
        get_label: function() {
          return __("Submit");
        },
        get_description: function(doc) {
          return __("Submit {0}", [
            `${__(doc.name)}: ${doc.container_no}`
          ]);
        },
        action: function(doc) {
            frappe.call({
                method: 'icd_tz.icd_tz.api.utils.submit_doc',
                args: {
                    doc_type: 'In Yard Container Booking',
                    doc_name: doc.name
                },
                freeze: true,
                freeze_message: __('<i class="fa fa-spinner fa-spin fa-4x"></i>'),
                callback: function(response) {
                    if (response.message) {
                        frappe.show_alert(__("Booking: {0} submitted successfully.", [doc.name]), 5);
                    } else {
                        frappe.show_alert(__("Failed to submit Booking {0}.", [doc.name]), 5);
                    }
                }
            });
        },
    },
}

var show_dialog = (listview) => {
    let d = new frappe.ui.Dialog({
        title: "Bulk Container Booking",
        fields: [
            {
                label: 'M BL No',
                fieldname: 'm_bl_no',
                fieldtype: 'Data',
                reqd: 0
            },
            {
                label: 'H BL No',
                fieldname: 'h_bl_no',
                fieldtype: 'Data',
                reqd: 0
            },
            {
                fieldname: 'cf_cb',
                fieldtype: 'Column Break'
            },
            {
                label: 'C & F Company',
                fieldname: 'c_and_f_company',
                fieldtype: 'Link',
                options: 'Clearing and Forwarding Company',
                reqd: 1,
                onchange: function() {
                    d.set_value('clearing_agent', '');

                    if (d.get_value('c_and_f_company')) {
                        d.set_df_property('clearing_agent', 'hidden', 0);
                    } else {
                        d.set_df_property('clearing_agent', 'hidden', 1);
                    }
                },
                get_query: function() {
                    return {
                        filters: {
                            "disabled": 0
                        }
                    };
                }
            },
            {
                label: 'Clearing Agent',
                fieldname: 'clearing_agent',
                fieldtype: 'Link',
                options: 'Clearing Agent',
                reqd: 1,
                hidden: 1,
                get_query: function() {
                    return {
                        filters: {
                            "disabled": 0,
                            'c_and_f_company': d.get_value('c_and_f_company')
                        }
                    };
                }
            },
            {
                fieldname: 'insp_cb',
                fieldtype: 'Column Break'
            },
            {
                label: 'Inspection Date',
                fieldname: 'inspection_date',
                fieldtype: 'Date',
                reqd: 1
            },
            {
                label: 'Inspection Location',
                fieldname: 'inspection_location',
                fieldtype: 'Link',
                options: 'Container Location',
                reqd: 1
            }
        ],
        size: "large",
        primary_action_label: 'Create Bookings',
        primary_action(values) {
            if (values) {
                if (!values.m_bl_no && !values.h_bl_no) {
                    frappe.msgprint({
                        title: __("Validation Error"),
                        indicator: 'red',
                        message: __("Please enter either M BL No or H BL No")
                    });
                    return;
                }

                if (values.m_bl_no && values.h_bl_no) {
                    frappe.msgprint({
                        title: __("Validation Error"),
                        indicator: 'red',
                        message: __("Invalid input: You must enter EITHER <b>M BL No</b> or <b>H BL No</b>, but not both. Please clear one of these fields to proceed.")
                    });
                    return;
                }

                frappe.call({
                    method: 'icd_tz.icd_tz.doctype.in_yard_container_booking.in_yard_container_booking.create_bulk_bookings',
                    args: {
                        data: values
                    },
                    freeze: true,
                    freeze_message: __('<i class="fa fa-spinner fa-spin fa-4x"></i>'),
                    callback: (r) => {
                        if (r.message) {
                            d.hide()
                            frappe.show_alert({
                                message: __("{0} Bookings Created successfully", [r.message]),
                                indicator: 'green'
                            }, 10);
                        }
                        listview.refresh();
                    }
                });
            }
        },

    });

    d.fields_dict.m_bl_no.df.onchange = () => {
        if (d.get_value('m_bl_no') && d.get_value('h_bl_no')) {
            frappe.msgprint({
                title: __("Validation Error"),
                indicator: 'red',
                message: __("Invalid input: You must enter EITHER <b>M BL No</b> or <b>H BL No</b>, but not both. Please clear one of these fields to proceed.")
            });
        }
    };

    d.fields_dict.h_bl_no.df.onchange = () => {
        if (d.get_value('h_bl_no') && d.get_value('m_bl_no')) {
            frappe.msgprint({
                title: __("Validation Error "),
                indicator: 'red',
                message: __("Invalid input: You must enter EITHER <b>M BL No</b> or <b>H BL No</b>, but not both. Please clear one of these fields to proceed.")
            });
        }
    };

    d.show();
}
