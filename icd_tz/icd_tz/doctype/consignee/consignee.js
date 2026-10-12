// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("Consignee", {
  refresh(frm) {
    if (frm.doc.customer || frm.is_new()) return;

    frm.add_custom_button(__("Create Customer"), () => {
      frm.call({
        method: "create_customer",
        doc: frm.doc,
        freeze: true,
        callback: () => frm.reload_doc(),
      });
    });
  },
});
