frappe.ui.form.on("Purchase Invoice", {
  refresh: (frm) => {
    if (frm.doc.docstatus !== 0) return;

    frm.add_custom_button(
      __("Transport Services"),
      () => show_transport_services_dialog(frm),
      __("Get Items From")
    );
  },
});

var show_transport_services_dialog = (frm) => {
  // without Edit Posting Date, save moves the invoice to today
  const posting_date = frm.doc.set_posting_time
    ? frm.doc.posting_date
    : frappe.datetime.get_today();

  let d = new frappe.ui.Dialog({
    title: __("Get Transport Services"),
    fields: [
      {
        label: __("Supplier"),
        fieldname: "supplier",
        fieldtype: "Link",
        options: "Supplier",
        reqd: 1,
        default: frm.doc.supplier,
      },
      {
        label: __("From Date"),
        fieldname: "from_date",
        fieldtype: "Date",
        reqd: 1,
      },
      {
        label: __("To Date"),
        fieldname: "to_date",
        fieldtype: "Date",
        reqd: 1,
        default: frappe.datetime.get_today(),
      },
      {
        fieldtype: "HTML",
        options: `<p class="text-muted small">${__(
          "Every item on this invoice is replaced by one line per container received in the period."
        )}</p>`,
      },
    ],
    size: "small",
    primary_action_label: __("Get Transport Services"),
    primary_action(values) {
      frappe.call({
        method: "icd_tz.icd_tz.api.transport_charges.get_transport_services",
        args: {
          company: frm.doc.company,
          purchase_invoice: frm.is_new() ? null : frm.doc.name,
          posting_date: posting_date,
          ...values,
        },
        freeze: true,
        callback: async (r) => {
          d.hide();
          await set_transport_services(
            frm,
            values.supplier,
            posting_date,
            r.message
          );
        },
      });
    },
  });

  d.show();
};

var set_transport_services = async (frm, supplier, posting_date, services) => {
  if (frm.doc.supplier !== supplier) {
    await frm.set_value("supplier", supplier);
  }

  // the supplier fetch can set its own price list, so the settings one is applied after it
  frappe.after_ajax(async () => {
    frm.clear_table("items");
    await frm.set_value("buying_price_list", services.buying_price_list);
    services.items.forEach((item) => frm.add_child("items", item));
    frm.refresh_field("items");
    frm.cscript.calculate_taxes_and_totals();

    if (services.contract) {
      frappe.show_alert({
        message: __("Priced from Contract {0}", [
          frappe.utils.escape_html(services.contract),
        ]),
        indicator: "blue",
      });
    }

    if (services.unpriced_items.length) {
      frappe.msgprint({
        title: __("Transport Items Without a Price"),
        indicator: "orange",
        message: __(
          "These items have no buying price on {0}, so their lines have a zero rate. Set the rate before you submit: {1}",
          [
            frappe.datetime.str_to_user(posting_date),
            services.unpriced_items
              .map((item) => frappe.utils.escape_html(item))
              .join(", "),
          ]
        ),
      });
    }
  });
};
