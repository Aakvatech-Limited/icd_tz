frappe.ui.form.on("Waiver Request", {
  setup: (frm) => {
    frm.set_query("sales_order", () => {
      return { filters: { docstatus: 0 } };
    });
  },
});
