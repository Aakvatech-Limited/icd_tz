// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gate Pass", {
  refresh(frm) {
    frm.trigger("set_filters");
  },
  onload: (frm) => {
    frm.trigger("set_filters");
  },
  set_filters: (frm) => {
    frm.set_query("clearing_agent", () => {
      return {
        filters: {
          disabled: 0,
          c_and_f_company: frm.doc.c_and_f_company,
        },
      };
    });
  },
  action_for_missing_booking: (frm) => {
    if (frm.doc.action_for_missing_booking) {
      frm.set_value("missing_booking_allowed_by", frappe.session.user_fullname);
      frm.refresh_field("missing_booking_allowed_by");
    } else {
      frm.set_value("missing_booking_allowed_by", "");
      frm.refresh_field("missing_booking_allowed_by");
    }
  },
});
