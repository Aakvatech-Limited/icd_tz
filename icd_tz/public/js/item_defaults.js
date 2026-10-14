// WIP holds a container expense until the container is invoiced, then COGS takes it
const ICD_ACCOUNT_ROOT_TYPES = {
  wip_account: "Asset",
  cogs_account: "Expense",
};

// money accounts never hold container expenses, matching EXCLUDED_ACCOUNT_TYPES on the server
const ICD_EXCLUDED_ACCOUNT_TYPES = ["Receivable", "Payable", "Bank", "Cash"];

const ICD_DEFAULT_TABLES = {
  Item: "item_defaults",
  "Item Group": "item_group_defaults",
};

for (const [doctype, table] of Object.entries(ICD_DEFAULT_TABLES)) {
  frappe.ui.form.on(doctype, {
    setup: (frm) => {
      for (const [field, root_type] of Object.entries(ICD_ACCOUNT_ROOT_TYPES)) {
        frm.set_query(field, table, (doc, cdt, cdn) => {
          const row = locals[cdt][cdn];
          return {
            filters: {
              is_group: 0,
              disabled: 0,
              root_type,
              account_type: ["not in", ICD_EXCLUDED_ACCOUNT_TYPES],
              company: row.company,
              account_currency: erpnext.get_currency(row.company),
            },
          };
        });
      }
    },
  });
}
