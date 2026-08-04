// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("Container Movement Order", {
	refresh: (frm) => {
        frm.trigger("set_queries");
        frm.trigger("create_container_reception");
	},
    onload: (frm) => {
        if (!frm.doc.company) {
            frm.set_value("company", frappe.defaults.get_user_default("Company"));
        }

        frm.trigger("set_queries");
        frm.trigger("create_container_reception");
    },
    set_queries: (frm) => {
        frm.set_query("manifest", () => {
            return {
                filters: {
                    docstatus: 1
                }
            };
        });
        frm.set_query("transporter", () => {
            return {
                filters: {
                    "disabled": 0,
                    "is_transporter": 1
                }
            }
        });
        frm.set_query("driver", () => {
            return {
                filters: {
                    "status": "Active",
                    "vehicle_owner": frm.doc.transporter
                }
            }
        });
        frm.set_query("truck", () => {
            return {
                filters: {
                    "disabled": 0,
                    "vehicle_owner": frm.doc.transporter,
                    "is_truck": 1
                }
            }
        });
        frm.set_query("trailer", () => {
            return {
                filters: {
                    "disabled": 0,
                    "vehicle_owner": frm.doc.transporter,
                    "is_trailer": 1
                }
            }
        });
    },
    manifest: (frm) => {
        frm.trigger("get_containers");
    },
    create_container_reception: (frm) => {
        if (frm.doc.docstatus == 1 && frm.doc.status != "Received") {
            frm.add_custom_button(__('Create Container Reception'), () => {
                frappe.new_doc('Container Reception', {
                    "movement_order": frm.doc.name,
                    "manifest": frm.doc.manifest,
                    "ship": frm.doc.ship,
                    "ship_dc_date": frm.doc.ship_dc_date,
                    "voyage_no": frm.doc.voyage_no,
                    "port": frm.doc.port,
                    "container_no": frm.doc.container_no,
                    "size": frm.doc.size,
                    "truck": frm.doc.truck,
                    "trailer": frm.doc.trailer,
                    "driver": frm.doc.driver,
                    "driver_license": frm.doc.driver_license,
                    "transporter": frm.doc.transporter,
                    "cargo_type": frm.doc.cargo_type,
                    "m_bl_no": frm.doc.m_bl_no,
                    "container_count": frm.doc.container_count,
                    "freight_indicator": frm.doc.freight_indicator,
                }, doc => {});
            }).addClass('btn-primary');
        }
    },
    get_containers: (frm) => {
        if (frm.doc.manifest) {
            frappe.call({
                method: "icd_tz.icd_tz.doctype.container_movement_order.container_movement_order.get_manifest_details",
                args: {
                    manifest: frm.doc.manifest
                },
                freeze: true,
                freeze_message: __("Please wait..."),
                callback: (r) => {
                    if (r.message) {
                        let data = r.message;
                        frm.set_value("company", data[0].company);
                        frm.set_value("ship", data[0].vessel_name);
                        frm.set_value("voyage_no", data[0].voyage_no);

                        frm.refresh_fields();

                        show_dialog(frm, data);
                    }
                }
            });
        }
    },
    select_container: (frm) => {
        frm.trigger("get_containers");
    },
});


