// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("Container Inspection", {
  refresh: (frm) => {
    frm.trigger("set_filters");
    frm.trigger("create_service_order");
    frm.trigger("create_additional_booking");
  },
  onload: (frm) => {
    frm.trigger("set_filters");
    frm.trigger("create_service_order");
    frm.trigger("create_additional_booking");
  },
  set_filters: (frm) => {
    frm.set_query("service", "services", () => {
      return {
        filters: {
          item_group: "ICD Services",
        },
      };
    });
    frm.set_query("driver_name", () => {
      return {
        filters: {
          status: "Active",
        },
      };
    });
    frm.set_query("in_yard_container_booking", () => {
      return {
        filters: {
          docstatus: 1,
        },
      };
    });
  },
  in_yard_container_booking: (frm) => {
    frm.trigger("get_container_custom_verification");
  },
  get_container_custom_verification: (frm) => {
    if (frm.doc.in_yard_container_booking) {
      frappe.call({
        method: "get_custom_verification_services",
        doc: frm.doc,
        args: {
          // self: frm.doc,
          caller: "Front End",
        },
        callback: (r) => {
          if (r.message) {
            frm.add_child("services", {
              service: r.message,
            });
            frm.refresh_field("services");
          }
        },
      });
    }
  },
  create_additional_booking: (frm) => {
    if (frm.doc.docstatus != 1) {
      return;
    }

    frm.add_custom_button(__("Create Additional Booking"), () => {
      const bl_no = frm.doc.h_bl_no
        ? __("H BL No: <b>{0}</b>", [frm.doc.h_bl_no])
        : __("M BL No: <b>{0}</b>", [frm.doc.m_bl_no]);

      frappe.prompt(
        [
          {
            label: __("Expected Inspection Date"),
            fieldname: "inspection_date",
            fieldtype: "Date",
            reqd: 1,
          },
          {
            fieldtype: "Column Break",
          },
          {
            label: __("Expected Inspection Location"),
            fieldname: "inspection_location",
            fieldtype: "Link",
            options: "Container Location",
            reqd: 1,
          },
          {
            fieldtype: "Section Break",
          },
          {
            fieldname: "confirmation",
            fieldtype: "HTML",
            options: __(
              "Container <b>{0}</b>, {1},   already has a Booking.<br><br> <p style='color: red'><i>Are you sure, you want to create an additional Booking for this container..??</i></p>",
              [frm.doc.container_no, bl_no]
            ),
          },
        ],
        (values) => {
          frappe.call({
            method:
              "icd_tz.icd_tz.doctype.in_yard_container_booking.in_yard_container_booking.create_additional_booking",
            args: {
              container_inspection: frm.doc.name,
              inspection_date: values.inspection_date,
              inspection_location: values.inspection_location,
            },
            freeze: true,
            freeze_message: __('<i class="fa fa-spinner fa-spin fa-4x"></i>'),
            callback: (r) => {
              if (r.message) {
                frappe.show_alert(
                  {
                    message: __("Additional Booking {0} created successfully", [
                      r.message,
                    ]),
                    indicator: "green",
                  },
                  10
                );
                frappe.set_route(
                  "Form",
                  "In Yard Container Booking",
                  r.message
                );
              }
            },
          });
        },
        __("Create Additional Booking"),
        __("Create Booking")
      );
    });
  },
  create_service_order: (frm) => {
    if (!frm.doc.service_order & (frm.doc.docstatus == 1)) {
      frm
        .add_custom_button(__("Create Service Order"), () => {
          frappe.new_doc(
            "Service Order",
            {
              container_inspection: frm.doc.name,
              consignee: frm.doc.consignee,
              clearing_agent: frm.doc.c_and_f_agent,
              c_and_f_company: frm.doc.c_and_f_company,
              container_id: frm.doc.container_id,
              container_no: frm.doc.container_no,
              container_location: frm.doc.container_location,
            },
            (doc) => {}
          );
        })
        .addClass("btn-primary");
    }
  },
});
