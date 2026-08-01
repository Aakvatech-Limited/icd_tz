frappe.ui.form.on("Waiver Request", {
  setup: (frm) => {
    frm.set_query("sales_order", () => {
      return { filters: { docstatus: 0 } };
    });
  },
  sales_order: (frm) => {
    frm.clear_table("items");
    frm.refresh_field("items");
  },
  apply_discount_on: (frm) => {
    if (frm.doc.apply_discount_on == "Single Item" && frm.doc.sales_order) {
      frm.clear_table("items");
      get_items(frm);
    } else {
      frm.clear_table("items");
      frm.refresh_field("items");
    }
  },
  additional_discount_percentage: (frm) => {
    recalculate_item_discounts(frm);
  },
  discount_amount: (frm) => {
    recalculate_item_discounts(frm);
  },
  discount_criteria: (frm) => {
    recalculate_item_discounts(frm);
  },
});

frappe.ui.form.on("Waiver Request Item", {
  items_add: (frm) => {
    if (frm.doc.sales_order) {
      get_items(frm, true);
    }
  },
  item_code: (frm, cdt, cdn) => {
    let row = frappe.get_doc(cdt, cdn);
    if (row.item_code && frm.doc.sales_order) {
      get_item_details(frm, row);
    }
  },
});

var get_items = (frm, reset_options = false) => {
  frappe
    .call({
      method: "icd_tz.icd_tz.doctype.waiver_request.waiver_request.get_items",
      args: { sales_order: frm.doc.sales_order },
    })
    .then((r) => {
      if (!r.message || r.message.length == 0) {
        frappe.show_alert({
          message: __("No items found on the selected Sales Order"),
          indicator: "red",
        });
        return;
      }

      if (reset_options) {
        set_item_code_options(frm, r.message);
        return;
      }

      r.message.forEach((row) => {
        add_item_row(frm, row);
      });
      frm.refresh_field("items");
    });
};

var get_item_details = (frm, row) => {
  frappe
    .call({
      method:
        "icd_tz.icd_tz.doctype.waiver_request.waiver_request.get_item_details",
      args: {
        sales_order: frm.doc.sales_order,
        item_code: row.item_code,
      },
    })
    .then((r) => {
      if (!r.message || r.message.length == 0) {
        return;
      }

      set_row_amounts(frm, row, r.message[0]);
      frm.refresh_field("items");
    });
};

var add_item_row = (frm, item) => {
  let row = frm.add_child("items");
  set_row_amounts(frm, row, item);
};

var set_row_amounts = (frm, row, item) => {
  let discount_amount = get_row_discount_amount(frm, item.actual_price);
  row.item_code = item.item_code;
  row.item_name = item.item_name;
  row.actual_price = item.actual_price;
  row.so_detail = item.so_detail;
  row.discount_amount = discount_amount;
  row.amount_after_discount = item.actual_price - discount_amount;
};

var get_row_discount_amount = (frm, actual_price) => {
  if (frm.doc.discount_criteria == "Waiver Based on Percentage") {
    return (actual_price * (frm.doc.additional_discount_percentage || 0)) / 100;
  }

  if (frm.doc.discount_criteria == "Waiver Based on Actual Amount") {
    return frm.doc.discount_amount || 0;
  }

  return 0;
};

var recalculate_item_discounts = (frm) => {
  if (frm.doc.apply_discount_on != "Single Item" || !frm.doc.items.length) {
    return;
  }

  frm.doc.items.forEach((row) => {
    row.discount_amount = get_row_discount_amount(frm, row.actual_price);
    row.amount_after_discount = row.actual_price - row.discount_amount;
  });
  frm.refresh_field("items");
};

var set_item_code_options = (frm, data) => {
  let options = data.map((row) => row.item_code);
  const grid = frm.get_field("items").grid;

  grid.visible_columns = undefined;
  grid.setup_visible_columns();
  grid.fields_map.item_code.options = options;

  grid.grid_rows.forEach((row) => {
    row.docfields.forEach((docfield) => {
      if (docfield.fieldname === "item_code") {
        docfield.options = options;
      }
    });
  });

  frm.refresh_field("items");
  grid.refresh();
};
