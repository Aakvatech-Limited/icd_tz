frappe.ui.form.on("Vehicle", {
  setup: function (frm) {
    frm.set_query("vehicle_owner", function () {
      return {
        filters: {
          is_transporter: 1,
          disabled: 0,
        },
      };
    });
  },
});
