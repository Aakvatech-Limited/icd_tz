// Copyright (c) 2024, elius mgani and contributors
// For license information, please see license.txt

frappe.ui.form.on('Manifest', {
	refresh: (frm) => {
		frm.trigger("create_movement_order");
		frm.trigger("icd_render_manifest_dashboard");
	},
	onload: (frm) => {
		if (!frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_user_default("Company"));
		}
		frm.trigger("create_movement_order");
		frm.trigger("icd_render_manifest_dashboard");
	},
	manifest: (frm) => {
		if (frm.doc.manifest) {
			frappe.call({
				method: "extract_data_from_manifest_file",
				doc: frm.doc,
				args: {
				},
				freeze: true,
				freeze_message: __("Extracting data from manifest file..."),
				callback: (r) => {
					if (r.message) {
						frm.refresh();
					}
				}
			});
		}
	},
	create_movement_order: (frm) => {
		if (frm.doc.docstatus == 1) {
			frm.add_custom_button(__('Create Movement Order'), () => {
				frappe.new_doc('Container Movement Order', {
					"manifest": frm.doc.name,
					"vessel_name": frm.doc.voyage,
					"received_date": frm.doc.arrival_date,
					"voyage_no": frm.doc.voyage_no,
					"company": frm.doc.company,
				}, doc => { });
			}).addClass('btn-primary');
		}
	},
	icd_render_manifest_dashboard: (frm) => {
		if (!frm.doc.name || frm.doc.containers.length == 0 || frm.doc.docstatus != 1) return;

		frappe.call({
			method: "get_dashboard_data",
			doc: frm.doc,
			callback: function (r) {
				if (r.message) {
					const data = r.message;

					const total = data.total_containers;
					const received = data.received_containers;
					const pending = data.pending_containers;

					const pct_received = total > 0 ? (received / total) * 100 : 0;
					const pct_pending = total > 0 ? (pending / total) * 100 : 0;

					let bar_segments = "";
					if (pct_received > 0) {
						bar_segments += `
						<div style="
							width: ${pct_received}%;
							background: #2ecc71; /* Green */
							height: 100%;
							transition: width 0.3s ease;
						" title="Received: ${received} of ${total} (${pct_received.toFixed(0)}%)"></div>
					`;
					}
					if (pct_pending > 0) {
						bar_segments += `
						<div style="
							width: ${pct_pending}%;
							background: #f39c12; /* Orange */
							height: 100%;
							transition: width 0.3s ease;
						" title="Pending: ${pending} of ${total} (${pct_pending.toFixed(0)}%)"></div>
					`;
					}

					const kpi_cards = `
					<div style="flex: 1; min-width: 90px; padding: 10px 14px; border-radius: 8px; background: var(--card-bg); border-left: 3px solid #3498db; text-align: center;">
						<div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #3498db; margin-bottom: 4px;">Total Units</div>
						<div style="font-size: 20px; font-weight: 700; color: var(--text-color);">${data.total_containers}</div>
					</div>
					<div style="flex: 1; min-width: 90px; padding: 10px 14px; border-radius: 8px; background: var(--card-bg); border-left: 3px solid #f39c12; text-align: center;">
						<div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #f39c12; margin-bottom: 4px;">FCL</div>
						<div style="font-size: 20px; font-weight: 700; color: var(--text-color);">${data.total_fcl}</div>
					</div>
					<div style="flex: 1; min-width: 90px; padding: 10px 14px; border-radius: 8px; background: var(--card-bg); border-left: 3px solid #9b59b6; text-align: center;">
						<div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #9b59b6; margin-bottom: 4px;">LCL</div>
						<div style="font-size: 20px; font-weight: 700; color: var(--text-color);">${data.total_lcl}</div>
					</div>
					<div style="flex: 1; min-width: 90px; padding: 10px 14px; border-radius: 8px; background: var(--card-bg); border-left: 3px solid #95a5a6; text-align: center;">
						<div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #95a5a6; margin-bottom: 4px;">Empty</div>
						<div style="font-size: 20px; font-weight: 700; color: var(--text-color);">${data.total_empty}</div>
					</div>
					<div style="flex: 1; min-width: 90px; padding: 10px 14px; border-radius: 8px; background: var(--card-bg); border-left: 3px solid #1abc9c; text-align: center;">
						<div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #1abc9c; margin-bottom: 4px;">Loose</div>
						<div style="font-size: 20px; font-weight: 700; color: var(--text-color);">${data.total_loose}</div>
					</div>
					<div style="flex: 1; min-width: 90px; padding: 10px 14px; border-radius: 8px; background: var(--card-bg); border-left: 3px solid #2ecc71; text-align: center;">
						<div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #2ecc71; margin-bottom: 4px;">Received</div>
						<div style="font-size: 20px; font-weight: 700; color: var(--text-color);">${data.received_containers}</div>
					</div>
					<div style="flex: 1; min-width: 90px; padding: 10px 14px; border-radius: 8px; background: var(--card-bg); border-left: 3px solid #e74c3c; text-align: center;">
						<div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #e74c3c; margin-bottom: 4px;">Pending</div>
						<div style="font-size: 20px; font-weight: 700; color: var(--text-color);">${data.pending_containers}</div>
					</div>
				`;

					const html = `
					<div class="icd-manifest-dashboard" style="margin-bottom: 16px;">
						<div style="font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; color: var(--text-muted); margin-bottom: 10px;">
							Container Reception Progress
						</div>

						<!-- Progress Bar -->
						<div style="width: 100%; height: 10px; background: var(--border-color); border-radius: 5px; overflow: hidden; display: flex; margin-bottom: 14px;">
							${bar_segments}
						</div>

						<!-- KPI Cards -->
						<div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px;">
							${kpi_cards}
						</div>
					</div>
				`;

					let target = frm.layout.wrapper.find(".form-tabs-list");
					if (target.length === 0) {
						target = frm.layout.wrapper.find(".form-section").first();
					}

					frm.layout.wrapper.find(".icd-manifest-dashboard").remove();
					target.before(html);
				}
			}
		});
	}
});