var show_dialog = (frm, data) => {
    let d = new frappe.ui.Dialog({
        title: __("Select Container"),
        soze: "large",
        fields: [
            {
                fieldtype: "Data",
                fieldname: "m_bl_no",
                label: __("M BL No"),
                placeholder: __("Enter M BL No to filter")
            },
            {
                fieldtype: "Column Break",
                fieldname: "column_break"
            },
            {
                fieldtype: "Button",
                fieldname: "apply_filter",
                label: __("Apply Filter")
            },
            {
                fieldtype: "Section Break",
                fieldname: "section_break"
            },
            {
                fieldtype: "HTML",
                fieldname: "container_table"
            }
        ]
    });

    let wrapper = d.fields_dict.container_table.$wrapper;

    if (data.length > 0) {
        let data_html = show_details(data);
        wrapper.html(data_html);
        attachCheckboxListener(wrapper);
    }

    d.fields_dict.apply_filter.$input.click(() => {
        get_containers(frm.doc.manifest, d.get_value("m_bl_no"), wrapper);
    });

    d.set_primary_action(__("Select"), () => {
        let container = {};

        wrapper.find('tr:has(input:checked)').each(function () {
            container = {
                container_no: $(this).find("#container_no").attr("data-container_no"),
                m_bl_no: $(this).find("#m_bl_no").attr("data-m_bl_no"),
                container_size: $(this).find("#container_size").attr("data-container_size"),
                freight_indicator: $(this).find("#freight_indicator").attr("data-freight_indicator"),
                cargo_type: $(this).find("#cargo_type").attr("data-cargo_type"),
            };
        });

        if (container) {
            frm.set_value("container_no", container.container_no);
            frm.set_value("m_bl_no", container.m_bl_no);
            frm.set_value("size", container.container_size);
            frm.set_value("freight_indicator", container.freight_indicator);
            frm.set_value("cargo_type", container.cargo_type);

            frm.refresh_fields();
            d.hide();
        } else {
            frappe.msgprint({
                title: __('Message'),
                indicator: 'red',
                message: __(
                    '<h4 class="text-center" style="background-color: #D3D3D3; font-weight: bold;">\
                    No any Container selected<h4>'
                )
            });
        }
    });

    d.$wrapper.find('.modal-content').css({
        "width": "650px",
        "max-height": "1000px",
        "overflow": "auto",
    });

    d.show();

    function show_details(data) {
        let html = `
            <style>
                .table-container {
                    height: 300px;
                    overflow-y: auto;
                    margin-top: 10px;
                }
                .table-container thead th {
                    position: sticky;
                    top: 0;
                    background-color: white;
                    z-index: 1;
                }
                .table-container table {
                    width: 100%;
                }
                .container-checkbox {
                    transform: scale(1.2);
                    margin: 5px;
                }
            </style>
            <div class="table-container">
                <table class="table table-hover">
                    <colgroup>
                        <col width="5%">
                        <col width="25%">
                        <col width="25%">
                        <col width="10%">
                        <col width="15%">
                        <col width="20%">
                    </colgroup>
                    <thead>
                        <tr>
                            <th style="background-color: #D3D3D3;"></th>
                            <th style="background-color: #D3D3D3;">Container NO</th>
                            <th style="background-color: #D3D3D3;">M BL No</th>
                            <th style="background-color: #D3D3D3;">Size</th>
                            <th style="background-color: #D3D3D3;">Freight Indicator</th>
                            <th style="background-color: #D3D3D3;">Cargo Type</th>
                        </tr>
                    </thead>
                    <tbody>`;

        data.forEach(row => {
            let cargo_type = ''
            if (row.cargo_type == 'IM') {
                cargo_type = 'Local'
            } else if (row.cargo_type == 'TR') {
                cargo_type = 'Transit'
            }
            html += `<tr>
                    <td><input type="checkbox" class="container-checkbox"/></td>
                    <td id="container_no" data-container_no="${row.container_no}">${row.container_no}</td>
                    <td id="m_bl_no" data-m_bl_no="${row.m_bl_no}">${row.m_bl_no}</td>
                    <td id="container_size" data-container_size="${row.container_size}">${row.container_size}</td>
                    <td id="freight_indicator" data-freight_indicator="${row.freight_indicator}">${row.freight_indicator}</td>
                    <td id="cargo_type" data-cargo_type="${cargo_type}">${cargo_type}</td>
                </tr>`;
        });

        html += `</tbody></table></div>`;
        return html;
    }

    function get_containers(manifest, m_bl_no, wrapper) {
        frappe.call({
            method: "icd_tz.icd_tz.doctype.container_movement_order.container_movement_order.get_manifest_details",
            args: {
                manifest: manifest,
                m_bl_no: m_bl_no
            },
            freeze: true,
            freeze_message: __("Filtering containers..."),
            callback: (r) => {
                let records = r.message;
                if (records.length > 0) {
                    let html = show_details(records);
                    wrapper.html(html);
                    attachCheckboxListener(wrapper);
                } else {
                    wrapper.html("");
                    wrapper.append(`<div class="multiselect-empty-state"
                        style="border: 1px solid #d1d8dd; border-radius: 3px; height: 200px; overflow: auto;">
                        <span class="text-center" style="margin-top: -40px;">
                            <i class="fa fa-2x fa-heartbeat text-extra-muted"></i>
                            <p class="text-extra-muted text-center" style="font-size: 16px; font-weight: bold;">
                            No Container(s) found</p>
                        </span>
                    </div>`);
                }
            }
        });
    }

    function attachCheckboxListener(wrapper) {
        wrapper.find('.container-checkbox').on('click', function () {
            wrapper.find('.container-checkbox').not(this).prop('checked', false);
        });
    }
};
