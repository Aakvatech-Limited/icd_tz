frappe.ui.form.on('TANeSW Declaration', {
	refresh: function(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__('Sync from TANeSW'), function() {
				frappe.call({
					method: 'tanesw_integration.api.sync_declaration',
					args: { tansad_no: frm.doc.tansad_no },
					freeze: true,
					freeze_message: __('Connecting to TANeSW...'),
					callback: function(r) {
						if (r.message && r.message.status === 'ok') {
							frappe.show_alert({ message: __('Synchronized from TANeSW'), indicator: 'green' });
							frm.reload_doc();
						}
					}
				});
			}).addClass('btn-primary');

			frm.add_custom_button(__('Create Carry-In'), function() {
				frappe.model.with_doctype('TANeSW Carry In', function() {
					let cri = frappe.model.get_new_doc('TANeSW Carry In');
					cri.tansad_no = frm.doc.tansad_no;
					cri.crn = frm.doc.crn;
					cri.mrn = frm.doc.mrn;
					cri.warehouse_code = frm.doc.warehouse_code;
					if (frm.doc.containers && frm.doc.containers.length > 0) {
						cri.container_no = frm.doc.containers[0].container_no;
						cri.seal_no = frm.doc.containers[0].seal_no;
						cri.weight = frm.doc.containers[0].weight;
					}
					frappe.set_route('Form', 'TANeSW Carry In', cri.name);
				});
			});

			frm.add_custom_button(__('Create Inspection Booking'), function() {
				frappe.model.with_doctype('TANeSW Inspection Booking', function() {
					let bkng = frappe.model.get_new_doc('TANeSW Inspection Booking');
					bkng.tansad_no = frm.doc.tansad_no;
					bkng.declaration_record = frm.doc.tansad_no;
					bkng.warehouse_code = frm.doc.warehouse_code;
					bkng.company_name = frm.doc.clearing_agent_name;
					bkng.bl_no = frm.doc.house_bl_no || frm.doc.master_bl_no;
					bkng.container_count = frm.doc.containers ? frm.doc.containers.length : 0;
					frappe.set_route('Form', 'TANeSW Inspection Booking', bkng.name);
				});
			});
		}
	}
});
