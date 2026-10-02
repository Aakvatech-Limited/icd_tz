// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("Container", {
  refresh: (frm) => {
    if (
      frm.doc.freight_indicator === "LCL" &&
      !frm.doc.has_hbl &&
      !frm.doc.is_empty_container &&
      !["At Gate Confirmation", "Delivered"].includes(frm.doc.status)
    ) {
      frm.add_custom_button(__("Unpack Container"), () => {
        frappe.new_doc("Container Unpacking", { container_id: frm.doc.name });
      });
    }
  },
});
