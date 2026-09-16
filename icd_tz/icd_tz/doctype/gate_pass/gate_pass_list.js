frappe.listview_settings["Gate Pass"] = {
  add_fields: [],
  hide_name_column: true,

  onload: (listview) => {
    $('button[data-label="Add Gate Pass"]').hide();

    listview.page
      .add_inner_button(__("Create Gate Pass for Empty Container"), () => {
        show_dialog(listview);
      })
      .removeClass("btn-default")
      .addClass("btn-info btn-sm");
  },
};

var show_dialog = (listview) => {
  let d = new frappe.ui.Dialog({
    title: "Gate Pass for Empty Container",
    fields: [
      {
        fieldname: "container_id",
        fieldtype: "Link",
        label: "Container ID",
        options: "Container",
        reqd: 1,
        get_query: () => {
          return {
            filters: {
              is_empty_container: 1,
            },
          };
        },
      },
    ],
    size: "small",
    primary_action_label: "Create Gate Pass",
    primary_action(values) {
      if (values) {
        frappe.call({
          method:
            "icd_tz.icd_tz.doctype.gate_pass.gate_pass.create_getpass_for_empty_container",
          args: {
            container_id: values.container_id,
          },
          freeze: true,
          freeze_message: __('<i class="fa fa-spinner fa-spin fa-4x"></i>'),
          callback: (r) => {
            if (r.message) {
              d.hide();
              frappe.show_alert(
                {
                  message: __("{0} Gate Pass Created successfully", [
                    r.message,
                  ]),
                  indicator: "green",
                },
                10
              );
              listview.refresh();
            }
          },
        });
      }
    },
  });

  d.show();
};
