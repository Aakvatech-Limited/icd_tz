// Copyright (c) 2026, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("EDI Partner", {
  test_connection(frm) {
    if (frm.is_dirty()) {
      frappe.msgprint(
        __("Please save the record before testing the connection")
      );
      return;
    }

    frappe.call({
      method: "try_edi_connection",
      doc: frm.doc,
      freeze: true,
      freeze_message: __("Testing EDI connection..."),
      callback: (r) => {
        if (r.message && r.message.success) {
          frappe.msgprint({
            title: __("Success"),
            message: r.message.message,
            indicator: "green",
          });
        }
      },
    });
  },
});

// A child DocType never loads its own script, so its handlers belong here.
frappe.ui.form.on("EDI Partner Template", {
  reset_template(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.edi_type) {
      frappe.msgprint(__("Please pick an EDI Type first"));
      return;
    }

    frappe.confirm(
      __(
        "Replace this template with the one shipped with the app? Your changes will be lost."
      ),
      () => pull_shipped_template(frm, row)
    );
  },

  edi_type(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (row.edi_type && !row.template) {
      pull_shipped_template(frm, row);
    }
  },
});

function pull_shipped_template(frm, row) {
  frappe.call({
    method: "icd_tz.icd_tz.api.edi.templates.get_shipped_template",
    args: { edi_type: row.edi_type },
    freeze: true,
    callback: (r) => {
      if (!r.message) return;

      frappe.model.set_value(row.doctype, row.name, "template", r.message);
      frm.refresh_field("templates");
    },
  });
}
