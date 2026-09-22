frappe.listview_settings["Sales Order"] = {
  add_fields: [],
  hide_name_column: true,

  onload: (listview) => {
    listview.page
      .add_inner_button(__("Create Sales Order"), () => {
        show_dialog();
      })
      .removeClass("btn-default")
      .addClass("btn-info btn-sm");
  },
};

var show_dialog = () => {
  let d = new frappe.ui.Dialog({
    title: "Create Sales Order",
    fields: [
      {
        label: "M BL No",
        fieldname: "m_bl_no",
        fieldtype: "Data",
        reqd: 0,
      },
      {
        fieldname: "h_bl_cb",
        fieldtype: "Column Break",
      },
      {
        label: "H BL No",
        fieldname: "h_bl_no",
        fieldtype: "Data",
        reqd: 0,
        depends_on: "eval:!doc.is_empty_container",
      },
      {
        fieldname: "empty_sb",
        fieldtype: "Section Break",
      },
      {
        label: "Is Empty Container",
        fieldname: "is_empty_container",
        fieldtype: "Check",
        default: 0,
        description:
          "Bill the empty containers of the M BL to the shipping line, for storage only",
      },
      {
        fieldname: "customer_cb",
        fieldtype: "Column Break",
      },
      {
        label: "Customer",
        fieldname: "customer",
        fieldtype: "Link",
        options: "Customer",
        depends_on: "is_empty_container",
        mandatory_depends_on: "is_empty_container",
      },
    ],
    size: "small",
    primary_action_label: "Create Order",
    primary_action(values) {
      if (values) {
        if (values.is_empty_container && !values.m_bl_no) {
          frappe.msgprint({
            title: __("Validation Error"),
            indicator: "red",
            message: __(
              "Please enter the <b>M BL No</b> of the empty containers to bill"
            ),
          });
          return;
        }

        if (!values.is_empty_container && !values.m_bl_no && !values.h_bl_no) {
          frappe.msgprint({
            title: __("Validation Error"),
            indicator: "red",
            message: __("Please enter either M BL No or H BL No"),
          });
          return;
        }

        if (!values.is_empty_container && values.m_bl_no && values.h_bl_no) {
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
          method: "icd_tz.icd_tz.api.sales_order.create_sales_order",
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
                  message: __("Sales Order Created successfully"),
                  indicator: "green",
                },
                10
              );
            }
          },
        });
      }
    },
  });

  d.fields_dict.is_empty_container.df.onchange = () => {
    if (d.get_value("is_empty_container")) {
      d.set_value("h_bl_no", "");
    }
  };

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
