frappe.ui.form.on("Driver", {
  setup: function (frm) {
    frm.set_query("transporter", function () {
      return {
        filters: {
          is_transporter: 1,
          disabled: 0,
        },
      };
    });
  },
});
