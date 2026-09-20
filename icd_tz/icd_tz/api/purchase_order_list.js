frappe.listview_settings["Purchase Order"] = {
  add_fields: [],

  onload: (listview) => {
    listview.page
      .add_inner_button(__("Create Port Expense Order"), () => {
        show_port_expense_dialog();
      })
      .removeClass("btn-default")
      .addClass("btn-info btn-sm");
  },
};

var show_port_expense_dialog = () => {
  let d = new frappe.ui.Dialog({
    title: __("Create Port Expense Order"),
    fields: [
      {
        label: __("Manifest"),
        fieldname: "manifest",
        fieldtype: "Link",
        options: "Manifest",
        reqd: 1,
        get_query: () => {
          return { filters: { docstatus: 1 } };
        },
      },
    ],
    size: "small",
    primary_action_label: __("Open Port Expenses"),
    primary_action(values) {
      d.hide();
      icd_tz.open_port_expenses(values.manifest);
    },
  });

  d.show();
};
