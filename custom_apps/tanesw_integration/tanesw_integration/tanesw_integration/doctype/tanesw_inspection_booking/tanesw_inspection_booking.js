frappe.ui.form.on('TANeSW Inspection Booking', {
	onload(frm) {
		if (frm.is_new() && !frm.doc.warehouse_code) {
			frappe.xcall("tanesw_integration.credentials.get_facility_code").then((code) => code && frm.set_value("warehouse_code", code));
		}
	},
	refresh: function(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__('Fetch Booking from TANeSW'), function() {
				frappe.call({
					method: 'tanesw_integration.api.booking_detail',
					args: { tansad_no: frm.doc.tansad_no },
					freeze: true,
					callback: function(r) {
						if (r.message) {
							let b = r.message.jntInscBkngInfo || {};
							if (b.bkngRqstDt) frm.set_value('booking_request_date', b.bkngRqstDt);
							if (b.bkngAprvDtm) frm.set_value('booking_approval_datetime', b.bkngAprvDtm);
							if (b.prcsStatCd) frm.set_value('process_status_code', b.prcsStatCd);
							if (b.coNm) frm.set_value('company_name', b.coNm);
							if (b.godsLoctWrhsCd) frm.set_value('warehouse_code', b.godsLoctWrhsCd);
							if (b.blNo) frm.set_value('bl_no', b.blNo);
							frm.set_value('status', b.prcsStatCd === 'B' ? 'Approved' : 'Requested');
							frm.set_value('raw_response', JSON.stringify(r.message, null, 2));
							frm.save();
							frappe.show_alert({ message: __('Booking fetched and updated'), indicator: 'green' });
						}
					}
				});
			});

			frm.add_custom_button(__('Submit Booking to TANeSW'), function() {
				frappe.confirm(__('Submit this Joint Inspection Booking to TANeSW?'), function() {
					frappe.call({
						method: 'tanesw_integration.api.submit_inspection_booking',
						args: {
							payload: {
								tansadNo: frm.doc.tansad_no,
								bkngRqstDt: frm.doc.booking_request_date,
								godsLoctWrhsCd: frm.doc.warehouse_code,
								coNm: frm.doc.company_name,
								blNo: frm.doc.bl_no
							}
						},
						freeze: true,
						callback: function(r) {
							frappe.show_alert({ message: __('Booking submitted'), indicator: 'green' });
							frm.set_value('status', 'Requested');
							frm.save();
						}
					});
				});
			}).addClass('btn-primary');
		}
	}
});
