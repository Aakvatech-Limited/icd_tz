// Copyright (c) 2026, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("ICD Container", {
  refresh(frm) {
    if (frm.doc.ship_dc_date || frm.is_new()) return;

    frm.add_custom_button(__("Fetch Ship D/C Date"), () => {
      frm.call({
        method: "fetch_ship_dc_date",
        doc: frm.doc,
        freeze: true,
        freeze_message: __("Looking up the discharge date in TANeSW..."),
        callback: (r) => {
          if (!r.message) {
            frappe.msgprint(
              __(
                "TANeSW has no approved discharge date for this container yet."
              )
            );
            return;
          }
          frm.reload_doc();
        },
      });
    });
  },
});
