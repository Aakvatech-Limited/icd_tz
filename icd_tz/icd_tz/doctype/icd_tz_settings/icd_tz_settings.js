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

    for (const field of ["wip_account", "cogs_account"]) {
      frm.set_query(field, () => {
        return {
          filters: {
            is_group: 0,
            company: frappe.defaults.get_user_default("Company"),
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
