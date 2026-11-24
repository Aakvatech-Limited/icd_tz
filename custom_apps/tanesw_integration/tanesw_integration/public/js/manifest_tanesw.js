// TANeSW additions to icd_tz's Manifest form (tanesw_integration hooks: doctype_js). icd_tz's own script is untouched:
// this adds a "Diverted" card to its Container Reception Progress row, a line naming where the boxes went with a link
// to the TANeSW Diverted Containers report, a "Check TANeSW Now" button, and a warning before port expense orders
// when boxes on this Manifest are no longer ours.
frappe.ui.form.on("Manifest", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.mrn) return;
		frappe.call({
			method: "tanesw_integration.port_charge_check.precheck",
			args: { manifest: frm.doc.name },
			callback: (r) => {
				const res = r.message || {};
				if (!res.enabled || !(res.gone || []).length) return;
				const boxes = res.gone.map((g) => `${frappe.utils.escape_html(g.container_no)} (${frappe.utils.escape_html(g.went_to)})`).join(", ");
				frm.set_intro(__("{0} box(es) on this Manifest are no longer ours: {1}. Leave them out of port expense orders; {2}",
					[res.gone.length, boxes, res.blocking ? __("submitting an order or invoice with them is stopped.") : __("submitting one with them shows a warning.")])
					+ (res.note ? " " + frappe.utils.escape_html(res.note) : ""), "red");
			},
		});
		frappe.call({
			method: "tanesw_integration.manifest_sync.manifest_summary",
			args: { manifest: frm.doc.name },
			callback: (r) => {
				const s = r.message || {};
				if (!s.enabled) return;
				frm._tanesw_summary = s;
				tanesw_manifest.render(frm, s, 0);
				tanesw_manifest.button(frm);
			},
		});
	},
});

const tanesw_manifest = {
	card(s) {
		const tip = __("Boxes that left our allocation in TANeSW after this vessel was allocated to us");
		return `<div class="tanesw-diverted-card" title="${tip}" style="flex: 1; min-width: 90px; padding: 10px 14px; border-radius: 8px; background: var(--card-bg); border-left: 3px solid #8e44ad; text-align: center; cursor: pointer;">
			<div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #8e44ad; margin-bottom: 4px;">${__("Diverted")}</div>
			<div style="font-size: 20px; font-weight: 700; color: var(--text-color);">${s.diverted}</div>
		</div>`;
	},

	line(s) {
		const places = Object.entries(s.places || {})
			.sort((a, b) => b[1] - a[1])
			.map(([p, n]) => `${frappe.utils.escape_html(p)} ${n}`)
			.join(", ");
		const bits = [];
		if (s.diverted) bits.push(__("{0} diverted ({1})", [s.diverted, places]));
		if (s.added) bits.push(__("{0} added after upload", [s.added]));
		if (s.needs_action)
			bits.push(`<span style="color: var(--red-600)">${__("{0} diverted with a Movement Order or Container already made: check with Ops", [s.needs_action])}</span>`);
		const text = bits.length ? bits.join(" · ") : __("No changes in TANeSW since this vessel was allocated to us");
		const when = s.last_run ? __("last checked {0}", [frappe.datetime.prettyDate(s.last_run)]) : "";
		return `<div class="tanesw-manifest-line" style="font-size: 12px; color: var(--text-muted); margin: -4px 0 14px;">
			<b>${__("TANeSW")}:</b> ${text} · <a class="tanesw-open-report">${__("View boxes")}</a>${when ? " · " + when : ""}
		</div>`;
	},

	render(frm, s, tries) {
		const wrap = frm.layout.wrapper;
		wrap.find(".tanesw-diverted-card, .tanesw-manifest-line, .tanesw-manifest-own").remove();
		const dash = wrap.find(".icd-manifest-dashboard");
		if (!dash.length) {
			// icd_tz draws its dashboard after its own server call (submitted Manifests only): wait for it a little
			if (frm.doc.docstatus === 1 && tries < 20) {
				setTimeout(() => tanesw_manifest.render(frm, s, tries + 1), 200);
				return;
			}
			// no icd_tz dashboard (Draft): our own small block
			const own = $(`<div class="tanesw-manifest-own" style="display: flex; gap: 10px; margin-bottom: 8px; max-width: 220px;">${tanesw_manifest.card(s)}</div>`);
			let target = wrap.find(".form-tabs-list");
			if (!target.length) target = wrap.find(".form-section").first();
			target.before(own);
			own.after(tanesw_manifest.line(s));
		} else {
			const row = dash.find('div[style*="flex-wrap"]').first();
			(row.length ? row : dash).append(tanesw_manifest.card(s));
			dash.append(tanesw_manifest.line(s));
		}
		const open = () => frappe.set_route("query-report", "TANeSW Diverted Containers", { mrn: s.mrn, from_date: "2020-01-01" });
		wrap.find(".tanesw-diverted-card, .tanesw-open-report").on("click", open);
		// icd_tz redraws its dashboard on every refresh and drops our card with it: put it back once
		if (!frm._tanesw_watch && dash.length) {
			frm._tanesw_watch = true;
			const obs = new MutationObserver(() => {
				const d = frm.layout.wrapper.find(".icd-manifest-dashboard");
				if (d.length && !d.find(".tanesw-diverted-card").length && frm._tanesw_summary)
					tanesw_manifest.render(frm, frm._tanesw_summary, 0);
			});
			obs.observe(frm.layout.wrapper.get(0), { childList: true, subtree: true });
		}
	},

	button(frm) {
		frm.add_custom_button(__("Check TANeSW Now"), () => {
			frappe.call({
				method: "tanesw_integration.manifest_sync.check_vessel_now",
				args: { manifest: frm.doc.name },
				freeze: true,
				freeze_message: __("Reading this vessel's manifest from TANeSW..."),
				callback: (r) => {
					const x = r.message || {};
					frappe.show_alert({
						message: __("TANeSW checked: {0} removed, {1} added, {2} taken off, {3} put on the Manifest", [
							x.removed || 0, x.added || 0, x.taken_off || 0, x.put_on || 0]),
						indicator: "green",
					});
					frm.reload_doc();
				},
			});
		}, __("TANeSW"));
	},
};
