frappe.ui.form.on("Sales Order", {
  update_items: (frm) => {
    if (!frm.doc.m_bl_no && !frm.doc.h_bl_no) {
      frappe.msgprint("Please enter M BL No or H BL No");
      return;
    }

    if (frm.is_dirty()) {
      frappe.msgprint("Please save the document before updating items");
      return;
    }

    frappe.call({
      method: "icd_tz.icd_tz.api.sales_order.update_items_on_sales_order",
      args: {
        doc_name: frm.doc.name,
      },
      freeze: true,
      freeze_message: __('<i class="fa fa-spinner fa-spin fa-4x"></i>'),
      callback: (r) => {
        if (r.message) {
          frm.reload_doc();
        }
      },
    });
  },
  request_waiver: (frm) => {
    if (frm.is_dirty()) {
      frappe.msgprint("Please save the document before requesting a waiver");
      return;
    }

    show_waiver_dialog(frm);
  },
});

var show_waiver_dialog = (frm) => {
  let dialog = new frappe.ui.Dialog({
    title: __("Request Waiver"),
    fields: [
      {
        fieldname: "apply_discount_on",
        label: __("Apply Discount On"),
        fieldtype: "Select",
        options: "\nGrand Total\nNet Total\nSingle Item",
        reqd: 1,
      },
      {
        fieldname: "waiver_cb_1",
        fieldtype: "Column Break",
      },
      {
        fieldname: "discount_criteria",
        label: __("Discount Criteria"),
        fieldtype: "Select",
        options: "\nWaiver Based on Percentage\nWaiver Based on Actual Amount",
        reqd: 1,
      },
      {
        fieldname: "waiver_cb_2",
        fieldtype: "Column Break",
      },
      {
        fieldname: "additional_discount_percentage",
        label: __("Discount (%)"),
        fieldtype: "Float",
        depends_on:
          "eval:doc.discount_criteria == 'Waiver Based on Percentage'",
      },
      {
        fieldname: "discount_amount",
        label: __("Discount Amount"),
        fieldtype: "Currency",
        depends_on:
          "eval:doc.discount_criteria == 'Waiver Based on Actual Amount'",
      },
      {
        fieldname: "reason_sec",
        fieldtype: "Section Break",
      },
      {
        fieldname: "waiver_reason",
        label: __("Waiver Reason"),
        fieldtype: "Small Text",
        reqd: 1,
        description: __("Reason why this Sales Order is requesting a waiver"),
      },
      {
        fieldname: "items_sec",
        fieldtype: "Section Break",
        label: __("Items"),
        depends_on: "eval:doc.apply_discount_on == 'Single Item'",
      },
      {
        fieldname: "items",
        fieldtype: "HTML",
      },
    ],
  });

  let wrapper = dialog.fields_dict.items.$wrapper;

  dialog.fields_dict.apply_discount_on.df.onchange = () => {
    if (dialog.get_value("apply_discount_on") == "Single Item") {
      render_waiver_items(frm, dialog, wrapper);
    } else {
      wrapper.html("");
    }
  };
  dialog.fields_dict.discount_criteria.df.onchange = () => {
    if (dialog.get_value("apply_discount_on") == "Single Item") {
      render_waiver_items(frm, dialog, wrapper);
    }
  };
  dialog.fields_dict.additional_discount_percentage.df.onchange = () => {
    if (dialog.get_value("apply_discount_on") == "Single Item") {
      render_waiver_items(frm, dialog, wrapper);
    }
  };
  dialog.fields_dict.discount_amount.df.onchange = () => {
    if (dialog.get_value("apply_discount_on") == "Single Item") {
      render_waiver_items(frm, dialog, wrapper);
    }
  };

  dialog.set_primary_action(__("Request Waiver"), () => {
    let data = dialog.get_values();
    if (!data) {
      return;
    }

    let items = null;
    if (data.apply_discount_on == "Single Item") {
      items = get_checked_waiver_items(wrapper);
      if (items.length == 0) {
        frappe.msgprint(__("Please select at least one Item"));
        return;
      }
    }

    frappe.call({
      method:
        "icd_tz.icd_tz.doctype.waiver_request.waiver_request.create_waiver_request",
      args: {
        sales_order: frm.doc.name,
        apply_discount_on: data.apply_discount_on,
        discount_criteria: data.discount_criteria,
        waiver_reason: data.waiver_reason,
        additional_discount_percentage: data.additional_discount_percentage,
        discount_amount: data.discount_amount,
        items: items,
      },
      freeze: true,
      freeze_message: __("Please wait..."),
      callback: (r) => {
        if (r.message) {
          dialog.hide();
          frappe.show_alert({
            message: __("Waiver Request {0} created successfully", [r.message]),
            indicator: "green",
          });
          frm.reload_doc();
        }
      },
    });
  });

  dialog.show();
};

