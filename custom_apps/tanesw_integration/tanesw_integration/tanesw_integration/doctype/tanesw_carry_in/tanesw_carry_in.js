frappe.ui.form.on('TANeSW Carry In', {
	onload(frm) {
		if (frm.is_new() && !frm.doc.warehouse_code) {
			frappe.xcall("tanesw_integration.credentials.get_facility_code").then((code) => code && frm.set_value("warehouse_code", code));
		}
	},
	refresh: function(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__('Validate Container in TANeSW'), function() {
				if (!frm.doc.container_no) {
					frappe.msgprint(__('Please specify a Container No'));
					return;
				}
				frappe.call({
					method: 'tanesw_integration.api.validate_carry_in_container',
					args: {
						wrhs_cd: frm.doc.warehouse_code,
						cntr_no: frm.doc.container_no,
						crn: frm.doc.crn || ''
					},
					freeze: true,
					freeze_message: __('Validating Container in TANeSW...'),
					callback: function(r) {
						if (r.message) {
							frappe.msgprint({
								title: __('Validation Result'),
								message: '<pre>' + JSON.stringify(r.message, null, 2) + '</pre>',
								indicator: 'blue'
							});
						}
					}
				});
			});

			frm.add_custom_button(__('Submit Carry-In to TANeSW'), function() {
				frappe.confirm(__('Are you sure you want to submit this Carry-In report to TANeSW?'), function() {
					frappe.call({
						method: 'tanesw_integration.api.submit_carry_in_report',
						args: {
							payload: {
								criBaseNo: frm.doc.cri_base_no,
								wrhsCd: frm.doc.warehouse_code,
								crn: frm.doc.crn,
								mrn: frm.doc.mrn,
								cntrNo: frm.doc.container_no,
								vhclNo: frm.doc.vehicle_no,
								drvrNm: frm.doc.driver_name
							}
						},
						freeze: true,
						freeze_message: __('Submitting to TANeSW...'),
						callback: function(r) {
							if (r.message) {
								frappe.show_alert({ message: __('Carry-In submitted successfully'), indicator: 'green' });
								frm.set_value('status', 'REPORTED');
								frm.save();
							}
						}
					});
				});
			}).addClass('btn-danger');
		}
	}
});
