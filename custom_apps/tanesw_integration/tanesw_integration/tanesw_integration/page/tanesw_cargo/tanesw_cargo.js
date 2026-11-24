// Cargo Mgmt — desk mirror of the TANeSW portal's Cargo Management menu.
// Routes: /app/tanesw-cargo/<screenId>[/<key>[/<key2>]]
(() => {
	const PAGE = "tanesw-cargo";
	const CODE_GROUPS = ["COM0023", "CGM0066", "CGM0055", "CGM0009", "CGM0002", "CGM0036", "CGM0010", "CGM0017", "CGM0021", "COM0007", "COM0005"];
	const MENU = [
		{ group: "Manifest Management", subs: [{ sub: "Sea Import Manifest", items: ["cgme0101025q"] }] },
		{ group: "Transfer", subs: [
			{ sub: "ICD Transfer", items: ["cgme0301001q", "cgme0301002q", "cgme0301011q", "cgme0301021q"] },
			{ sub: "Simple Transfer Declaration", items: ["cgme0302001q", "cgme0302011q", "cgme0302021q"] },
		] },
		{ group: "Warehouse", subs: [
			{ sub: "Warehouse In/Out", items: ["cgme0401001q", "cgme0401008q"] },
			{ sub: "Stripping", items: ["cgme0406001q", "cgme0406002q", "cgme0406008q", "cgme0406012q"] },
		] },
		{ group: "Tracking", subs: [{ sub: "Cargo Tracking", items: ["cgme0910001q"] }] },
	];
	const SCREENS = {
		cgme0101025q: { title: "Manifest Information", ui: "UI-CGME-0101-025Q" },
		cgme0101026q: { title: "Sea Import MRN Details", ui: "UI-CGME-0101-026Q", parent: "cgme0101025q" },
		cgme0101027q: { title: "Master BL Information", ui: "UI-CGME-0101-027Q", parent: "cgme0101025q" },
		cgme0301001q: { title: "Expected ICD Transfer List", ui: "UI-CGME-0301-001Q" },
		cgme0301002q: { title: "ICD Transfer Declaration List", ui: "UI-CGME-0301-002Q" },
		cgme0301005s: { title: "ICD Transfer Declaration Registration", ui: "UI-CGME-0301-005S", parent: "cgme0301002q" },
		cgme0301011q: { title: "ICD Transfer Declaration Amendment List", ui: "UI-CGME-0301-011Q" },
		cgme0301012s: { title: "ICD Transfer Declaration Amendment Registration", ui: "UI-CGME-0301-012S", parent: "cgme0301011q" },
		cgme0301021q: { title: "ICD Transfer Declaration Cancellation List", ui: "UI-CGME-0301-021Q" },
		cgme0301022s: { title: "ICD Transfer Cancellation Registration", ui: "UI-CGME-0301-022S", parent: "cgme0301021q" },
	};
	const CRUMB = {};
	MENU.forEach(m => m.subs.forEach(sb => sb.items.forEach(id => { CRUMB[id] = ["Cargo Mgmt.", m.group, sb.sub]; })));
	const HANDLERS = {};
	const DEFAULT_SCREEN = "cgme0301002q";
	const EDITABLE = ["", "A01", "A05", "D09"];
	const DCL_STATUS = ["A01", "A04", "D01", "A05", "D06", "D08", "D09", "G07"];
	const AMD_STATUS = ["A01", "A04", "D01", "A05", "D06", "D08", "D09", "D15"];

	let U, T, esc, S;
	const st = { $main: null, $nav: null, last_key: null, store: {}, pending: {}, ready: null };

	frappe.pages[PAGE].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Cargo Management"), single_column: true });
		st.ready = frappe.require(["/assets/tanesw_integration/js/tanesw_ui.js", "/assets/tanesw_integration/css/tanesw_ui.css", "/assets/tanesw_integration/js/tanesw_nav.js", "/assets/tanesw_integration/js/tanesw_cargo_more.js"]).then(() => {
			T = window.tanesw_ui; esc = T.esc;
			U = T.make("tanesw_integration.cargo."); S = U.S;
			// One menu for all TANeSW screens (Cargo, Joint Inspection, records, settings) — see tanesw_nav.js
			const $root = $(`<div class="ji-page"><nav class="ji-nav" aria-label="${esc(__("TANeSW menu"))}"></nav><div class="ji-col"><div class="tn-status-host"></div><div class="ji-main"></div></div></div>`).appendTo(page.body);
			st.$main = $root.find(".ji-main");
			st.$status = $root.find(".tn-status-host");
			st.$nav = $root.find(".ji-nav");
			st.nav = window.tanesw_nav.mount(st.$nav);
			st.$main.on("click", ".ji-stat[data-doc]", function (e) { e.preventDefault(); status_popup($(this).attr("data-doc"), $(this).attr("data-cd")); });
			return Promise.all([
				U.call("tanesw_integration.joint_inspection.context").then(c => { S.ctx = c || {}; st.$status.html(window.tanesw_nav.status_bar(S.ctx)); }),
				U.call("tanesw_integration.joint_inspection.codes", { comn_cds: CODE_GROUPS }).then(c => (S.codes = c || {})),
				U.call("tanesw_integration.joint_inspection.parties").then(p => (S.parties = p || S.parties)).catch(() => {}),
			]);
		});
		frappe.router && frappe.router.on && frappe.router.on("change", () => { if (frappe.get_route()[0] === PAGE) render(); });
	};
	// Re-read TANeSW Settings each time the page is shown, so switching "Enable Write Operations"
	// takes effect without a browser reload (the buttons are drawn from S.ctx.write_enabled).
	frappe.pages[PAGE].on_page_show = () => {
		render();
		st.ready && st.ready.then(() => U.call("tanesw_integration.joint_inspection.context").then(c => {
			const changed = !!(c && c.write_enabled) !== !!S.ctx.write_enabled;
			S.ctx = c || S.ctx;
			st.$status && st.$status.html(window.tanesw_nav.status_bar(S.ctx));
			if (changed) { st.last_key = null; render(); }
		}));
	};

	function go(screen, ...args) { frappe.set_route(PAGE, screen, ...args.filter(a => a != null && a !== "")); }

	function render() {
		if (!st.ready) return;
		st.ready.then(() => {
			const route = frappe.get_route();
			const screen = SCREENS[route[1]] ? route[1] : DEFAULT_SCREEN;
			const args = route.slice(2).map(decodeURIComponent);
			const key = `${screen}/${args.join("/")}`;
			if (key === st.last_key && st.$main.children().length) return;
			st.last_key = key;
			const meta = SCREENS[screen];
			let menu_id = screen;
			while (SCREENS[menu_id] && SCREENS[menu_id].parent) menu_id = SCREENS[menu_id].parent;  // bulk 006S -> 005Q -> 001Q
			st.nav.set_active(PAGE, menu_id);
			const crumb = (CRUMB[menu_id] || ["Cargo Mgmt."]).concat([SCREENS[menu_id].title]);
			st.$main.html(`<div class="ji-title-row"><h4 class="ji-title">${esc(__(meta.title))} (${meta.ui})</h4>
				<div class="ji-crumb">${crumb.slice(0, -1).map(c => esc(__(c))).join(" / ")} / <span>${esc(__(crumb.slice(-1)[0]))}</span></div></div>
				<div class="ji-body"></div>`);
			const $body = st.$main.find(".ji-body");
			HANDLERS[screen]($body, ...args);
		}).catch(() => st.$main && st.$main.html(`<div class="ji-card text-danger">${esc(__("Could not reach TANeSW. Check TANeSW User Account and Settings."))}</div>`));
	}

	// ------------------------------------------------------------ shared bits
	const fd = v => esc(T.fmt_date(v));
	const fdt = v => esc(T.fmt_dt(v));
	const num = v => T.fmt_num(v);
	const period = r => (r.trsfStrtDt || r.trsfEndDt) ? `${fd(r.trsfStrtDt)} ~ ${fd(r.trsfEndDt)}` : esc(r.trsfPridDt || r.trsfPirdDt || "");
	// status cell; with a document number it opens the processing-status popup (portal dclrDtlPpup)
	const DOC_CD = { CDD: "edoc_cgm0065", CDA: "edoc_cgm0066", CDC: "edoc_cgm0067", STD: "edoc_cgm0068", STA: "edoc_cgm0069",
		STC: "edoc_cgm0070", CRI: "edoc_cgm0076", CRO: "edoc_cgm0084", SRR: "edoc_cgm0086", SRA: "edoc_cgm0087", SRC: "edoc_cgm0088" };
	const status = (c, dt, doc, kind) => {
		if (!c) return "";
		// Portal format: "APPROVED" with "[dd/mm/yyyy hh:mm]" underneath (name only, no code).
		const name = (S.codes.COM0023 || {})[c];
		const inner = `${name ? esc(name) : `[${esc(c)}]`}${dt ? `<br><small>[${fdt(dt)}]</small>` : ""}`;
		return doc && kind && c !== "A01" ? `<a class="ji-link ji-stat" data-doc="${esc(doc)}" data-cd="${DOC_CD[kind]}">${inner}</a>` : `<span class="ji-status">${inner}</span>`;
	};

	function status_popup(doc, cd) {
		const d = U.modal("Processing Status Details", `<div class="ji-h"></div><div class="ji-dt mt-2"></div>`);
		const $h = d.$body.find(".ji-h"), $dt = d.$body.find(".ji-dt");
		U.loading($h, 5);
		U.call("declaration_status", { doc_sbmt_no: doc, dcla_doc_cd: cd }).then(r => {
			const show_detail = x => x && $dt.html(U.form_grid([
				["Customs", esc(x.cstmNm)], ["Declaration Date", esc(x.dclrPrcssDtm)],
				["Document", `${esc(x.dclaDocCd || "")} ${esc(x.docNm || "")}`], ["Processing Status", esc(x.prcssStatCdNm)],
				["Business Status", esc(x.docPrcssStatCdNm)], ["Document Submit No", esc(x.docSbmtNo)],
				["Return Reason", esc(x.rmrk), { wide: true }],
			]));
			U.grid($h, {
				rows: r.history || [], columns: [
					{ label: "Document Submit No", render: (x, i) => `<a class="ji-link" data-i="${i}">${esc(x.docSbmtNo)}</a>` },
					{ label: "Amendment Degree", render: x => esc(x.amdDgr) },
					{ label: "Processing Status", render: x => esc(x.prcssStatCdNm) },
					{ label: "Declaration Date", render: x => esc(x.dclrPrcssDtm) },
				],
				bind: ($g, rows) => $g.find("[data-i]").on("click", function () {
					const x = rows[Number($(this).attr("data-i"))];
					if (x.dclrPrcssSttsUuid) U.call("declaration_status_detail", { uuid: x.dclrPrcssSttsUuid, srno: x.prcssSrno }).then(show_detail);
				}),
			});
			if (r.notice_url) $dt.html(`<div class="ji-banner">${esc(__("TANeSW has issued the confirmation / approval notice for this declaration."))}
				<a class="btn btn-sm btn-primary ml-2" target="_blank" rel="noopener" href="${esc(r.notice_url)}">${esc(__("Open notice on TANeSW"))}</a></div>`);
			else if ((r.errors || []).length) U.grid($dt, { title: "Errors", rows: r.errors, columns: [
				{ label: "Validation Type", render: x => esc(x.valdnTpCdNm) }, { label: "Item", render: x => esc(x.valdnItmNm) },
				{ label: "Value", render: x => esc(x.valdnItmCn) }, { label: "Message", cls: "left", render: x => esc(x.errMsgCn || x.errMsgId) },
				{ label: "Notice Date", render: x => esc(x.dclrPrcssDtm) }] });
			else show_detail(r.detail);
		}).catch(() => $h.html(`<div class="text-danger">${esc(__("Could not load processing status"))}</div>`));
	}
	function print_movement(dclr_no, crn, is_bulk) {
		return U.call("icd_movement_sheet", { dclr_no, crn, is_bulk }, __("Generating movement sheet..."))
			.then(res => U.show_pdf(res, __("ICD Movement Sheet")));
	}
	// Portal masks: DCLR_NO 9-4-1-7 (10-4-1-7 when longer than 21), CRN 11-4-3.
	const mask = (v, parts) => { const r = String(v || "").replace(/-/g, ""); let i = 0; const out = [];
		for (const n of parts) { if (i >= r.length) break; out.push(r.slice(i, i + n)); i += n; } if (i < r.length) out.push(r.slice(i)); return esc(out.join("-")); };
	const dclr_fmt = v => { const r = String(v || "").replace(/-/g, ""); return r.length >= 18 ? mask(r, r.length <= 21 ? [9, 4, 1, 7] : [10, 4, 1, 7]) : esc(v); };
	const crn_fmt = v => { const r = String(v || "").replace(/-/g, ""); return r.length > 11 ? mask(r, [11, 4, 3]) : esc(v); };
	const wh_cell = (c, n) => U.wh(c, n);

	function search_card(fields_html, extra_buttons = "") {
		return $(`<div class="ji-card">${fields_html}
			<div class="ji-actions"><button class="btn btn-sm ji-reset">${esc(__("Reset"))}</button>
			<div class="right">${extra_buttons}<button class="btn btn-sm btn-primary ji-search">${esc(__("Search"))}</button></div></div></div>`);
	}

	function list_screen($body, sid, defaults, fields, columns, method, opts = {}) {
		const s = st.store[sid] || (st.store[sid] = { form: defaults(), page: 0, size: 10 });
		const $search = search_card(U.form_grid(fields(s.form))).appendTo($body);
		U.bind_range($search); U.bind_checks($search);
		const $grid = $(`<div class="ji-card"></div>`).appendTo($body);
		let last_rows = [];
		function load(page) {
			const form = U.read_form($search);
			// Date ranges: both ends required and end >= start, as the portal validates (msg.cgm.00034).
			const pairs = new Set($search.find(".ji-range-btn").map(function () { return `${$(this).attr("data-s")}|${$(this).attr("data-e")}`; }).get());
			for (const p of pairs) {
				const [a, b] = p.split("|");
				if (!form[a] || !form[b]) return frappe.show_alert({ message: __("Enter both dates of the date range"), indicator: "orange" });
				if (form[b] < form[a]) return frappe.show_alert({ message: __("The end date must be on or after the start date"), indicator: "orange" });
			}
			if (opts.validate && !opts.validate(form)) return;
			Object.assign(s, { form, page: page || 0 });
			U.loading($grid, columns.length + 2);
			U.call(method, { ...(opts.args ? opts.args(form) : form), page: s.page, size: s.size }).then(res => {
				last_rows = res.content || [];
				U.grid($grid, {
					columns, rows: last_rows, meta: res.page, size: s.size, select: opts.select,
					toolbar: `<div class="ji-actions" style="margin:0 0 8px"><button class="btn btn-xs btn-default ji-csv">${esc(__("Excel Download"))}</button><div class="right">${opts.toolbar || ""}</div></div>`,
					onPage: p => load(p), onSize: z => { s.size = z; load(0); },
					bind: ($h, rows) => {
						$h.find(".ji-csv").on("click", () => U.export_csv(SCREENS[sid].title, columns, rows));
						opts.bind && opts.bind($h, rows, () => load(s.page), res);
					},
				});
			}).catch(() => U.grid($grid, { columns, rows: [] }));
		}
		$search.find(".ji-search").on("click", () => load(0));
		$search.find(".ji-reset").on("click", () => { delete st.store[sid]; st.last_key = null; render(); });
		if (opts.autoload !== false) load(s.page);
	}

	Object.assign(HANDLERS, {
		cgme0101025q: (...a) => s_manifest_info(...a), cgme0101026q: (...a) => s_mrn_detail(...a), cgme0101027q: (...a) => s_mbl_info(...a),
		cgme0301001q: (...a) => s_icd_expected(...a), cgme0301002q: (...a) => s_icd_list(...a), cgme0301005s: (...a) => s_icd_decl(...a),
		cgme0301011q: (...a) => s_amd_list(...a), cgme0301012s: (...a) => s_amd_decl(...a),
		cgme0301021q: (...a) => s_cncl_list(...a), cgme0301022s: (...a) => s_cncl_decl(...a),
	});
	// Extension point used by tanesw_cargo_more.js (Simple Transfer, Carry-In/Out, Stripping, Tracking)
	window.tanesw_cargo = {
		SCREENS, HANDLERS, EDITABLE, st,
		ctx: () => ({ U, T, esc, S }),
		go, render, list_screen, search_card, status, status_popup, period, dclr_fmt, crn_fmt, wh_cell, wh_list, fd, fdt, num,
		vehicle_dialog: (...a) => vehicle_dialog(...a), VHCL_COLS: () => VHCL_COLS, CNTR_COLS: () => CNTR_COLS, penalty_rows: (...a) => penalty_rows(...a),
	};

	// ============================================================ Manifest
	const our_code = () => (S.ctx && S.ctx.warehouse_code) || "";
	function s_manifest_info($body) {
		list_screen($body, "cgme0101025q",
			() => ({ srch_dt_from: T.today(), srch_dt_to: T.add_days(T.today(), 7), srch_tp: "mrn", our_only: "ours" }),
			f => [
				["Date of Arrival", U.date_range("srch_dt_from", "srch_dt_to", f), { wide: true, req: true }],
				[`<select class="form-control" data-f="srch_tp" style="height:26px;font-size:12px">${[["mrn", "MRN"], ["vsslNm", "Vessel Name"], ["tpaUid", "TPA/ZPC UID"]]
					.map(([v, l]) => `<option value="${v}" ${f.srch_tp === v ? "selected" : ""}>${esc(__(l))}</option>`).join("")}</select>`,
					`<input class="form-control" data-f="srch_tp_cn" value="${esc(f.srch_tp_cn)}" style="text-transform:uppercase">`, { wide: true }],
				["Show", `<select class="form-control" data-f="our_only" style="max-width:260px">
					${[["ours", __("Our Cargo"), __("Vessels with any B/L delivered to {0} (containers, bulk or loose), including vessels not yet arrived", [our_code()])],
						["0", __("All Port Manifests"), __("Every manifest arriving in these dates, for all ICDs, as the TANeSW portal shows")]].map(([v, l, tip]) =>
						`<option value="${v}" title="${esc(tip)}" ${((f.our_only || "ours") === "0" ? "0" : "ours") === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`, { wide: true }],
			],
			[
				{ label: "MRN", render: r => `<a class="ji-link" data-mrn="${esc(r.mrn)}">${esc(r.mrn)}</a>` },
				{ label: "Our B/Ls", cls: "num", render: r => r.our_bl_count == null ? "" : num(r.our_bl_count) },
				{ label: "Our Containers", cls: "num", render: r => r.our_cntr_count == null ? "" : num(r.our_cntr_count) },
				{ label: "Arrived?", render: r => r.our_bl_count == null ? "" : (fd(r.actlArvlDt || r.arvlXptdDt) && String(T.iso_date(r.actlArvlDt || r.arvlXptdDt)) > T.today() ? `<span class="ji-muted">${esc(__("Not yet"))}</span>` : esc(__("Yes"))) },
				{ label: "Target", cls: "num", render: r => r.our_trgt_count == null ? "" : num(r.our_trgt_count) },
				{ label: "Declared", cls: "num", render: r => r.our_dclr_count == null ? "" : num(r.our_dclr_count) },
				{ label: "Vessel Name", cls: "left", render: r => esc(r.vsslNm) },
				{ label: "TPA/ZPC UID", render: r => esc(r.tpaUid) },
				{ label: "Carrier", cls: "left", render: r => U.pair(r.carrCd, r.carrNm) },
				{ label: "Date of Arrival", render: r => fd(r.actlArvlDt || r.arvlXptdDt) },
				{ label: "S/A", cls: "num", render: r => num(r.shagCnt) },
				{ label: "F/F", cls: "num", render: r => num(r.fwdrCnt) },
				{ label: "Simple MBL", cls: "num", render: r => num(r.mblSCnt) },
				{ label: "Consol MBL", cls: "num", render: r => num(r.mblCCnt) },
				{ label: "HBL", cls: "num", render: r => num(r.hblCnt) },
				{ label: "Number of Containers", cls: "num", render: r => num(r.cntrCnt) },
			],
			"manifest_info_list",
			{ bind: ($h, rows, reload, res) => {
				// Manifests whose B/L list TANeSW did not return are UNVERIFIED: not in the list above (they may
				// belong to another ICD) and not silently hidden either.
				const unv = (res && res.unverified) || [];
				if (unv.length) $h.prepend(`<div class="ji-banner" style="border-left:3px solid var(--orange-500,#f59f00)">
					<b>${esc(__("List incomplete: {0} of {1} manifests in this window could not be checked against TANeSW and are not shown.", [unv.length, res.scanned]))}</b>
					${esc(__("They may or may not carry cargo for {0}.", [our_code()]))}
					<button class="btn btn-xs btn-default ji-retry" style="margin-left:6px">${esc(__("Check again"))}</button>
					<div style="margin-top:6px">${unv.map(u => `<a class="ji-link" data-mrn="${esc(u.mrn)}" title="${esc(__("Open the MRN to read its B/Ls directly"))}">${esc(u.mrn)}</a> <span class="ji-muted">${esc(u.vsslNm || "")} ${fd(u.arvlDt)}</span>`).join(" &nbsp;·&nbsp; ")}</div></div>`);
				$h.find(".ji-retry").on("click", reload);
				$h.find("[data-mrn]").on("click", function () { go("cgme0101026q", $(this).attr("data-mrn")); });
			} });
	}

	function s_mrn_detail($body, mrn) {
		const $sum = $(`<div class="ji-card"><div class="ji-muted">${esc(__("Loading..."))}</div></div>`).appendTo($body);
		const $mbl = $(`<div class="ji-card"></div>`).appendTo($body);
		$(`<div class="ji-actions"><button class="btn btn-sm btn-default">${esc(__("List"))}</button></div>`).appendTo($body)
			.find("button").on("click", () => go("cgme0101025q"));
		let MRN_HDR = null;
		U.call("mrn_detail", { mrn }).then(m => {
			MRN_HDR = m;
			$sum.html(`<div class="ji-card-title">${esc(__("Summary"))}</div>` + U.form_grid([
				["MRN", esc(m.mrn)], ["Voyage", esc(m.vygNo)],
				["Call Sign", esc(m.csgn)], ["Nationality of Vessel", U.pair(m.natCd, m.natNm)],
				["Carrier", esc(m.carrNm || m.carrCd)], ["Vessel Name", esc(m.vsslNm)],
				["Port of Departure", U.pair(m.dptrPortCd, m.dptrPortNm)], ["Port of Discharge", U.pair(m.dscgPortCd, m.dscgPortNm)],
				["Date of Submission", fd(m.sbmtDt)], ["Arrival Date", fd(m.actlArvlDt || m.arvlXptdDt)],
				["Date of Departure", fd(m.dptrDt)], ["Arrival in ballast", esc(m.arvlBlstYn || "")],
				["Terminal No.", wh_cell(m.trmnlCd, m.trmnlNm)], ["Terminal Operator", U.pair(m.trmnlOptrCd, m.trmnlOptrNm)],
			]));
		}).catch(() => $sum.html(`<div class="text-danger">${esc(__("Failed to load MRN"))}</div>`));
		const s = { page: 0, size: 10, our: (st.store.cgme0101025q?.form?.our_only ?? "ours") !== "0" };
		const columns = [
			{ label: "MSN", render: r => esc(r.msn) },
			{ label: "M B/L No", render: r => `<a class="ji-link" data-mbl="${esc(r.mblNo)}">${esc(r.mblNo)}</a>` },
			{ label: "Cargo Type", render: r => U.code("CGM0002", r.cagClsfCd) },  // IM / TR / EX ...
			{ label: "B/L Type", render: r => U.code("CGM0009", r.blTpCd) },  // S / C ...
			{ label: "Port of Loading", render: r => U.pair(r.loadPortCd, r.loadPortNm) },
			{ label: "Shipping Agent", cls: "left", render: r => U.pair(r.shagCd, r.shagNm) },
			{ label: "Delivery Place", cls: "left", render: r => wh_cell(r.dlvrPlcCd, r.dlvrPlcNm) },
			{ label: "Package", cls: "num", render: r => `${num(r.blPckgNo)} ${esc(r.pckgUtCd || "")}` },
			{ label: "Weight", cls: "num", render: r => `${num(r.blGwght)} ${esc(r.gwghtUtCd || "")}` },
			{ label: "Number of Container", cls: "num", render: r => num(r.cntrCnt) },
			{ label: "Total HBL", cls: "num", render: r => num(r.hblCnt) },
			{ label: "Audit Status", render: r => U.code("CGM0055", r.blAudtStatCd) },
		];
		function load(page) {
			s.page = page;
			U.loading($mbl, columns.length + 1);
			U.call("mrn_mbl_list", { mrn, page, size: s.size, our_only: s.our ? 1 : 0 }).then(res => U.grid($mbl, {
				title: "Master B/L List", columns, rows: res.content, meta: res.page, size: s.size,
				toolbar: `<div class="ji-actions" style="margin:0 0 8px"><div><button class="btn btn-xs btn-default ji-xls" title="${esc(__("Official TANeSW workbook — always the whole manifest"))}">${esc(__("Excel Download"))}</button>
					<button class="btn btn-xs btn-default ji-mpdf" title="${esc(__("Cargo Manifest Report Inward of Vessel (PDF)"))}">${esc(__("Manifest PDF"))}</button></div>
					<div class="right"><label class="mb-0"><input type="checkbox" class="ji-our" ${s.our ? "checked" : ""}> ${esc(__("Only B/Ls delivered to {0}", [our_code()]))}</label></div></div>`,
				onPage: load, onSize: z => { s.size = z; load(0); },
				bind: $h => {
					$h.find("[data-mbl]").on("click", function () { go("cgme0101027q", mrn, $(this).attr("data-mbl")); });
					$h.find(".ji-our").on("change", function () { s.our = this.checked; load(0); });
					$h.find(".ji-xls").on("click", () => U.call("manifest_excel", { mrn, header: MRN_HDR }, __("Downloading manifest Excel from TANeSW...")).then(U.download_b64));
					$h.find(".ji-mpdf").on("click", () => U.call("manifest_report", { mrn }, __("Generating manifest...")).then(res => U.show_pdf(res, __("Cargo Manifest {0}", [mrn]))));
				},
			}));
		}
		load(0);
	}

	const MBL_LABELS = [
		["mrn", "MRN"], ["crn", "Cargo Ref No"], ["prcssStatCd", "Status"], ["mblNo", "M B/L No"], ["blTpCd", "B/L Type"],
		["cagClsfCd", "Cargo Type"], ["loadPortCd", "Port of Loading"], ["dstnPlcCd", "Place of Destination"],
		["dlvrPlcCd", "Place of Delivery"], ["shagCd", "Shipping Agent"], ["exppnNm", "Exporter"], ["cnsiNm", "Consignee"],
		["ntfyNm", "Notify"], ["godsDesc", "Description of Goods"], ["blPckgNo", "Number of Packages"], ["blGwght", "Gross Weight"],
		["blNwght", "Net Weight"], ["blVol", "Gross Volume"], ["pckgTpCd", "Packing Type"], ["oilTpCd", "Oil Type"],
		["invcVal", "Invoice Value"], ["frghChrg", "Freight Charge"], ["imdgCd", "IMDG Code"], ["cntrCnt", "Number of Container"],
		["shppngMrk", "Shipping Mark"],
	];

	function s_mbl_info($body, mrn, mbl) {
		const $d = $(`<div class="ji-card"><div class="ji-muted">${esc(__("Loading..."))}</div></div>`).appendTo($body);
		const $tabs = $(`<div class="ji-card"></div>`).appendTo($body);
		$(`<div class="ji-actions"><button class="btn btn-sm btn-default">${esc(__("List"))}</button></div>`).appendTo($body)
			.find("button").on("click", () => go("cgme0101026q", mrn));
		U.call("mbl_info", { mrn, mbl_no: mbl }).then(b => {
			const known = new Set(MBL_LABELS.map(x => x[0]));
			const val = (k) => {
				const v = b[k];
				if (k === "prcssStatCd") return U.code("COM0023", v) + (b.prcssDtm ? ` [${fd(b.prcssDtm)}]` : "");
				if (k === "cagClsfCd") return U.code("CGM0002", v);
				if (k === "blTpCd") return U.code("CGM0009", v);
				if (k === "dlvrPlcCd") return wh_cell(v, b.dlvrPlcNm);
				if (k === "shagCd") return U.pair(v, b.shagNm);
				if (k === "loadPortCd" || k === "dstnPlcCd") return U.pair(v, b[k.replace("Cd", "Nm")]);
				if (k === "blPckgNo") return `${num(v)} ${esc(b.pckgUtCd || "")}`;
				if (k === "blGwght" || k === "blNwght") return `${num(v)} ${esc(b.gwghtUtCd || b.wghtUtCd || "")}`;
				if (k === "blVol") return `${num(v)} ${esc(b.volUtCd || "")}`;
				return esc(v);
			};
			const extra = Object.keys(b).filter(k => !known.has(k) && b[k] != null && b[k] !== "" && typeof b[k] !== "object");
			$d.html(`<div class="ji-card-title">${esc(__("Master B/L Detail"))}</div>` +
				U.form_grid(MBL_LABELS.map(([k, l]) => [l, val(k), ["godsDesc", "shppngMrk"].includes(k) ? { wide: true } : {}])) +
				(extra.length ? `<details class="mt-2"><summary class="ji-muted">${esc(__("All other TANeSW fields"))} (${extra.length})</summary>
					${U.form_grid(extra.map(k => [k, esc(b[k])]))}</details>` : ""));
			const cntrs = b.cntrList || b.impMnfsCntrList || b.cntrRList || [];
			const reffs = b.reffList || b.mblReffList || b.reffRList || [];
			$tabs.html(`<div class="ji-tabs"><a data-t="r">${esc(__("Reference Document Information"))}</a><a class="active" data-t="c">${esc(__("Cargo Information"))}</a></div><div class="ji-tb"></div>`);
			const show = t => {
				$tabs.find(".ji-tabs a").removeClass("active").filter(`[data-t="${t}"]`).addClass("active");
				const $tb = $tabs.find(".ji-tb");
				t === "c" ? U.grid($tb, { rows: cntrs, columns: [
					{ label: "Number of Container", render: r => esc(r.cntrNo) },
					{ label: "Type", render: r => U.code("CGM0021", r.loadTpCd) },
					{ label: "Size", render: r => U.code("CGM0010", r.cntrSizeCd) },
					{ label: "Seal No#1", render: r => esc(r.sealNo1) }, { label: "Seal No#2", render: r => esc(r.sealNo2) },
					{ label: "Seal No#3", render: r => esc(r.sealNo3) },
					{ label: "Freight Indicator", render: r => U.code("CGM0017", r.frghIdcrCd) },
					{ label: "Package / Weight", cls: "num", render: r => `${num(r.cntrPckgNo)} ${esc(r.cntrPckgUtCd || "")} / ${num(r.cntrWght)} ${esc(r.cntrWghtUtCd || r.wghtUtCd || "")}` },
					{ label: "Reefer Plug", render: r => esc(r.reffPlugYn) },
				] }) : U.grid($tb, { rows: reffs, columns: [
					{ label: "Reference Type", render: r => esc(r.reffTpCd) },
					{ label: "Reference Document No", render: r => esc(r.reffNo) },
					{ label: "Number of Packages", cls: "num", render: r => num(r.reffPckgNo) },
					{ label: "Weight", cls: "num", render: r => num(r.reffWght) },
				] });
			};
			$tabs.find(".ji-tabs a").on("click", function () { show($(this).attr("data-t")); });
			show("c");
		}).catch(() => $d.html(`<div class="text-danger">${esc(__("Failed to load B/L"))}</div>`));
	}

	// ============================================================ ICD Transfer lists
	const XPTD_COLS = [
		{ label: "Vessel Name", cls: "left", render: r => esc(r.vsslNm) },
		{ label: "Voyage No", render: r => esc(r.vygNo) },
		{ label: "MRN", render: r => esc(r.mrn) },
		{ label: "CRN", render: r => crn_fmt(r.crn) },
		{ label: "Arrival Date", render: r => fd(r.arvlDt) },
		{ label: "Carrier", cls: "left", render: r => U.pair(r.carrCd, r.carrNm) },
		{ label: "Number of M B/L", cls: "num", render: r => esc(r.mblCnt) },
		{ label: "Containers: Total", cls: "num", render: r => esc(r.totCnt) },
		{ label: "Target", cls: "num", render: r => esc(r.trgtCnt) },
		{ label: "Declaration", cls: "num", render: r => esc(r.dclrCnt) },
	];

	function s_icd_expected($body) {
		list_screen($body, "cgme0301001q",
			() => ({ srch_arvl_dt_from: T.add_months(T.today(), -1), srch_arvl_dt_to: T.today(), srch_cag_tp: "C" }),
			f => [
				["Arrival Date", U.date_range("srch_arvl_dt_from", "srch_arvl_dt_to", f, ["-6M", "-3M", "-1M", "-1W", "T"]), { req: true }],
				["Cargo Type", `<label class="mr-3"><input type="radio" name="x-cag" data-f="srch_cag_tp" value="C" ${f.srch_cag_tp !== "B" ? "checked" : ""}> ${esc(__("Container"))}</label>
					<label><input type="radio" name="x-cag" data-f="srch_cag_tp" value="B" ${f.srch_cag_tp === "B" ? "checked" : ""}> ${esc(__("Bulk"))}</label>`, { req: true }],
				["MRN", `<input class="form-control" data-f="srch_mrn" value="${esc(f.srch_mrn)}" style="text-transform:uppercase">`],
				["Vessel Name", `<input class="form-control" data-f="srch_vssl_nm" value="${esc(f.srch_vssl_nm)}">`],
			],
			XPTD_COLS, "icd_expected_list");
	}

	function s_icd_list($body) {
		const statuses = Object.fromEntries(DCL_STATUS.map(c => [c, (S.codes.COM0023 || {})[c] || c]));
		list_screen($body, "cgme0301002q",
			() => ({ srch_dt_tp: "rgsrDt", srch_dt_tp_from: T.add_months(T.today(), -1), srch_dt_tp_to: T.today(), prcss_stat_cds: DCL_STATUS }),
			f => [
				[`<select class="form-control" data-f="srch_dt_tp" style="height:26px;font-size:12px"><option value="rgsrDt" ${f.srch_dt_tp !== "sbmtDt" ? "selected" : ""}>${esc(__("Date of Register"))}</option><option value="sbmtDt" ${f.srch_dt_tp === "sbmtDt" ? "selected" : ""}>${esc(__("Date of Submission"))}</option></select>`,
					U.date_range("srch_dt_tp_from", "srch_dt_tp_to", f, ["-6M", "-3M", "-1M", "-1W", "T"]), { wide: true, req: true }],
				["Declaration No", `<input class="form-control" data-f="srch_dclr_no" value="${esc(f.srch_dclr_no)}">`],
				["Place of Departure", `<input class="form-control" list="cg-wh" data-f="srch_dptr_wrhs_cd" value="${esc(f.srch_dptr_wrhs_cd)}">${wh_list("cg-wh")}`],
				["MRN", `<input class="form-control" data-f="srch_mrn" value="${esc(f.srch_mrn)}" style="text-transform:uppercase">`],
				["Container No.", `<input class="form-control" data-f="srch_cntr_no" value="${esc(f.srch_cntr_no)}" style="text-transform:uppercase">`],
				["Status", U.checks("prcss_stat_cds", statuses, f.prcss_stat_cds), { wide: true, req: true }],
			],
			[
				{ label: "Declaration No", render: r => `<a class="ji-link" data-dclr="${esc(r.dclrNo)}">${dclr_fmt(r.dclrNo)}</a>` },
				{ label: "MRN", render: r => esc(r.mrn) },
				{ label: "Departure Place", cls: "left", render: r => wh_cell(r.dptrWrhsCd, r.dptrWrhsNm) },
				{ label: "Destination Place", cls: "left", render: r => wh_cell(r.dstnWrhsCd, r.dstnWrhsNm) },
				{ label: "Transfer Period", render: period },
				{ label: "Containers (Hand-Over)", render: r => esc(r.cntrCnt) },
				{ label: "Vehicle", render: r => esc(r.vhclCnt) },
				{ label: "Status", render: r => status(r.prcssStatCd, r.prcssDtm, r.dclrNo, "CDD") },
				{ label: "Movement Sheet", render: r => r.prcssStatCd === "D06" ? `<button class="btn btn-xs btn-default" data-mvmn="${esc(r.dclrNo)}" title="${esc(__("Print Movement Sheet"))}">${frappe.utils.icon("printer", "xs")} ${esc(__("Print"))}</button>` : "" },
			],
			"icd_declaration_list",
			{
				validate: f => (f.prcss_stat_cds || []).length ? true : (frappe.show_alert({ message: __("Select at least one status"), indicator: "orange" }), false),
				select: r => ["A01", "A05", ""].includes(r.prcssStatCd || "") && !r.sbmtDt,
				// Opening the popup only reads TANeSW; Save/Submit on the declaration stay behind "Enable Write Operations".
				toolbar: `<button class="btn btn-default btn-xs" id="cg-new">${esc(__("New Declaration"))}</button> ${U.write_btn("Delete", "btn-danger btn-xs", "cg-del")}`,
				bind: ($h, rows, reload) => {
					$h.find("[data-dclr]").on("click", function () { go("cgme0301005s", $(this).attr("data-dclr")); });
					$h.find("[data-mvmn]").on("click", function () { print_movement($(this).attr("data-mvmn")); });
					$h.find("#cg-new").on("click", () => pick_usable_cargo(row => { st.pending.decl = row; go("cgme0301005s", "new"); }));
					$h.find("#cg-del").on("click", () => {
						const sel = $h.selected();
						if (!sel.length) return frappe.show_alert({ message: __("Select declarations to delete"), indicator: "orange" });
						frappe.confirm(__("Delete {0} declaration(s)?", [sel.length]), () =>
							U.call("icd_declaration_delete_many", { dclr_nos: sel.map(r => r.dclrNo) }, __("Deleting...")).then(reload));
					});
				},
			});
	}

	function wh_list(id) {
		return `<datalist id="${id}">${Object.entries(S.parties.warehouses || {}).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</datalist>`;
	}

	// CGME-0301-003Q usable cargo popup
	function pick_usable_cargo(on_pick) {
		const f = { srch_arvl_dt_from: T.add_months(T.today(), -1), srch_arvl_dt_to: T.add_months(T.today(), 1), srch_cag_tp: "C" };
		const d = U.modal("Usable Cargo to ICD", `<div class="ji-s">${U.form_grid([
			["Arrival Date", U.date_range("srch_arvl_dt_from", "srch_arvl_dt_to", f, ["-6M", "-3M", "-1M", "-1W", "T"]), { req: true }],
			["Cargo Type", `<label class="mr-3"><input type="radio" name="u-cag" data-f="srch_cag_tp" value="C" checked> ${esc(__("Container"))}</label><label><input type="radio" name="u-cag" data-f="srch_cag_tp" value="B"> ${esc(__("Bulk"))}</label>`],
			["MRN", `<input class="form-control" data-f="srch_mrn" style="text-transform:uppercase">`],
			["Vessel Name", `<input class="form-control" data-f="srch_vssl_nm" style="text-transform:uppercase">`],
		])}<div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary ji-search">${esc(__("Search"))}</button></div></div></div><div class="ji-g mt-2"></div>`, "extra-large");
		U.bind_range(d.$body);
		const $g = d.$body.find(".ji-g");
		const load = (page = 0) => {
			U.loading($g, 11);
			U.call("icd_usable_cargo", { ...U.read_form(d.$body.find(".ji-s")), page, size: 10 }).then(res => U.grid($g, {
				rows: res.content, meta: res.page, size: 10, onPage: load, onSize: () => load(0),
				columns: [{ label: "MRN", render: (r, i) => `<a class="ji-link" data-i="${i}">${esc(r.mrn)}${r.ifDeclKey ? ` [${esc(r.ifDeclKey)}]` : ""}</a>` }].concat(XPTD_COLS.filter(c => c.label !== "MRN")),
				bind: ($h, rows) => $h.find("[data-i]").on("click", function () { d.hide(); on_pick(rows[Number($(this).attr("data-i"))]); }),
			}));
		};
		d.$body.find(".ji-search").on("click", () => load(0));
		load(0);
	}

	// ============================================================ 005S declaration
	const CNTR_COLS = [
		{ label: "Container No.", render: r => esc(r.cntrNo) },
		{ label: "Size", render: r => esc(r.cntrSizeCd) },
		{ label: "Seal No#1", render: r => esc(r.sealNo1) }, { label: "Seal No#2", render: r => esc(r.sealNo2) },
		{ label: "Seal No#3", render: r => esc(r.sealNo3) },
		{ label: "Freight Indicator", render: r => esc(r.frghIdcrCd) },
		{ label: "Package", cls: "num", render: r => `${num(r.pckgNo ?? r.cntrPckgNo)} ${esc(r.pckgUtCd || r.cntrPckgUtCd || "")}` },
		{ label: "Weight", cls: "num", render: r => `${num(r.cntrWght)} ${esc(r.cntrWghtUtCd || r.wghtUtCd || "")}` },
		{ label: "Hand-Over", render: r => esc(r.hndvYn) },
	];
	const VHCL_COLS = [
		{ label: "Driver", cls: "left", render: r => esc(r.drvrNm) },
		{ label: "License No.", render: r => esc(r.drvrLcneNo) },
		{ label: "Driving Type", render: r => U.code("CGM0066", r.drivTpCd) },
		{ label: "C45_No", render: r => r.drivTpCd === "VEHC" ? esc(r.c45No) : "" },
		{ label: "Vehicle No.", render: r => r.drivTpCd === "VEHC" ? esc(r.vhclNo) : "OWN" },
		{ label: "Trailer No.", render: r => r.drivTpCd === "VEHC" ? esc(r.trlrNo) : "" },
		{ label: "Semi Trailer", render: r => r.drivTpCd === "VEHC" ? esc(r.semiTrlrNo) : "" },
		{ label: "Horse", render: r => esc(r.horsChkYn) },
	];

	function s_icd_decl($body, dclr_no) {
		const is_new = !dclr_no || dclr_no === "new";
		const $head = $(`<div class="ji-card"><div class="ji-muted">${esc(__("Loading..."))}</div></div>`).appendTo($body);
		const $tabs = $(`<div class="ji-card"></div>`).appendTo($body);
		const $act = $(`<div class="ji-actions"></div>`).appendTo($body);
		let H = {}, C = [], V = [], dirty = false;

		const loaded = is_new
			? (st.pending.decl ? U.call("icd_base_info", { mrn: st.pending.decl.mrn }).then(b => {
				const p = st.pending.decl;
				return { mrn: p.mrn, crn: p.crn, isBulk: p.isBulk || (p.srchCagTp === "B" ? "Y" : "N"),
					dptrWrhsCd: b.dptrWrhsCd, dstnWrhsCd: b.dstnWrhsCd, cstmOfceCd: b.cstmOfceCd,
					trsfStrtDt: T.today(), trsfEndDt: T.today(), prcssStatCd: "" };
			}) : Promise.reject("no-mrn"))
			: U.call("icd_declaration", { dclr_no });
		loaded.then(d => {
			H = { ...d }; C = d.trsfIcdCntrRList || []; V = d.trsfIcdVhclRList || [];
			delete H.trsfIcdCntrRList; delete H.trsfIcdVhclRList;
			draw();
		}).catch(e => {
			if (e === "no-mrn") { go("cgme0301002q"); frappe.show_alert({ message: __("Use New Declaration to pick the MRN first"), indicator: "orange" }); }
			else $head.html(`<div class="text-danger">${esc(__("Failed to load declaration"))}</div>`);
		});

		function editable() { return EDITABLE.includes(H.prcssStatCd || ""); }
		function deletable() { return editable() && !H.sbmtDt && !H.audtDt && !H.autrId && !!H.dclrNo; }

		function draw() {
			const ed = editable();
			const per = ed ? `<input type="date" class="form-control ji-date" data-f="trsfStrtDt" value="${esc(T.iso_date(H.trsfStrtDt))}"> <span class="ji-dash">~</span>
				<input type="date" class="form-control ji-date" data-f="trsfEndDt" value="${esc(T.iso_date(H.trsfEndDt))}">` : period(H);
			$head.html(`<div class="ji-card-title">${esc(__("ICD Declaration"))}</div>` + U.form_grid([
				["Declaration No", dclr_fmt(H.dclrNo)], ["Status", status(H.prcssStatCd, H.prcssDtm, H.dclrNo, "CDD")],
				["MRN", esc(H.mrn), { req: true }], ["CRN", crn_fmt(H.crn)],
				["Transfer Period", per, { req: true, wide: true }],
				["Place of Departure", wh_cell(H.dptrWrhsCd, H.dptrWrhsNm), { req: true }], ["Place of Destination", wh_cell(H.dstnWrhsCd, H.dstnWrhsNm)],
				["Customs Office", U.pair(H.cstmOfceCd, H.cstmOfceNm || (S.parties.customs || {})[H.cstmOfceCd])], ["Number of Containers (Hand-Over)", esc(H.cntrCnt)],
			]));
			$tabs.html(`<div class="ji-tabs"><a class="active" data-t="c">${esc(__("Container Information"))}</a><a data-t="v">${esc(__("Vehicle Information"))}</a></div><div class="ji-tb"></div>`);
			$tabs.find(".ji-tabs a").on("click", function () { tab($(this).attr("data-t")); });
			tab("c");
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${esc(__("List"))}</button><div class="right">
				${H.dclrNo && H.prcssStatCd === "D06" ? `<button class="btn btn-sm btn-default" id="d-mvmn">${esc(__("Print Movement Sheet"))}</button>
				<button class="btn btn-sm btn-default" id="d-xls">${esc(__("Download"))}</button>` : ""}
				${ed ? U.write_btn("Save", "btn-default", "d-save") : ""}
				${ed ? U.write_btn("Submit", "btn-primary", "d-sbmt") : ""}
				${deletable() ? U.write_btn("Delete", "btn-danger", "d-del") : ""}</div>`);
			$act.find("#d-list").on("click", () => dirty
				? frappe.confirm(__("Containers / vehicles you added are not saved in TANeSW yet. Leave anyway?"), () => go("cgme0301002q"))
				: go("cgme0301002q"));
			$act.find("#d-xls").on("click", () => U.call("icd_declaration_excel", { header: H }, __("Downloading...")).then(U.download_b64));
			$act.find("#d-mvmn").on("click", () => print_movement(H.dclrNo, H.crn, H.isBulk));
			$act.find("#d-save").on("click", () => send("save"));
			$act.find("#d-sbmt").on("click", () => send("sbmt"));
			$act.find("#d-del").on("click", () => frappe.confirm(__("Delete this declaration?"), () =>
				U.call("icd_declaration_delete", { dclr_no: H.dclrNo, prcss_stat_cd: H.prcssStatCd }, __("Deleting...")).then(() => go("cgme0301002q"))));
		}

		function tab(t) {
			$tabs.find(".ji-tabs a").removeClass("active").filter(`[data-t="${t}"]`).addClass("active");
			const $tb = $tabs.find(".ji-tb");
			const ed = editable();
			if (t === "c") {
				U.grid($tb, {
					rows: C, columns: CNTR_COLS, select: ed ? () => true : null,
					toolbar: ed ? `<div class="ji-actions" style="margin:0 0 8px"><span class="ji-muted">${esc(__("Total"))} : ${C.length}</span><div class="right">
						${U.write_btn("Add", "btn-xs btn-primary", "c-add")} <button class="btn btn-xs btn-default" id="c-del">${esc(__("Delete"))}</button></div></div>` : "",
					bind: $h => {
						// Portal (new and saved declarations alike): the popup's Save runs checkCntr + trgt/save, then the
						// ticked containers are ADDED TO THIS GRID. trgt/save returns {"cgmeTrsfIcdMDto":{}} and does not
						// store them — they reach TANeSW with the declaration's Save / Submit. Never reload here, or the
						// picked containers vanish (a declaration then ends up with 0 containers).
						$h.find("#c-add").on("click", () => pick_containers({ mrn: H.mrn, crn: H.crn, dclr_no: H.dclrNo || "", is_bulk: H.isBulk, mode: "save" }, rows => {
							const have = new Set(C.map(r => r.cntrNo));
							let added = 0;
							rows.forEach(r => { if (!have.has(r.cntrNo)) { C.push({ ...r }); added++; } });
							mark_dirty(); tab("c");
							frappe.show_alert({ message: __("{0} container(s) added — press Save or Submit to send them to TANeSW", [added]), indicator: "blue" }, 7);
						}));
						$h.find("#c-del").on("click", () => {
							const sel = new Set($h.selected());
							if (!sel.size) return frappe.show_alert({ message: __("Select rows to delete"), indicator: "orange" });
							C = C.filter(r => !sel.has(r)); mark_dirty(); tab("c");
						});
					},
				});
			} else {
				// Portal Vehicle Information tab: left Template Download / Excel Upload, right New / Delete;
				// clicking the driver name opens the vehicle popup (CGME-0305-107Q) to edit the row.
				const cols = VHCL_COLS.map(c => c.label === "Driver" && ed
					? { ...c, render: (r, i) => r.drvrLcneNo === "NOT ASSIGNED" ? esc(r.drvrNm) : `<a class="ji-link" data-ed="${i}">${esc(r.drvrNm) || "&mdash;"}</a>` }
					: c);
				U.grid($tb, {
					rows: V, columns: cols, select: ed ? () => true : null,
					row_cls: r => r._warn ? "ji-warn" : "",
					toolbar: ed ? `<div class="ji-actions" style="margin:0 0 8px"><div>
							<button class="btn btn-xs btn-default" id="v-tmpl">${esc(__("Template Download"))}</button>
							<button class="btn btn-xs btn-default" id="v-upl">${esc(__("Excel Upload"))}</button>
							<input type="file" id="v-upl-file" accept=".xlsx,.csv" hidden>
							<span class="ji-muted" style="margin-left:8px">${esc(__("Total"))} : ${V.length}</span></div>
						<div class="right"><button class="btn btn-xs btn-primary" id="v-add">${esc(__("New"))}</button> <button class="btn btn-xs btn-default" id="v-del">${esc(__("Delete"))}</button></div></div>` : "",
					bind: $h => {
						$h.find("#v-add").on("click", () => vehicle_dialog(null, row => { V.push(row); mark_dirty(); tab("v"); }));
						$h.find("[data-ed]").on("click", function () { const i = Number($(this).attr("data-ed")); vehicle_dialog(V[i], row => { V[i] = { ...row, _warn: false }; mark_dirty(); tab("v"); }); });
						$h.find("#v-del").on("click", () => {
							const sel = new Set($h.selected());
							if (!sel.size) return frappe.show_alert({ message: __("Select rows to delete"), indicator: "orange" });
							V = V.filter(r => !sel.has(r)); mark_dirty(); tab("v");
						});
						$h.find("#v-tmpl").on("click", () => U.call("icd_vehicle_template", {}, __("Downloading template...")).then(U.download_b64));
						$h.find("#v-upl").on("click", () => $h.find("#v-upl-file").trigger("click"));
						$h.find("#v-upl-file").on("change", function () {
							const f = this.files && this.files[0]; this.value = "";
							if (!f) return;
							const rd = new FileReader();
							rd.onload = () => U.call("icd_vehicle_excel_parse", { filename: f.name, content: String(rd.result).split(",")[1] }, __("Reading {0}...", [f.name])).then(res => {
								// Portal: imported rows are appended to the grid as they are; checks run at Save / Submit.
								const warn_rows = new Set((res.warnings || []).map(w => Number((String(w).match(/\d+/) || [])[0])));
								(res.rows || []).forEach(r => V.push({ ...r, _warn: warn_rows.has(r._excel_row) }));
								mark_dirty(); tab("v");
								const n = (res.rows || []).length;
								if ((res.warnings || []).length) frappe.msgprint({ title: __("{0} vehicle(s) added from {1}", [n, esc(f.name)]),
									indicator: "orange", message: `<p>${esc(__("These rows are highlighted and must be fixed (click the driver name) before Save / Submit:"))}</p>` + res.warnings.map(esc).join("<br>") });
								else frappe.show_alert({ message: __("{0} vehicle(s) added from {1} — press Save or Submit to send them to TANeSW", [n, f.name]), indicator: "green" }, 7);
							});
							rd.readAsDataURL(f);
						});
					},
				});
			}
		}

		function mark_dirty() {
			dirty = true;
			$act.find(".ji-dirty").remove();
			$act.find(".right").prepend(`<span class="ji-dirty ji-muted" style="margin-right:8px;color:var(--orange-500,#f59f00)">${esc(__("Unsaved changes"))}</span>`);
		}

		function send(action) {
			const header = { ...H, ...U.read_form($head) };
			// send dates back in the format TANeSW gave us (YYYYMMDD vs YYYY-MM-DD)
			["trsfStrtDt", "trsfEndDt"].forEach(k => {
				if (header[k] && H[k] && !String(H[k]).includes("-")) header[k] = String(header[k]).replace(/-/g, "");
			});
			const method = action === "sbmt" ? "icd_declaration_submit" : "icd_declaration_save";
			frappe.confirm(action === "sbmt" ? __("Do you want to submit?") : __("Do you want to save?"), () =>
				U.call(method, { header, containers: C, vehicles: V }, action === "sbmt" ? __("Submitting to TANeSW...") : __("Saving in TANeSW...")).then(r => {
					frappe.show_alert({ message: action === "sbmt" ? __("Submitted") : __("Saved"), indicator: "green" });
					st.pending.decl = null;
					const no = (r && r.dclrNo) || H.dclrNo;
					st.last_key = null;
					no ? go("cgme0301005s", no) : render();
				}));
		}
	}

	// CGME-0301-006Q container picker. mode "save" posts checkCntr + trgt/save; "select" just returns rows.
	function pick_containers(p, done) {
		// Portal CGME-0301-006Q "Available Container List": search, tick containers, Save (checkCntr -> trgt/save).
		const d = U.modal("Container List (UI-CGME-0301-006Q)", `<div class="ji-s"><div class="ji-card-title">${esc(__("Available Container List"))}</div>${U.form_grid([
			["Container No.", `<input class="form-control" data-f="cntr_no" style="text-transform:uppercase">`],
			[p.is_bulk === "Y" ? "" : "B/L No", p.is_bulk === "Y" ? "" : `<input class="form-control" data-f="srch_bl_no" style="text-transform:uppercase">`],
		])}<div class="ji-actions"><button class="btn btn-sm ji-reset">${esc(__("Reset"))}</button><div class="right"><button class="btn btn-sm btn-primary ji-search">${esc(__("Search"))}</button></div></div></div>
			<div class="ji-g mt-2"></div>
			<div class="ji-actions"><span></span><div class="right">${p.mode === "save" ? U.write_btn("Save", "btn-primary", "p-ok") : `<button class="btn btn-sm btn-primary" id="p-ok">${esc(__("Select"))}</button>`}</div></div>`, "extra-large");
		const $g = d.$body.find(".ji-g");
		const cols = CNTR_COLS.slice(0, 8).concat([{ label: "B/L No", render: r => esc(r.mblNo || r.hblNo) }]);
		let size = 10;  // portal default page size
		const load = (page = 0) => {
			U.loading($g, cols.length + 2);
			U.call("icd_target_containers", { mrn: p.mrn, crn: p.crn, dclr_no: p.dclr_no, cag_dclr_tp_cd: p.cag || "CDD",
				is_bulk: p.is_bulk || "N", ...U.read_form(d.$body.find(".ji-s")), page, size })
				.then(res => U.grid($g, { rows: res.content, meta: res.page, size, onPage: load, onSize: z => { size = z; load(0); }, select: () => true, columns: cols }));
		};
		d.$body.find(".ji-search").on("click", () => load(0));
		d.$body.find(".ji-reset").on("click", () => { d.$body.find(".ji-s input").val(""); load(0); });
		d.$body.find("#p-ok").on("click", () => {
			const rows = $g.selected ? $g.selected() : [];
			if (!rows.length) return frappe.show_alert({ message: __("Select at least one container"), indicator: "orange" });
			if (p.mode !== "save") { d.hide(); return done(rows); }
			frappe.confirm(__("Do you want to save?"), () =>
				U.call("icd_add_containers", { mrn: p.mrn, crn: p.crn, dclr_no: p.dclr_no, is_bulk: p.is_bulk || "N", rows }, __("Checking and saving containers...")).then(() => { d.hide(); done(rows); }));
		});
		load(0);
	}

	// CGME-0305-107Q vehicle dialog
	function vehicle_dialog(row, on_ok) {
		const v = { drivTpCd: "VEHC", horsChkYn: "Y", ...(row || {}) };
		const inp = (f, extra = "") => `<input class="form-control" data-f="${f}" value="${esc(v[f])}" style="text-transform:uppercase" ${extra}>`;
		const d = U.modal(row ? "Edit Vehicle" : "Add Vehicle", U.form_grid([
			["Driving Type", ["OWN", "VEHC"].map(c => `<label class="mr-3"><input type="radio" name="drv-tp" data-f="drivTpCd" value="${c}" ${v.drivTpCd === c ? "checked" : ""}> ${U.code("CGM0066", c)}</label>`).join(""), { req: true, wide: true }],
			["Licence No.", inp("drvrLcneNo") + `<button class="btn btn-xs btn-default" id="lk-lcne">${esc(__("Look up"))}</button>`, { req: true }],
			["Driver Name", inp("drvrNm"), { req: true }],
			["C45 No.", inp("c45No") + `<button class="btn btn-xs btn-default vh" id="lk-c45">${esc(__("Search"))}</button>`, { req: true }],
			["Horse", ["Y", "N"].map(c => `<label class="mr-3"><input type="radio" name="hors" data-f="horsChkYn" value="${c}" ${v.horsChkYn === c ? "checked" : ""}> ${c}</label>`).join(""), { req: true }],
			["Vehicle No.", inp("vhclNo") + `<button class="btn btn-xs btn-default vh" data-kind="vhcl">${esc(__("Search"))}</button>`],
			["Trailer No.", inp("trlrNo") + `<button class="btn btn-xs btn-default vh" data-kind="trlr">${esc(__("Search"))}</button>`],
			["Semi-Trailer No.", inp("semiTrlrNo") + `<button class="btn btn-xs btn-default vh" data-kind="semi-trlr">${esc(__("Search"))}</button>`],
		]) + `<div class="ji-lk mt-2"></div><div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary" id="vh-ok">${esc(__("OK"))}</button></div></div>`);
		const $b = d.$body;
		const sync = () => {
			const own = $b.find('[data-f="drivTpCd"]:checked').val() === "OWN";
			$b.find('[data-f="c45No"],[data-f="vhclNo"],[data-f="trlrNo"],[data-f="semiTrlrNo"]').prop("readonly", own);
			$b.find(".vh").prop("disabled", own);
			if (own) { $b.find('[data-f="vhclNo"]').val("OWN"); $b.find('[data-f="c45No"],[data-f="trlrNo"],[data-f="semiTrlrNo"]').val(""); }
			else if ($b.find('[data-f="vhclNo"]').val() === "OWN") $b.find('[data-f="vhclNo"]').val("");
		};
		$b.on("change", '[data-f="drivTpCd"]', sync); sync();
		$b.find("#lk-lcne").on("click", () => U.call("trsf_driver_licence", { lcne_no: $b.find('[data-f="drvrLcneNo"]').val() }).then(r => {
			if (r && (r.drvrNm || r.nm)) $b.find('[data-f="drvrNm"]').val(r.drvrNm || r.nm);
			else frappe.show_alert({ message: __("Licence not found"), indicator: "orange" });
		}));
		const $lk = $b.find(".ji-lk");
		$b.find("#lk-c45").on("click", () => U.call("trsf_transporters", { c45_no: $b.find('[data-f="c45No"]').val() }).then(res => U.grid($lk, {
			title: "Transporter Licence", rows: res.content, columns: [
				{ label: "Licence No.", render: (r, i) => `<a class="ji-link" data-c="${i}">${esc(r.c45No)}</a>` },
				{ label: "Company", cls: "left", render: r => esc(r.coNm) }, { label: "Valid To", render: r => fd(r.lcneVldEndDt) }],
			bind: ($h, rows) => $h.find("[data-c]").on("click", function () { $b.find('[data-f="c45No"]').val(rows[Number($(this).attr("data-c"))].c45No); $lk.empty(); }),
		})));
		$b.find(".vh[data-kind]").on("click", function () {
			const kind = $(this).attr("data-kind");
			const c45 = $b.find('[data-f="c45No"]').val();
			if (!c45) return frappe.show_alert({ message: __("Enter the C45 transporter licence first"), indicator: "orange" });
			const target = { vhcl: "vhclNo", trlr: "trlrNo", "semi-trlr": "semiTrlrNo" }[kind];
			U.call("trsf_vehicles", { kind, c45_no: c45, vhcl_no: $b.find(`[data-f="${target}"]`).val() }).then(res => U.grid($lk, {
				title: "Vehicles", rows: res.content, columns: [
					{ label: "Vehicle No.", render: (r, i) => `<a class="ji-link" data-c="${i}">${esc(r.vhclNo)}</a>` },
					{ label: "Licence No.", render: r => esc(r.lcneNo) }, { label: "Chassis No.", render: r => esc(r.chssNo) },
					{ label: "Valid To", render: r => fd(r.lcneVldEndDt) }],
				bind: ($h, rows) => $h.find("[data-c]").on("click", function () { $b.find(`[data-f="${target}"]`).val(rows[Number($(this).attr("data-c"))].vhclNo); $lk.empty(); }),
			}));
		});
		$b.find("#vh-ok").on("click", () => {
			const f = U.read_form($b);
			Object.keys(f).forEach(k => { if (typeof f[k] === "string") f[k] = f[k].toUpperCase(); });
			f.drvrNm = (U.read_form($b).drvrNm || "").toUpperCase();
			if (!f.drvrNm || !f.drvrLcneNo) return frappe.show_alert({ message: __("Driver Name and Licence No. are required"), indicator: "orange" });
			if (f.drivTpCd === "VEHC" && (!f.vhclNo || !f.c45No)) return frappe.show_alert({ message: __("Vehicle No. and C45 No. are required"), indicator: "orange" });
			if (f.drivTpCd === "OWN") Object.assign(f, { vhclNo: "OWN", c45No: "", trlrNo: "", semiTrlrNo: "" });
			d.hide(); on_ok({ ...(row || {}), ...f });
		});
	}

	// ============================================================ amendment / cancellation lists
	function amd_cncl_list($body, sid, method, open_sid, no_field, label_no) {
		const statuses = Object.fromEntries(AMD_STATUS.map(c => [c, (S.codes.COM0023 || {})[c] || c]));
		list_screen($body, sid,
			() => ({ srch_dt_tp: "rgsrDt", rgsr_dt_from: T.add_days(T.today(), -17), rgsr_dt_to: T.today(), srch_no_tp: "dclrNo", prcss_stat_cds: AMD_STATUS }),  // portal default: last 17 days
			f => [
				[`<select class="form-control" data-f="srch_dt_tp" style="height:26px;font-size:12px"><option value="rgsrDt">${esc(__("Date of Register"))}</option><option value="sbmtDt" ${f.srch_dt_tp === "sbmtDt" ? "selected" : ""}>${esc(__("Date of Submission"))}</option></select>`,
					U.date_range("rgsr_dt_from", "rgsr_dt_to", f, ["-6M", "-3M", "-1M", "-1W", "T"]), { req: true }],
				["MRN", `<input class="form-control" data-f="mrn" value="${esc(f.mrn)}" style="text-transform:uppercase">`],
				[`<select class="form-control" data-f="srch_no_tp" style="height:26px;font-size:12px"><option value="dclrNo">${esc(__(label_no))}</option><option value="bfDclrNo" ${f.srch_no_tp === "bfDclrNo" ? "selected" : ""}>${esc(__("ICD Declaration No"))}</option></select>`,
					`<input class="form-control" data-f="srch_no" value="${esc(f.srch_no)}">`],
				["Place of Departure", `<input class="form-control" list="cg-wh2" data-f="dptr_wrhs_cd" value="${esc(f.dptr_wrhs_cd)}">${wh_list("cg-wh2")}`],
				["Status", U.checks("prcss_stat_cds", statuses, f.prcss_stat_cds), { wide: true, req: true }],
			],
			[
				{ label: label_no, render: r => `<a class="ji-link" data-no="${esc(r[no_field])}">${dclr_fmt(r[no_field])}</a>` },
				{ label: "ICD Declaration No", render: r => dclr_fmt(r.reffDclrNo) },
				{ label: "MRN", render: r => esc(r.mrn) },
				{ label: "Departure Place", cls: "left", render: r => wh_cell(r.dptrWrhsCd, r.dptrWrhsNm) },
				{ label: "Destination Place", cls: "left", render: r => wh_cell(r.dstnWrhsCd, r.dstnWrhsNm) },
				{ label: "Transfer Period", render: period },
			].concat(sid === "cgme0301011q" ? [
				{ label: "Containers (Hand-Over)", render: r => esc(r.cntrCnt) }, { label: "Vehicle", render: r => esc(r.vhclCnt) }] : [])
				.concat([{ label: "Status", render: r => status(r.prcssStatCd, r.prcssDtm, r[no_field], sid === "cgme0301011q" ? "CDA" : "CDC") }]),
			method,
			{
				validate: f => (f.prcss_stat_cds || []).length ? true : (frappe.show_alert({ message: __("Select at least one status"), indicator: "orange" }), false),
				select: r => ["A01", "A05"].includes(r.prcssStatCd) && !r.sbmtDt,
				toolbar: `${U.write_btn("New", "btn-default btn-xs", "cg-new")} ${U.write_btn("Delete", "btn-danger btn-xs", "cg-del")}`,
				bind: ($h, rows, reload) => {
					$h.find("[data-no]").on("click", function () { go(open_sid, $(this).attr("data-no")); });
					$h.find("#cg-new").on("click", () => go(open_sid, "new"));
					$h.find("#cg-del").on("click", () => {
						const sel = $h.selected();
						if (!sel.length) return frappe.show_alert({ message: __("Select rows to delete"), indicator: "orange" });
						const one = r => no_field === "amdDclrNo" ? U.call("icd_amendment_delete", { header: r }) : U.call("icd_cancellation_delete", { cncl_dclr_no: r.cnclDclrNo });
						frappe.confirm(__("Delete {0} record(s)?", [sel.length]), () => sel.reduce((p, r) => p.then(() => one(r)), Promise.resolve())
							.then(() => { frappe.show_alert({ message: __("Deleted"), indicator: "green" }); reload(); }));
					});
				},
			});
	}
	function s_amd_list($body) { amd_cncl_list($body, "cgme0301011q", "icd_amendment_list", "cgme0301012s", "amdDclrNo", "Amend Declaration No."); }
	function s_cncl_list($body) { amd_cncl_list($body, "cgme0301021q", "icd_cancellation_list", "cgme0301022s", "cnclDclrNo", "Cancel Declaration No"); }

	// CGME-0301-013Q target popup (approved declarations): dclr_tp_cd CDA amend / CDC cancel
	function pick_target(dclr_tp_cd, on_pick) {
		const f = { rgsr_dt_from: T.add_months(T.today(), -1), rgsr_dt_to: T.today() };
		const d = U.modal(dclr_tp_cd === "CDA" ? "ICD Declaration to Amend" : "ICD Declaration to Cancel", `<div class="ji-s">${U.form_grid([
			["Date of Register", U.date_range("rgsr_dt_from", "rgsr_dt_to", f), { req: true, wide: true }],
			["Declaration No", `<input class="form-control" data-f="dclr_no">`], ["MRN", `<input class="form-control" data-f="mrn" style="text-transform:uppercase">`],
		])}<div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary ji-search">${esc(__("Search"))}</button></div></div></div><div class="ji-g mt-2"></div>`, "extra-large");
		U.bind_range(d.$body);
		const $g = d.$body.find(".ji-g");
		const load = (page = 0) => {
			U.loading($g, 8);
			U.call("icd_amendment_targets", { dclr_tp_cd, ...U.read_form(d.$body.find(".ji-s")), page, size: 10 }).then(res => U.grid($g, {
				rows: res.content, meta: res.page, size: 10, onPage: load, onSize: () => load(0),
				columns: [
					{ label: "Declaration No", render: (r, i) => `<a class="ji-link" data-i="${i}">${dclr_fmt(r.dclrNo)}</a>` },
					{ label: "MRN", render: r => esc(r.mrn) },
					{ label: "Departure Place", cls: "left", render: r => wh_cell(r.dptrWrhsCd, r.dptrWrhsNm) },
					{ label: "Destination Place", cls: "left", render: r => wh_cell(r.dstnWrhsCd, r.dstnWrhsNm) },
					{ label: "Transfer Period", render: period },
					{ label: "Containers (Hand-Over)", render: r => esc(r.cntrCnt) }, { label: "Vehicle", render: r => esc(r.vhclCnt) },
					{ label: "Status", render: r => status(r.prcssStatCd) },
				],
				bind: ($h, rows) => $h.find("[data-i]").on("click", function () { d.hide(); on_pick(rows[Number($(this).attr("data-i"))]); }),
			}));
		};
		d.$body.find(".ji-search").on("click", () => load(0));
		load(0);
	}

	function reference_block(r) {
		return `<div class="ji-card-title">${esc(__("ICD Declaration"))}</div>` + U.form_grid([
			["ICD Declaration No", dclr_fmt(r.dclrNo || r.reffDclrNo)], ["MRN", esc(r.mrn)],
			["Place of Departure", wh_cell(r.dptrWrhsCd, r.dptrWrhsNm)], ["Place of Destination", wh_cell(r.dstnWrhsCd, r.dstnWrhsNm)],
			["Transfer Period", period(r)], ["Number of Containers (Hand-Over)", esc(r.cntrCnt)],
		]);
	}
	function penalty_rows(h) {
		// Portal amendment/cancellation forms carry the penalty in USD and TZS (pnltUsdAmt / pnltAmt) plus the bill.
		return h.pnltImpsYn === "Y" ? [["Penalty", `USD ${num(h.pnltUsdAmt)}${h.pnltAmt ? ` / TZS ${num(h.pnltAmt)}` : ""}`], ["Bill No.", esc(h.bllNo)]] : [];
	}

	// ============================================================ 012S amendment
	function s_amd_decl($body, amd_no) {
		const is_new = !amd_no || amd_no === "new";
		const $ref = $(`<div class="ji-card"></div>`).appendTo($body);
		const $head = $(`<div class="ji-card"></div>`).appendTo($body);
		const $items = $(`<div class="ji-card" style="display:none"></div>`).appendTo($body);
		const $tabs = $(`<div class="ji-card"></div>`).appendTo($body);
		const $act = $(`<div class="ji-actions"></div>`).appendTo($body);
		let H = {}, R = {}, C = [], V = [], BC = [], BV = [], ITEMS = [];

		const with_tp = (rows, tp) => (rows || []).map(r => ({ ...r, dtlAmdTpCd: r.dtlAmdTpCd || tp }));
		function adopt(data) {
			// data = trsfIcdAmdInit (new) or trsfIcdAmdDcla (existing)
			R = { ...data };
			const amd = data.cgmeDclrAmdMDto || {};
			H = { ...H, ...amd, reffDclrNo: data.dclrNo || H.reffDclrNo, mrn: data.mrn || H.mrn, isBulk: data.isBulk };
			if (amd.dclrAmdPnltD && amd.dclrAmdPnltD.pnltImpsYn === "Y") Object.assign(H, { pnltImpsYn: "Y", pnltUsdAmt: amd.dclrAmdPnltD.pnltUsdAmt, bllNo: amd.dclrAmdPnltD.bllNo });
			const has_bf = (data.bfCntrRList || []).length || (data.afCntrRList || []).length;
			BC = with_tp(has_bf ? data.bfCntrRList : data.trsfIcdCntrRList, "O");
			C = with_tp(has_bf ? data.afCntrRList : data.trsfIcdCntrRList, "O");
			const has_bv = (data.bfVhclRList || []).length || (data.afVhclRList || []).length;
			BV = with_tp(has_bv ? data.bfVhclRList : data.trsfIcdVhclRList, "O");
			V = with_tp(has_bv ? data.afVhclRList : data.trsfIcdVhclRList, "O");
			ITEMS = amd.dclrAmdItmRList || [];
			draw();
		}
		if (is_new) {
			$ref.html(`<div class="ji-muted">${esc(__("Select the approved ICD declaration to amend."))}</div>
				<div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary" id="a-pick">${esc(__("Select Declaration"))}</button></div></div>`);
			$ref.find("#a-pick").on("click", () => pick_target("CDA", t => U.call("icd_amendment_init", { dclr_no: t.dclrNo }, __("Loading declaration...")).then(adopt)));
			$head.hide(); $tabs.hide();
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${esc(__("List"))}</button>`).find("#d-list").on("click", () => go("cgme0301011q"));
		} else {
			U.call("icd_amendment", { amd_dclr_no: amd_no }).then(adopt);
		}

		function editable() { return EDITABLE.includes(H.prcssStatCd || ""); }
		function draw() {
			$head.show(); $tabs.show();
			const ed = editable();
			$ref.html(reference_block(R));
			$head.html(`<div class="ji-card-title">${esc(__("Amendment"))}</div>` + U.form_grid([
				["Amend Declaration No.", dclr_fmt(H.amdDclrNo)], ["Status", status(H.prcssStatCd, H.prcssDtm)],
				["ICD Declaration No", dclr_fmt(H.reffDclrNo)], ["Amendment Type", esc(H.amdTpCd || "ZZ")],
				["Amendment Reason", ed ? `<textarea class="form-control" data-f="amdRsn">${esc(H.amdRsn)}</textarea>` : esc(H.amdRsn), { req: true, wide: true }],
				...penalty_rows(H),
			]));
			if (H.amdDclrNo && ITEMS.length) {
				$items.show();
				U.grid($items, { title: "Modification", rows: ITEMS, columns: [
					{ label: "Modify Item", cls: "left", render: r => esc(r.amdItmNm) },
					{ label: "Before", cls: "left", render: r => esc(r.bfItmCn) },
					{ label: "After", cls: "left", render: (r, i) => ed ? `<input class="form-control" data-item="${i}" value="${esc(r.afItmCn)}">` : esc(r.afItmCn) },
				], bind: $h => $h.on("change", "[data-item]", function () { ITEMS[Number($(this).attr("data-item"))].afItmCn = $(this).val(); }) });
			} else $items.hide();
			$tabs.html(`<div class="ji-tabs"><a class="active" data-t="c">${esc(__("Container Information"))}</a><a data-t="v">${esc(__("Vehicle Information"))}</a></div><div class="ji-tb"></div>`);
			$tabs.find(".ji-tabs a").on("click", function () { tab($(this).attr("data-t")); });
			tab("c");
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${esc(__("List"))}</button><div class="right">
				${ed ? U.write_btn("Save", "btn-default", "d-save") : ""}
				${ed && H.amdDclrNo ? U.write_btn("Submit", "btn-primary", "d-sbmt") : ""}
				${ed && H.amdDclrNo && !H.sbmtDt ? U.write_btn("Delete", "btn-danger", "d-del") : ""}</div>`);
			$act.find("#d-list").on("click", () => go("cgme0301011q"));
			$act.find("#d-save").on("click", () => send("save"));
			$act.find("#d-sbmt").on("click", () => send("sbmt"));
			$act.find("#d-del").on("click", () => frappe.confirm(__("Delete this amendment?"), () =>
				U.call("icd_amendment_delete", { header: H }, __("Deleting...")).then(() => go("cgme0301011q"))));
		}
		const amd_col = { label: "Amendment Type", render: r => esc({ O: "", A: __("Add"), C: __("Change"), D: __("Delete") }[r.dtlAmdTpCd] ?? r.dtlAmdTpCd) };
		function tab(t) {
			$tabs.find(".ji-tabs a").removeClass("active").filter(`[data-t="${t}"]`).addClass("active");
			const $tb = $tabs.find(".ji-tb");
			const ed = editable();
			const toggle = (list, i) => {
				const r = list[i];
				if (r.dtlAmdTpCd === "A") list.splice(i, 1);
				else r.dtlAmdTpCd = r.dtlAmdTpCd === "D" ? "O" : "D";
			};
			if (t === "c") {
				U.grid($tb, {
					rows: C, columns: [amd_col].concat(CNTR_COLS).concat(ed ? [{ label: "", render: (r, i) => `<button class="btn btn-xs btn-default" data-tg="${i}">${esc(r.dtlAmdTpCd === "D" ? __("Undo") : __("Delete"))}</button>` }] : []),
					row_cls: r => `amd-${r.dtlAmdTpCd}`,
					toolbar: ed ? `<div class="ji-actions" style="margin:0 0 8px"><span></span><div class="right"><button class="btn btn-xs btn-primary" id="c-add">${esc(__("Add"))}</button></div></div>` : "",
					bind: $h => {
						$h.find("[data-tg]").on("click", function () { toggle(C, Number($(this).attr("data-tg"))); tab("c"); });
						$h.find("#c-add").on("click", () => pick_containers({ mrn: H.mrn || R.mrn, crn: H.crn || R.crn, dclr_no: H.reffDclrNo, is_bulk: R.isBulk, cag: "CDA", mode: "select" },
							rows => { rows.forEach(r => C.push({ ...r, dtlAmdTpCd: "A" })); tab("c"); }));
					},
				});
			} else {
				U.grid($tb, {
					rows: V, columns: [amd_col].concat(VHCL_COLS).concat(ed ? [{ label: "", render: (r, i) => `<button class="btn btn-xs btn-default" data-ed="${i}">${esc(__("Edit"))}</button> <button class="btn btn-xs btn-default" data-tg="${i}">${esc(r.dtlAmdTpCd === "D" ? __("Undo") : __("Delete"))}</button>` }] : []),
					row_cls: r => `amd-${r.dtlAmdTpCd}`,
					toolbar: ed ? `<div class="ji-actions" style="margin:0 0 8px"><span></span><div class="right"><button class="btn btn-xs btn-primary" id="v-add">${esc(__("Add"))}</button></div></div>` : "",
					bind: $h => {
						$h.find("[data-tg]").on("click", function () { toggle(V, Number($(this).attr("data-tg"))); tab("v"); });
						$h.find("#v-add").on("click", () => vehicle_dialog(null, row => { V.push({ ...row, dtlAmdTpCd: "A" }); tab("v"); }));
						$h.find("[data-ed]").on("click", function () {
							const i = Number($(this).attr("data-ed"));
							vehicle_dialog(V[i], row => { V[i] = { ...row, dtlAmdTpCd: V[i].dtlAmdTpCd === "A" ? "A" : "C" }; tab("v"); });
						});
					},
				});
			}
		}
		function send(action) {
			const header = { ...H, ...U.read_form($head) };
			frappe.confirm(action === "sbmt" ? __("Do you want to submit?") : __("Do you want to save?"), () =>
				U.call("icd_amendment_save", { header, items: ITEMS, containers: C, vehicles: V, bf_containers: BC, bf_vehicles: BV, action },
					action === "sbmt" ? __("Submitting amendment...") : __("Saving amendment...")).then(r => {
					frappe.show_alert({ message: action === "sbmt" ? __("Submitted") : __("Saved"), indicator: "green" });
					const no = (r && r.cgmeDclrAmdMDto && r.cgmeDclrAmdMDto.amdDclrNo) || H.amdDclrNo;
					st.last_key = null;
					no ? go("cgme0301012s", no) : render();
				}));
		}
	}

	// ============================================================ 022S cancellation
	function s_cncl_decl($body, cncl_no) {
		const is_new = !cncl_no || cncl_no === "new";
		const $ref = $(`<div class="ji-card"></div>`).appendTo($body);
		const $head = $(`<div class="ji-card"></div>`).appendTo($body);
		const $tabs = $(`<div class="ji-card"></div>`).appendTo($body);
		const $act = $(`<div class="ji-actions"></div>`).appendTo($body);
		let H = {}, R = {};
		function load_ref(dclr_no) {
			return U.call("icd_cancellation_reference", { dclr_no }).then(r => {
				R = r || {};
				H = { ...H, reffDclrNo: R.dclrNo || dclr_no, mrn: H.mrn || R.mrn, crn: H.crn || R.crn, isBulk: R.isBulk };
				draw();
			});
		}
		if (is_new) {
			$ref.html(`<div class="ji-muted">${esc(__("Select the approved ICD declaration to cancel."))}</div>
				<div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary" id="c-pick">${esc(__("Select Declaration"))}</button></div></div>`);
			$ref.find("#c-pick").on("click", () => pick_target("CDC", t => load_ref(t.dclrNo)));
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${esc(__("List"))}</button>`).find("#d-list").on("click", () => go("cgme0301021q"));
		} else {
			U.call("icd_cancellation", { cncl_dclr_no: cncl_no }).then(c => {
				H = { ...c };
				if (c.dclrAmdPnltD && c.dclrAmdPnltD.pnltImpsYn === "Y") Object.assign(H, { pnltImpsYn: "Y", pnltUsdAmt: c.dclrAmdPnltD.pnltUsdAmt, bllNo: c.dclrAmdPnltD.bllNo });
				return load_ref(c.reffDclrNo);
			});
		}
		function editable() { return EDITABLE.includes(H.prcssStatCd || ""); }
		function draw() {
			const ed = editable();
			$ref.html(reference_block({ ...R, cstmOfceCd: R.cstmOfceCd }) + U.form_grid([["Customs Office", U.pair(R.cstmOfceCd, R.cstmOfceNm)], ["CRN", esc(R.crn)]]));
			$head.html(`<div class="ji-card-title">${esc(__("Cancellation"))}</div>` + U.form_grid([
				["Cancel Declaration No", dclr_fmt(H.cnclDclrNo)], ["Status", status(H.prcssStatCd, H.prcssDtm)],
				["Report No", dclr_fmt(H.reffDclrNo), { req: true }], ["MRN", esc(H.mrn)],
				["Cancellation Comment", ed ? `<textarea class="form-control" data-f="cnclCn">${esc(H.cnclCn)}</textarea>` : esc(H.cnclCn), { req: true, wide: true }],
				...penalty_rows(H),
			]));
			$tabs.html(`<div class="ji-tabs"><a class="active" data-t="c">${esc(__("Container Information"))}</a><a data-t="v">${esc(__("Vehicle Information"))}</a></div><div class="ji-tb"></div>`);
			const tab = t => {
				$tabs.find(".ji-tabs a").removeClass("active").filter(`[data-t="${t}"]`).addClass("active");
				U.grid($tabs.find(".ji-tb"), t === "c" ? { rows: R.trsfIcdCntrRList || [], columns: CNTR_COLS } : { rows: R.trsfIcdVhclRList || [], columns: VHCL_COLS });
			};
			$tabs.find(".ji-tabs a").on("click", function () { tab($(this).attr("data-t")); });
			tab("c");
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${esc(__("List"))}</button><div class="right">
				${ed ? U.write_btn("Save", "btn-default", "d-save") : ""}
				${ed && H.cnclDclrNo ? U.write_btn("Submit", "btn-primary", "d-sbmt") : ""}
				${ed && H.cnclDclrNo && !H.sbmtDt ? U.write_btn("Delete", "btn-danger", "d-del") : ""}</div>`);
			$act.find("#d-list").on("click", () => go("cgme0301021q"));
			const send = action => {
				const header = { ...H, ...U.read_form($head) };
				frappe.confirm(action === "sbmt" ? __("Do you want to submit?") : __("Do you want to save?"), () =>
					U.call("icd_cancellation_save", { header, action }, action === "sbmt" ? __("Submitting cancellation...") : __("Saving cancellation...")).then(r => {
						frappe.show_alert({ message: action === "sbmt" ? __("Submitted") : __("Saved"), indicator: "green" });
						const no = (r && r.cnclDclrNo) || H.cnclDclrNo;
						st.last_key = null;
						no ? go("cgme0301022s", no) : render();
					}));
			};
			$act.find("#d-save").on("click", () => send("save"));
			$act.find("#d-sbmt").on("click", () => send("sbmt"));
			$act.find("#d-del").on("click", () => frappe.confirm(__("Delete this cancellation?"), () =>
				U.call("icd_cancellation_delete", { cncl_dclr_no: H.cnclDclrNo }, __("Deleting...")).then(() => go("cgme0301021q"))));
		}
	}
})();