var get_waiver_row_discount = (dialog, actual_price) => {
  if (dialog.get_value("discount_criteria") == "Waiver Based on Percentage") {
    return (
      (actual_price *
        (dialog.get_value("additional_discount_percentage") || 0)) /
      100
    );
  }

  if (
    dialog.get_value("discount_criteria") == "Waiver Based on Actual Amount"
  ) {
    return Math.min(dialog.get_value("discount_amount") || 0, actual_price);
  }

  return 0;
};

var render_waiver_items = (frm, dialog, wrapper) => {
  let html = `<table class="table table-hover" style="width:100%;">
        <colgroup>
            <col width="5%">
            <col width="30%">
            <col width="15%">
            <col width="16%">
            <col width="16%">
            <col width="18%">
        </colgroup>
        <tr>
            <th><input type="checkbox" id="waiver-select-all" /></th>
            <th style="background-color: #D3D3D3;">Item</th>
            <th style="background-color: #D3D3D3;">Container No</th>
            <th style="background-color: #D3D3D3;">Amount</th>
            <th style="background-color: #D3D3D3;">Discount</th>
            <th style="background-color: #D3D3D3;">Amount After Discount</th>
        </tr>`;

  frm.doc.items.forEach((row) => {
    let discount_amount = get_waiver_row_discount(dialog, row.amount);
    let amount_after_discount = row.amount - discount_amount;

    html += `<tr class="waiver-item-row"
                data-item_code="${row.item_code}"
                data-item_name="${row.item_name}"
                data-actual_price="${row.amount}"
                data-container_no="${row.container_no || ""}"
                data-container_id="${row.container_id || ""}"
                data-discount_amount="${discount_amount}"
                data-amount_after_discount="${amount_after_discount}">
            <td><input type="checkbox" class="waiver-item-check"/></td>
            <td>${row.item_code}</td>
            <td>${row.container_no || ""}</td>
            <td>${format_currency(row.amount, frm.doc.currency)}</td>
            <td>${format_currency(discount_amount, frm.doc.currency)}</td>
            <td>${format_currency(amount_after_discount, frm.doc.currency)}</td>
        </tr>`;
  });
  html += `</table>`;
  wrapper.html(html);

  wrapper.find("#waiver-select-all").on("click", function () {
    wrapper.find(".waiver-item-check").prop("checked", $(this).is(":checked"));
  });
};

var get_checked_waiver_items = (wrapper) => {
  let items = [];
  wrapper
    .find("tr.waiver-item-row:has(.waiver-item-check:checked)")
    .each(function () {
      let $row = $(this);
      items.push({
        item_code: $row.data("item_code"),
        item_name: $row.data("item_name"),
        actual_price: $row.data("actual_price"),
        container_no: $row.data("container_no"),
        container_id: $row.data("container_id"),
        discount_amount: $row.data("discount_amount"),
        amount_after_discount: $row.data("amount_after_discount"),
      });
    });
  return items;
};
