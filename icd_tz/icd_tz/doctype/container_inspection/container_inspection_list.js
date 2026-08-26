frappe.listview_settings["Container Inspection"] = {
  add_fields: [],
  hide_name_column: true,

  onload: (listview) => {
    $('button[data-label="Add Container Inspection"]').hide();

    listview.page
      .add_inner_button(__("Create Bulk Inspections"), () => {
        show_dialog(listview);
      })
      .removeClass("btn-default")
      .addClass("btn-info btn-sm");
  },
  button: {
    show: function (doc) {
      return doc.docstatus === 0;
    },
    get_label: function () {
      return __("<strong>Submit</strong>");
    },
    get_description: function (doc) {
      return __("Submit {0}", [`${__(doc.name)}: ${doc.container_no}`]);
    },
    action: function (doc) {
      frappe.call({
        method: "icd_tz.icd_tz.api.utils.submit_doc",
        args: {
          doc_type: "Container Inspection",
          doc_name: doc.name,
        },
        freeze: true,
        freeze_message: __('<i class="fa fa-spinner fa-spin fa-4x"></i>'),
        callback: function (response) {
          if (response.message) {
            frappe.show_alert(
              __("Container Inspection: {0} submitted successfully.", [
                doc.name,
              ]),
              5
            );
          } else {
            frappe.show_alert(
              __("Failed to submit Container Inspection {0}.", [doc.name]),
              5
            );
          }
        },
      });
    },
  },
};

var show_dialog = (listview) => {
  let d = new frappe.ui.Dialog({
    title: "Bulk Inspections",
    fields: [
      {
        label: "M BL No",
        fieldname: "m_bl_no",
        fieldtype: "Data",
        reqd: 0,
      },
      {
        label: "H BL No",
        fieldname: "h_bl_no",
        fieldtype: "Data",
        reqd: 0,
      },
      {
        fieldname: "insp_cb",
        fieldtype: "Column Break",
      },
      {
        label: "Inspector Name",
        fieldname: "inspector_name",
        fieldtype: "Data",
        reqd: 1,
      },
    ],
    size: "large",
    primary_action_label: "Create Inspections",
    primary_action(values) {
      if (values) {
        if (!values.m_bl_no && !values.h_bl_no) {
          frappe.msgprint({
            title: __("Validation Error"),
            indicator: "red",
            message: __("Please enter either M BL No or H BL No"),
          });
          return;
        }

        if (values.m_bl_no && values.h_bl_no) {
          frappe.msgprint({
            title: __("Validation Error"),
            indicator: "red",
            message: __(
              "Invalid input: You must enter EITHER <b>M BL No</b> or <b>H BL No</b>, but not both. Please clear one of these fields to proceed."
            ),
          });
          return;
        }

        frappe.call({
          method:
            "icd_tz.icd_tz.doctype.container_inspection.container_inspection.create_bulk_inspections",
          args: {
            data: values,
          },
          freeze: true,
          freeze_message: __('<i class="fa fa-spinner fa-spin fa-4x"></i>'),
          callback: (r) => {
            if (r.message) {
              d.hide();
              frappe.show_alert(
                {
                  message: __("{0} Inspections Created successfully", [
                    r.message,
                  ]),
                  indicator: "green",
                },
                10
              );
            }
            listview.refresh();
          },
        });
      }
    },
  });

  d.fields_dict.m_bl_no.df.onchange = () => {
    if (d.get_value("m_bl_no") && d.get_value("h_bl_no")) {
      frappe.msgprint({
        title: __("Validation Error"),
        indicator: "red",
        message: __(
          "Invalid input: You must enter EITHER <b>M BL No</b> or <b>H BL No</b>, but not both. Please clear one of these fields to proceed."
        ),
      });
    }
  };

  d.fields_dict.h_bl_no.df.onchange = () => {
    if (d.get_value("h_bl_no") && d.get_value("m_bl_no")) {
      frappe.msgprint({
        title: __("Validation Error "),
        indicator: "red",
        message: __(
          "Invalid input: You must enter EITHER <b>M BL No</b> or <b>H BL No</b>, but not both. Please clear one of these fields to proceed."
        ),
      });
    }
  };

  d.show();
};
