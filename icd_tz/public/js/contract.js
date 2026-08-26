frappe.ui.form.on("Contract", {
  setup: function (frm) {
    // Clear standard ERPNext party_name handlers that were loaded before setup
    if (frappe.ui.form.handlers && frappe.ui.form.handlers.Contract) {
      frappe.ui.form.handlers.Contract.party_name = [];
    }

    // Register our single source of truth for party_name
    frappe.ui.form.on("Contract", "party_name", function (frm) {
      if (!frm.doc.party_name) {
        frm.set_value("party_full_name", "");
        return;
      }

      if (frm.doc.party_type === "Clearing and Forwarding Company") {
        frappe.db.get_value(
          frm.doc.party_type,
          frm.doc.party_name,
          "company_name",
          (r) => {
            if (r && r.company_name) {
              frm.set_value("party_full_name", r.company_name);
            }
          }
        );
      } else {
        let field = frm.doc.party_type.toLowerCase() + "_name";
        frappe.db.get_value(
          frm.doc.party_type,
          frm.doc.party_name,
          field,
          (r) => {
            if (r && r[field]) {
              frm.set_value("party_full_name", r[field]);
            }
          }
        );
      }
    });
  },
});

frappe.ui.form.on("Contract", {
  refresh: function (frm) {
    set_destination_options(frm);
  },

  is_storage_days_based: function (frm) {
    set_destination_options(frm);
  },
});

function set_destination_options(frm) {
  // The Storage Days destinations are the ones defined in ICD TZ Settings
  const grid =
    frm.fields_dict.storage_days && frm.fields_dict.storage_days.grid;
  if (!grid || !frm.doc.is_storage_days_based) {
    return;
  }

  frappe
    .call({ method: "icd_tz.icd_tz.api.contract.get_storage_destinations" })
    .then((r) => {
      grid.update_docfield_property("destination", "options", [
        "",
        ...(r.message || []),
      ]);
      grid.refresh();
    });
}
