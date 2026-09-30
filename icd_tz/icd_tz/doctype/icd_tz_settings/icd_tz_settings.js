// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("ICD TZ Settings", {
  refresh: (frm) => {
    frm.trigger("set_filters");
  },
  onload: (frm) => {
    frm.trigger("set_filters");
  },
  set_filters: (frm) => {
    frm.set_query("service_name", "service_types", () => {
      return {
        filters: {
          item_group: "ICD Services",
        },
      };
    });

    frm.set_query("service_name", "loose_types", () => {
      return {
        filters: {
          item_group: "ICD Services",
        },
      };
    });

    // WIP holds the expense until release, then COGS takes it
    const root_types = { wip_account: "Asset", cogs_account: "Expense" };
    for (const [field, root_type] of Object.entries(root_types)) {
      frm.set_query(field, () => {
        const company = frappe.defaults.get_user_default("Company");
        return {
          filters: {
            is_group: 0,
            disabled: 0,
            root_type: root_type,
            company: company,
            // the balance moves in company currency, so an account in another
            // currency cannot be released without a rate to convert it back
            account_currency:
              frappe.get_doc(":Company", company)?.default_currency ||
              frappe.boot.sysdefaults.currency,
          },
        };
      });
    }

    frm.set_query("expense_item", "expense_types", () => {
      return {
        filters: {
          item_group: "ICD Services",
        },
      };
    });

    frm.set_query("transport_charge_item", () => {
      return {
        filters: {
          item_group: "ICD Services",
          is_purchase_item: 1,
        },
      };
    });

    frm.set_query("default_buying_price_list", () => {
      return {
        filters: {
          buying: 1,
        },
      };
    });

    frm.set_query("gatepass_cancellation_item", () => {
      return {
        filters: {
          item_group: "ICD Services",
        },
      };
    });
  },
});
