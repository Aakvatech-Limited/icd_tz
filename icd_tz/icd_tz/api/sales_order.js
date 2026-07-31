
frappe.ui.form.on('Sales Order', {
	update_items: (frm) => {
        if (!frm.doc.m_bl_no && !frm.doc.h_bl_no) {
            frappe.msgprint("Please enter M BL No or H BL No")
            return;
        }

        if (frm.is_dirty()) {
            frappe.msgprint("Please save the document before updating items")
            return;
        }

        frappe.call({
            method: 'icd_tz.icd_tz.api.sales_order.update_items_on_sales_order',
            args: {
                doc_name: frm.doc.name
            },
            freeze: true,
            freeze_message: __('<i class="fa fa-spinner fa-spin fa-4x"></i>'),
            callback: (r) => {
                if (r.message) {
                    frm.reload_doc();
                }
            }
        });
    }
});
