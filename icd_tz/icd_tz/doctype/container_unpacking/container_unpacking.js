// Copyright (c) 2026, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on("Container Unpacking", {
  setup: (frm) => {
    frm.set_query("container_id", () => {
      return {
        filters: {
          has_hbl: 0,
          is_empty_container: 0,
          freight_indicator: "LCL",
          status: ["not in", ["At Gate Confirmation", "Delivered"]],
        },
      };
    });
  },
  refresh: (frm) => {
    // a form opened from the Container arrives with the container set and no rows
    if (frm.is_new() && frm.doc.container_id && !frm.doc.hbls?.length) {
      frm.trigger("container_id");
    }
  },
  container_id: (frm) => {
    frm.clear_table("hbls");
    frm.refresh_field("hbls");

    if (frm.doc.container_id) {
      frm.call("set_hbls").then(() => frm.refresh_field("hbls"));
    }
  },
});

frappe.ui.form.on("Container Unpacking Detail", {
  counted_packages: (frm, cdt, cdn) => {
    const row = locals[cdt][cdn];
    frappe.model.set_value(
      cdt,
      cdn,
      "package_difference",
      cint(row.counted_packages) - cint(row.manifest_packages)
    );
  },
});
