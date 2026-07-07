frappe.ui.form.on('Contract', {
    setup: function(frm) {
        // Clear standard ERPNext party_name handlers that were loaded before setup
        if (frappe.ui.form.handlers && frappe.ui.form.handlers.Contract) {
            frappe.ui.form.handlers.Contract.party_name = [];
        }

        // Register our single source of truth for party_name
        frappe.ui.form.on('Contract', 'party_name', function(frm) {
            if (!frm.doc.party_name) {
                frm.set_value("party_full_name", "");
                return;
            }

            if (frm.doc.party_type === "Clearing and Forwarding Company") {
                frappe.db.get_value(frm.doc.party_type, frm.doc.party_name, "company_name", (r) => {
                    if (r && r.company_name) {
                        frm.set_value("party_full_name", r.company_name);
                    }
                });
            } else {
                let field = frm.doc.party_type.toLowerCase() + "_name";
                frappe.db.get_value(frm.doc.party_type, frm.doc.party_name, field, (r) => {
                    if (r && r[field]) {
                        frm.set_value("party_full_name", r[field]);
                    }
                });
            }
        });
    }
});
