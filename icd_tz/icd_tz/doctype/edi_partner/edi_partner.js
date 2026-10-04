// Copyright (c) 2026, elius mgani and contributors
// For license information, please see license.txt

// what a container event is previewed from, its shipping line field, and the method that builds its message
const EDI_PREVIEWS = {
  "Gate In": {
    doctype: "Container Reception",
    fieldname: "container_reception",
    code_field: "shipping_line_code",
    method: "icd_tz.icd_tz.api.edi.codeco.generate_codeco_gate_in",
  },
  "Gate Out": {
    doctype: "Gate Pass",
    fieldname: "gate_pass",
    code_field: "shipping_line_code",
    method: "icd_tz.icd_tz.api.edi.codeco.generate_codeco_gate_out",
  },
  Unpacking: {
    doctype: "Container Unpacking",
    fieldname: "container_unpacking",
    code_field: "sline_code",
    method: "icd_tz.icd_tz.api.edi.costco.generate_costco_unpacking",
  },
};

frappe.ui.form.on("EDI Partner", {
  refresh(frm) {
    if (frm.is_new()) return;

    frm.add_custom_button(__("Preview EDI"), () => pick_edi_preview(frm));
  },

  enable_edi(frm) {
    // the default is shown when EDI is ticked, so it can be changed to the partner's convention
    if (!frm.doc.enable_edi || frm.doc.file_name_format) return;

    frappe.call({
      method:
        "icd_tz.icd_tz.doctype.edi_partner.edi_partner.get_default_file_name_format",
      callback: (r) => frm.set_value("file_name_format", r.message),
    });
  },

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

function pick_edi_preview(frm) {
  const link_fields = Object.entries(EDI_PREVIEWS).map(
    ([edi_type, preview]) => ({
      fieldtype: "Link",
      fieldname: preview.fieldname,
      label: __(preview.doctype),
      options: preview.doctype,
      depends_on: `eval: doc.edi_type == "${edi_type}"`,
      mandatory_depends_on: `eval: doc.edi_type == "${edi_type}"`,
      // only the movements this partner's shipping line is sent messages for
      get_query: () => ({
        filters: { [preview.code_field]: frm.doc.name, docstatus: ["!=", 2] },
      }),
    })
  );

  const dialog = new frappe.ui.Dialog({
    title: __("Preview EDI"),
    fields: [
      {
        fieldtype: "Select",
        fieldname: "edi_type",
        label: __("EDI Type"),
        options: ["", ...Object.keys(EDI_PREVIEWS)],
        reqd: 1,
      },
      ...link_fields,
    ],
    primary_action_label: __("Preview"),
    primary_action(values) {
      dialog.hide();
      show_edi_preview(frm, values.edi_type, values);
    },
  });

  dialog.show();
}

function show_edi_preview(frm, edi_type, values) {
  const { method, fieldname } = EDI_PREVIEWS[edi_type];

  frappe.call({
    method,
    args: { [fieldname]: values[fieldname], edi_partner: frm.doc.name },
    freeze: true,
    freeze_message: __("Building the EDI message..."),
    callback(r) {
      if (!r.message) {
        frappe.msgprint({
          title: __("No EDI message for this record"),
          indicator: "orange",
          message: __(
            "No message is owed. Either the unit is not a container, or it is cargo on a house bill."
          ),
        });
        return;
      }

      const {
        edi_type: message_type,
        edi_content: content,
        filename,
      } = r.message;

      const dialog = new frappe.ui.Dialog({
        title: __("{0} {1}", [message_type, __(edi_type)]),
        size: "large",
        fields: [{ fieldtype: "HTML", fieldname: "edi" }],
        primary_action_label: __("Download"),
        primary_action() {
          download_edi_file(content, filename);
        },
        secondary_action_label: __("Copy"),
        secondary_action() {
          frappe.utils.copy_to_clipboard(content);
        },
      });

      dialog.fields_dict.edi.$wrapper.html(`
        <div class="mb-2 font-weight-bold">${frappe.utils.escape_html(
          filename
        )}</div>
        <pre class="border rounded p-3 m-0"
             style="max-height: 58vh; overflow: auto; font-size: 12px;"
        >${frappe.utils.escape_html(content)}</pre>
      `);

      dialog.show();
    },
  });
}

function download_edi_file(content, filename) {
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/plain;charset=utf-8" })
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
