// Cargo Mgmt screens: Simple Transfer, Carry-In, Carry-Out, Stripping, Cargo Tracking.
// Plugs into the tanesw-cargo page through window.tanesw_cargo.
(() => {
	const CG = window.tanesw_cargo;
	if (!CG || CG._more) return;
	CG._more = true;
	const C = () => CG.ctx();
	const E = v => C().esc(v);
	// Unit names as the stripping grids show them: "Package(S)", "Kilogram" (COM0007 packages, COM0005 weights)
	const UNIT = (grp, c) => E((C().S.codes[grp] || {})[c] || c || "");
	const CSTM = c => c ? C().U.pair(c, (C().S.parties.customs || {})[c]) : "";  // "[TZDL] DAR CUSTOMS SERVICE CENTRE"
	const STATUS_RPT = { N: "NOT REPORT", P: "REPORTED PARTIALLY", Y: "REPORTED" };
	const EDIT_ROW = s => [null, undefined, "", "A01", "A05", "D09"].includes(s);

	Object.assign(CG.SCREENS, {
		cgme0302001q: { title: "Simple Transfer Declaration List", ui: "UI-CGME-0302-001Q" },
		cgme0302002s: { title: "Simple Transfer Declaration Registration", ui: "UI-CGME-0302-002S", parent: "cgme0302001q" },
		cgme0302011q: { title: "Simple Transfer Amendment List", ui: "UI-CGME-0302-011Q" },
		cgme0302012s: { title: "Simple Transfer Declaration Amendment", ui: "UI-CGME-0302-012S", parent: "cgme0302011q" },
		cgme0302021q: { title: "Simple Transfer Cancellation List", ui: "UI-CGME-0302-021Q" },
		cgme0302022s: { title: "Simple Transfer Cancellation", ui: "UI-CGME-0302-022S", parent: "cgme0302021q" },
		cgme0401001q: { title: "Expected Carry-In List", ui: "UI-CGME-0401-001Q" },
		cgme0401002s: { title: "Carry-In Declaration Registration", ui: "UI-CGME-0401-002S", parent: "cgme0401001q" },
		cgme0401003s: { title: "Carry-In Report (B/L)", ui: "UI-CGME-0401-003S", parent: "cgme0401001q" },
		cgme0401005q: { title: "Bulk Expected Carry-in List", ui: "UI-CGME-0401-005Q", parent: "cgme0401001q" },
		cgme0401006s: { title: "Bulk Carry-In Registration", ui: "UI-CGME-0401-006S", parent: "cgme0401005q" },
		cgme0401008q: { title: "Carry-Out Approval List", ui: "UI-CGME-0401-008Q" },
		cgme0401017s: { title: "Carry-Out Report (B/L)", ui: "UI-CGME-0401-017S", parent: "cgme0401008q" },
		cgme0401009s: { title: "Carry-Out Registration", ui: "UI-CGME-0401-009S", parent: "cgme0401008q" },
		cgme0406001q: { title: "Stripping Schedule List", ui: "UI-CGME-0406-001Q" },
		cgme0406002q: { title: "Stripping Result Report List", ui: "UI-CGME-0406-002Q" },
		cgme0406003s: { title: "Stripping Result Report Registration", ui: "UI-CGME-0406-003S", parent: "cgme0406002q" },
		cgme0406008q: { title: "Stripping Amendment List", ui: "UI-CGME-0406-008Q" },
		cgme0406009s: { title: "Stripping Result Amendment Registration", ui: "UI-CGME-0406-009S", parent: "cgme0406008q" },
		cgme0406012q: { title: "Stripping Cancellation List", ui: "UI-CGME-0406-012Q" },
		cgme0406013s: { title: "Stripping Result Cancellation Registration", ui: "UI-CGME-0406-013S", parent: "cgme0406012q" },
		cgme0910001q: { title: "Cargo Tracking List", ui: "UI-CGME-0910-001Q" },
	});

	// ---------------------------------------------------------------- small helpers
	const input = (f, v, extra = "") => `<input class="form-control" data-f="${f}" value="${E(v)}" ${extra}>`;
	const upper = (f, v) => input(f, v, 'style="text-transform:uppercase"');
	const select = (f, options, v, blank = true) => !Object.keys(options || {}).length ? input(f, v) : `<select class="form-control" data-f="${f}">${blank ? `<option value="">${E(__("All"))}</option>` : ""}${Object.entries(options || {})
		.map(([k, n]) => `<option value="${E(k)}" ${v === k ? "selected" : ""}>[${E(k)}] ${E(n)}</option>`).join("")}</select>`;
	const lbl_select = (f, opts, v) => `<select class="form-control" data-f="${f}" style="height:26px;font-size:12px">${opts.map(([k, l]) =>
		`<option value="${k}" ${v === k ? "selected" : ""}>${E(__(l))}</option>`).join("")}</select>`;
	const card = $body => $(`<div class="ji-card"></div>`).appendTo($body);
	const actions = $body => $(`<div class="ji-actions"></div>`).appendTo($body);
	const ensure_codes = groups => {
		const { U, S } = C();
		const missing = groups.filter(g => !S.codes[g]);
		return missing.length ? U.call("tanesw_integration.joint_inspection.codes", { comn_cds: missing }).then(c => Object.assign(S.codes, c || {})) : Promise.resolve();
	};
	const confirm_call = (msg, method, args, freeze, then) => frappe.confirm(__(msg), () => C().U.call(method, args, freeze).then(then));
	const editable_input = (cls, i, v, type = "text") => `<input class="form-control ${cls}" data-i="${i}" type="${type}" value="${E(v)}" style="min-width:90px">`;

	// =================================================================== Simple Transfer
	const SIMPL_COLS = no_field => [
		{ label: no_field === "dclrNo" ? "Declaration No" : (no_field === "amdDclrNo" ? "Amend Declaration No" : "Cancel Declaration No"), render: r => `<a class="ji-link" data-no="${E(r[no_field])}">${CG.dclr_fmt(r[no_field])}</a>` },
	].concat(no_field !== "dclrNo" ? [{ label: "Before Declaration No", render: r => CG.dclr_fmt(r.reffDclrNo) }] : []).concat([
		{ label: "CRN", render: r => CG.crn_fmt(r.crn) },
		{ label: "Transfer Type", render: r => C().U.code("CGM0064", r.trsfTpCd) },
		{ label: "Transfer Period", render: CG.period },
		{ label: "Departure", cls: "left", render: r => CG.wh_cell(r.dptrWrhsCd, r.dptrWrhsNm) },
		{ label: "Destination", cls: "left", render: r => CG.wh_cell(r.dstnWrhsCd, r.dstnWrhsNm) },
		{ label: "Hand-Over", render: r => E(r.hndvYn) },
		{ label: "Carry-Out", render: r => E(r.croYn) },
		{ label: "Carry-In", render: r => E(r.criYn) },
	]).concat(no_field !== "dclrNo" ? [{ label: "Penalty", render: r => E(r.pnltImpsYn) }] : []).concat([
		{ label: "Status", render: r => CG.status(r.prcssStatCd, r.prcssDtm, r[no_field], { dclrNo: "STD", amdDclrNo: "STA", cnclDclrNo: "STC" }[no_field]) },
	]);

	// Portal Status checkbox defaults: STD list vs amendment/cancellation lists (cgmePrcdCd STD / STA / STC).
	const SIMPL_STAT = { cgme0302001q: ["A01", "A04", "A05", "D01", "D06", "D08", "D09", "G07"] };
	const SIMPL_STAT_AC = ["A01", "A04", "A05", "D01", "D06", "D08", "D09", "D15"];
	function simpl_list($body, sid, method, open_sid, no_field, no_opts) {
		const stat = SIMPL_STAT[sid] || SIMPL_STAT_AC;
		ensure_codes(["CGM0064", "COM0023"]).then(() => CG.list_screen($body, sid,
			() => ({ from_rgsr_dt: C().T.add_months(C().T.today(), -1), to_rgsr_dt: C().T.today(), srch_no_tp: "dclrNo", prcss_stat_cds: stat }),
			f => [
				[sid === "cgme0302001q" ? "Date of Register" : "Registration Date", C().U.date_range("from_rgsr_dt", "to_rgsr_dt", f, ["-6M", "-3M", "-1M", "-1W", "T"]), { req: true }],
				[lbl_select("srch_no_tp", no_opts, f.srch_no_tp), input("srch_no", f.srch_no)],
			].concat(sid === "cgme0302001q" ? [["Transfer Type", select("srch_trsf_tp_cd",
				// the portal hides A, D, F, G, I, P on this screen
				Object.fromEntries(Object.entries(C().S.codes.CGM0064 || {}).filter(([k]) => !["A", "D", "F", "G", "I", "P"].includes(k))), f.srch_trsf_tp_cd), { wide: true }]] : [])
				.concat([["Status", C().U.checks("prcss_stat_cds", Object.fromEntries(stat.map(c => [c, (C().S.codes.COM0023 || {})[c] || c])), f.prcss_stat_cds), { wide: true, req: true }]]),
			SIMPL_COLS(no_field), method, {
				validate: f => (f.prcss_stat_cds || []).length ? true : (frappe.show_alert({ message: __("Select at least one status"), indicator: "orange" }), false),
				// amendment / cancellation lists have a Delete for registered rows, as in the portal
				select: r => ["A01", "A05"].includes(r.prcssStatCd) && !r.sbmtDt,
				toolbar: (no_field === "dclrNo" ? `<button class="btn btn-default btn-xs" id="cg-tmpl">${E(__("Template Download"))}</button> ${C().U.write_btn("Excel Upload", "btn-default btn-xs", "cg-upl")}<input type="file" id="cg-upl-file" accept=".xls,.xlsx" hidden> ` : "")
					+ `${C().U.write_btn("New", "btn-default btn-xs", "cg-new")} ${C().U.write_btn("Delete", "btn-danger btn-xs", "cg-del")}`,
				bind: ($h, rows, reload) => {
					$h.find("[data-no]").on("click", function () { CG.go(open_sid, $(this).attr("data-no")); });
					$h.find("#cg-new").on("click", () => CG.go(open_sid, "new"));
					$h.find("#cg-del").on("click", () => {
						const sel = $h.selected();
						if (!sel.length) return frappe.show_alert({ message: __("Select rows to delete"), indicator: "orange" });
						const done = () => { frappe.show_alert({ message: __("Deleted"), indicator: "green" }); reload(); };
						if (no_field === "dclrNo") return frappe.confirm(__("Delete {0} record(s)?", [sel.length]), () => C().U.call("simpl_delete_many", { dclr_nos: sel.map(r => r.dclrNo) }, __("Deleting...")).then(done));
						const one = r => no_field === "amdDclrNo" ? C().U.call("simpl_amd_delete", { header: r }) : C().U.call("simpl_cncl_delete", { cncl_dclr_no: r.cnclDclrNo });
						frappe.confirm(__("Delete {0} record(s)?", [sel.length]), () =>
							sel.reduce((p, r) => p.then(() => one(r)), Promise.resolve()).then(done));
					});
					$h.find("#cg-tmpl").on("click", () => C().U.call("download_template", {}, __("Downloading template...")).then(C().U.download_b64));
					$h.find("#cg-upl").on("click", () => $h.find("#cg-upl-file").trigger("click"));
					$h.find("#cg-upl-file").on("change", function () {
						const f = this.files && this.files[0]; this.value = "";
						if (!f) return;
						const rd = new FileReader();
						rd.onload = () => C().U.call("simpl_excel_upload", { filename: f.name, content: String(rd.result).split(",")[1] }, __("Uploading to TANeSW...")).then(res => {
							const m = (res && res.messages) || [];
							if (!m.length) frappe.msgprint(__("All declarations in the file were registered."));
							else frappe.msgprint({ title: __("TANeSW validation"), message: m.map(x => E(typeof x === "string" ? x : (x.msg || x.errMsg || JSON.stringify(x)))).join("<br>") });
							reload();
						});
						rd.readAsDataURL(f);
					});
				},
			}));
	}

	const SIMPL_CNTR_COLS = [
		{ label: "Type", render: r => C().U.code("CGM0021", r.pcknUtCd || r.loadTpCd) },
		{ label: "Container No.", render: r => E(r.cntrNo) },
		{ label: "Container Size", render: r => E((C().S.codes.CGM0010 || {})[r.cntrSizeCd] || r.cntrSizeCd) },  // portal shows the size name (CGM0010)
		{ label: "Seal No#1", render: r => E(r.sealNo1) },
		{ label: "Package", cls: "num", render: r => `${CG.num(r.cntrPckgNo)} ${E(r.cntrPckgUtCd || r.pckgUtCd || "")}` },
		{ label: "Weight", cls: "num", render: r => `${CG.num(r.cntrWght)} ${E(r.cntrWghtUtCd || r.wghtUtCd || "")}` },
	];

	function pick_cargo_ref(on_pick) {
		const { U } = C();
		const d = U.modal("Cargo Reference", `<div class="ji-s">${U.form_grid([
			["Cargo Type", `<label class="mr-3"><input type="radio" name="cg-ct" data-f="srch_cag_tp" value="import" checked> ${E(__("Import"))}</label><label><input type="radio" name="cg-ct" data-f="srch_cag_tp" value="export"> ${E(__("Export"))}</label>`, { wide: true }],
			["Master B/L No", upper("srch_bl_no")], ["CRN", upper("srch_crn_reff_no")],
		])}<div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary ji-search">${E(__("Search"))}</button></div></div></div><div class="ji-g mt-2"></div>`, "extra-large");
		const $g = d.$body.find(".ji-g");
		const load = (page = 0) => {
			U.loading($g, 8);
			U.call("simpl_cargo_refs", { ...U.read_form(d.$body.find(".ji-s")), page, size: 10 }).then(res => U.grid($g, {
				rows: res.content, meta: res.page, size: 10, onPage: load, onSize: () => load(0),
				columns: [
					{ label: "TANSAD No.", render: r => E(r.tansadNo) },
					{ label: "Reference Declaration No", render: r => E(r.reffDclrNo) },
					{ label: "MBL No", render: r => E(r.mblNo) }, { label: "HBL No", render: r => E(r.hblNo) },
					{ label: "CRN", render: (r, i) => `<a class="ji-link" data-i="${i}">${E(r.crn || r.tansadNo)}</a>` },
					{ label: "Package", cls: "num", render: r => CG.num(r.pckgNo) }, { label: "Weight", cls: "num", render: r => CG.num(r.wght) },
				],
				bind: ($h, rows) => $h.find("[data-i]").on("click", function () { d.hide(); on_pick(rows[Number($(this).attr("data-i"))]); }),
			}));
		};
		d.$body.find(".ji-search").on("click", () => load(0));
	}

	function simpl_decl($body, dclr_no) {
		const { U, T } = C();
		const is_new = !dclr_no || dclr_no === "new";
		const $head = card($body), $tabs = card($body), $act = actions($body);
		let H = {}, CN = [], VH = [];
		const ed = () => CG.EDITABLE.includes(H.prcssStatCd || "");
		const adopt = d => { H = { ...d }; CN = d.trsfSimplCntrRList || []; VH = d.trsfSimplVhclRList || []; delete H.trsfSimplCntrRList; delete H.trsfSimplVhclRList; draw(); };
		ensure_codes(["CGM0064"]).then(() => {
			if (!is_new) return U.call("simpl_declaration", { dclr_no }).then(adopt);
			$head.html(`<div class="ji-muted">${E(__("Select the cargo to transfer."))}</div><div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary" id="s-pick">${E(__("Select Cargo"))}</button></div></div>`);
			$head.find("#s-pick").on("click", () => pick_cargo_ref(r => {
				const cag = r.crn ? "import" : "export";
				U.call("simpl_init", { init_cag_tp: cag, init_no: r.crn || r.tansadNo, reff_dclr_no: r.reffDclrNo, mrn: r.mrn }, __("Loading cargo..."))
					.then(d => adopt({ ...d, mrn: r.mrn, trsfStrtDt: T.today(), trsfEndDt: T.today(), prcssStatCd: "" }));
			}));
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${E(__("List"))}</button>`).find("#d-list").on("click", () => CG.go("cgme0302001q"));
		});
		function draw() {
			const e = ed();
			const wh = (f, v) => e ? `<input class="form-control" list="sp-wh" data-f="${f}" value="${E(v)}">` : CG.wh_cell(v);
			$head.html(`<div class="ji-card-title">${E(__("Details"))}</div>` + U.form_grid([
				["Declaration No", CG.dclr_fmt(H.dclrNo)], ["Status", CG.status(H.prcssStatCd, H.prcssDtm, H.dclrNo, "STD")],
				["CRN", CG.crn_fmt(H.crn)], ["Ref Declaration No", E(H.reffDclrNo)],
				["TANSAD No.", E(H.tansadNo)], ["Transfer Type", e ? select("trsfTpCd", C().S.codes.CGM0064, H.trsfTpCd, false) : U.code("CGM0064", H.trsfTpCd), { req: true }],
				["Transfer Period", e ? `<input type="date" class="form-control ji-date" data-f="trsfStrtDt" value="${E(T.iso_date(H.trsfStrtDt))}"> ~ <input type="date" class="form-control ji-date" data-f="trsfEndDt" value="${E(T.iso_date(H.trsfEndDt))}">` : CG.period(H), { req: true, wide: true }],
				["Place of Departure", wh("dptrWrhsCd", H.dptrWrhsCd), { req: true }], ["Place of Destination", wh("dstnWrhsCd", H.dstnWrhsCd), { req: true }],
				["Customs Office", e ? input("cstmOfceCd", H.cstmOfceCd) : CSTM(H.cstmOfceCd), { req: true }], ["Transportation Reason", e ? input("trsfRsn", H.trsfRsn) : E(H.trsfRsn)],
			]) + CG.wh_list("sp-wh"));
			$tabs.html(`<div class="ji-tabs"><a class="active" data-t="c">${E(__("Container Information"))}</a><a data-t="v">${E(__("Vehicle Information"))}</a></div><div class="ji-tb"></div>`);
			$tabs.find(".ji-tabs a").on("click", function () { tab($(this).attr("data-t")); });
			tab("c");
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${E(__("List"))}</button><div class="right">
				${H.prcssStatCd === "D06" ? `<button class="btn btn-sm btn-default" id="d-hndv">${E(__("HandOver Registration"))}</button>` : ""}
				${e ? U.write_btn("Save", "btn-default", "d-save") : ""} ${e && H.dclrNo ? U.write_btn("Submit", "btn-primary", "d-sbmt") : ""}
				${e && H.dclrNo && !H.sbmtDt ? U.write_btn("Delete", "btn-danger", "d-del") : ""}</div>`);
			$act.find("#d-list").on("click", () => CG.go("cgme0302001q"));
			$act.find("#d-hndv").on("click", () => U.call("simpl_handover_check", { dclr_no: H.dclrNo }).then(r =>
				frappe.msgprint(r && r.hndvDclrNo ? __("HandOver report {0} — status {1}", [r.hndvDclrNo, r.hndvPrcssStatCdNm || r.hndvPrcssStatCd]) : __("No HandOver report has been registered for this declaration yet."))));
			const send = action => {
				const header = { ...H, ...U.read_form($head) };
				["trsfStrtDt", "trsfEndDt"].forEach(k => { if (header[k] && H[k] && !String(H[k]).includes("-")) header[k] = String(header[k]).replace(/-/g, ""); });
				confirm_call(action === "sbmt" ? "Do you want to submit?" : "Do you want to save?", "simpl_save", { header, containers: CN, vehicles: VH, action },
					__("Sending to TANeSW..."), r => { frappe.show_alert({ message: __("Done"), indicator: "green" }); CG.st.last_key = null; CG.go("cgme0302002s", (r && r.dclrNo) || H.dclrNo); });
			};
			$act.find("#d-save").on("click", () => send("save"));
			$act.find("#d-sbmt").on("click", () => send("sbmt"));
			$act.find("#d-del").on("click", () => confirm_call("Delete this declaration?", "simpl_delete", { dclr_no: H.dclrNo, prcss_stat_cd: H.prcssStatCd }, __("Deleting..."), () => CG.go("cgme0302001q")));
		}
		function tab(t) {
			$tabs.find(".ji-tabs a").removeClass("active").filter(`[data-t="${t}"]`).addClass("active");
			const $tb = $tabs.find(".ji-tb"), e = ed();
			if (t === "c") return U.grid($tb, { rows: CN, columns: SIMPL_CNTR_COLS });
			U.grid($tb, {
				rows: VH, select: e ? () => true : null,
				columns: CG.VHCL_COLS().concat(e ? [{ label: "", render: (r, i) => `<button class="btn btn-xs btn-default" data-ed="${i}">${E(__("Edit"))}</button>` }] : []),
				toolbar: e ? `<div class="ji-actions" style="margin:0 0 8px"><span></span><div class="right"><button class="btn btn-xs btn-primary" id="v-add">${E(__("Add"))}</button> <button class="btn btn-xs btn-default" id="v-del">${E(__("Delete"))}</button></div></div>` : "",
				bind: $h => {
					$h.find("#v-add").on("click", () => CG.vehicle_dialog(null, row => { VH.push(row); tab("v"); }));
					$h.find("[data-ed]").on("click", function () { const i = Number($(this).attr("data-ed")); CG.vehicle_dialog(VH[i], row => { VH[i] = row; tab("v"); }); });
					$h.find("#v-del").on("click", () => { const sel = new Set($h.selected()); VH = VH.filter(r => !sel.has(r)); tab("v"); });
				},
			});
		}
	}

	function pick_simpl_target(cag, on_pick) {
		const { U, T } = C();
		const f = { srch_rgsr_dt_from: T.add_days(T.today(), -7), srch_rgsr_dt_to: T.today() };  // portal: last 7 days
		const d = U.modal(cag === "STA" ? "Declaration to Amend" : "Declaration to Cancel", `<div class="ji-s">${U.form_grid([
			["Date of Register", U.date_range("srch_rgsr_dt_from", "srch_rgsr_dt_to", f), { req: true, wide: true }],
			[lbl_select("srch_no_tp", [["dclrNo", "Declaration No"], ["crn", "CRN"], ["cntrNo", "Container No."]], "dclrNo"), input("srch_no", ""), { wide: true }],
		])}<div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary ji-search">${E(__("Search"))}</button></div></div></div><div class="ji-g mt-2"></div>`, "extra-large");
		U.bind_range(d.$body);
		const $g = d.$body.find(".ji-g");
		const load = (page = 0) => {
			U.loading($g, 7);
			U.call("simpl_amd_cncl_targets", { cag_dclr_tp_cd: cag, ...U.read_form(d.$body.find(".ji-s")), page, size: 10 }).then(res => U.grid($g, {
				rows: res.content, meta: res.page, size: 10, onPage: load, onSize: () => load(0),
				columns: [{ label: "Declaration No", render: (r, i) => `<a class="ji-link" data-i="${i}">${CG.dclr_fmt(r.dclrNo)}</a>` },
					{ label: "CRN", render: r => CG.crn_fmt(r.crn) }, { label: "Transfer Type", render: r => U.code("CGM0064", r.trsfTpCd) },
					{ label: "Transfer Period", render: CG.period }, { label: "Departure", render: r => CG.wh_cell(r.dptrWrhsCd) }, { label: "Destination", render: r => CG.wh_cell(r.dstnWrhsCd) }],
				bind: ($h, rows) => $h.find("[data-i]").on("click", function () { d.hide(); on_pick(rows[Number($(this).attr("data-i"))]); }),
			}));
		};
		d.$body.find(".ji-search").on("click", () => load(0));
		load(0);
	}

	function simpl_amd($body, no) {
		const { U } = C();
		const is_new = !no || no === "new";
		const $info = card($body), $head = card($body), $tabs = card($body), $act = actions($body);
		let H = {}, INFO = {}, BV = [], AV = [], CN = [], ITEMS = [];
		const ed = () => CG.EDITABLE.includes(H.prcssStatCd || "");
		const adopt = d => {
			INFO = { ...d }; const amd = d.cgmeDclrAmdMDto || {};
			H = { ...H, ...amd, reffDclrNo: d.dclrNo || H.reffDclrNo };
			if (amd.dclrAmdPnltD && amd.dclrAmdPnltD.pnltImpsYn === "Y") Object.assign(H, { pnltImpsYn: "Y", pnltUsdAmt: amd.dclrAmdPnltD.pnltUsdAmt, bllNo: amd.dclrAmdPnltD.bllNo });
			const orig = (d.trsfSimplVhclRList || []).map(r => ({ ...r, dtlAmdTpCd: "O" }));
			const has = (d.bfVhclAmdList || []).length || (d.afVhclAmdList || []).length;
			BV = has ? d.bfVhclAmdList : orig; AV = has ? d.afVhclAmdList : orig.map(r => ({ ...r }));
			CN = d.trsfSimplCntrRList || []; ITEMS = amd.dclrAmdItmRList || [];
			draw();
		};
		ensure_codes(["CGM0064"]).then(() => {
			if (!is_new) return U.call("simpl_amd", { amd_dclr_no: no }).then(adopt);
			$info.html(`<div class="ji-muted">${E(__("Select the approved simple transfer to amend."))}</div><div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary" id="a-pick">${E(__("Select Declaration"))}</button></div></div>`);
			$info.find("#a-pick").on("click", () => pick_simpl_target("STA", t => U.call("simpl_amd_new", { dclr_no: t.dclrNo }, __("Loading...")).then(adopt)));
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${E(__("List"))}</button>`).find("#d-list").on("click", () => CG.go("cgme0302011q"));
		});
		function draw() {
			const e = ed();
			$info.html(`<div class="ji-card-title">${E(__("Declaration"))}</div>` + U.form_grid([
				["Before Declaration No", CG.dclr_fmt(INFO.dclrNo)], ["CRN", E(INFO.crn)],
				["Transfer Period", CG.period(INFO)], ["Transfer Type", U.code("CGM0064", INFO.trsfTpCd)],
				["Place of Departure", CG.wh_cell(INFO.dptrWrhsCd)], ["Place of Destination", CG.wh_cell(INFO.dstnWrhsCd)],
				["Customs Office", CSTM(INFO.cstmOfceCd)], ["Transportation Reason", E(INFO.trsfRsn)],
			]));
			$head.html(`<div class="ji-card-title">${E(__("Amendment"))}</div>` + U.form_grid([
				["Amend Declaration No", CG.dclr_fmt(H.amdDclrNo)], ["Status", CG.status(H.prcssStatCd, H.prcssDtm, H.amdDclrNo, "STA")],
				["Amendment Reason", e ? `<textarea class="form-control" data-f="amdRsn">${E(H.amdRsn)}</textarea>` : E(H.amdRsn), { req: true, wide: true }],
				...CG.penalty_rows(H),
			]) + (H.amdDclrNo && ITEMS.length ? `<div class="ji-it mt-2"></div>` : ""));
			if (H.amdDclrNo && ITEMS.length) U.grid($head.find(".ji-it"), { title: "Modification", rows: ITEMS, columns: [
				{ label: "Modify Item", render: r => E(r.amdItmNm) }, { label: "Before", render: r => E(r.bfItmCn) },
				{ label: "After", render: (r, i) => e ? `<input class="form-control" data-item="${i}" value="${E(r.afItmCn)}">` : E(r.afItmCn) }],
			bind: $h => $h.on("change", "[data-item]", function () { ITEMS[Number($(this).attr("data-item"))].afItmCn = $(this).val(); }) });
			$tabs.html(`<div class="ji-tabs"><a class="active" data-t="b">${E(__("Vehicle Information (Before)"))}</a><a data-t="a">${E(__("Vehicle Information (After)"))}</a><a data-t="c">${E(__("Container Information"))}</a></div><div class="ji-tb"></div>`);
			$tabs.find(".ji-tabs a").on("click", function () { tab($(this).attr("data-t")); });
			tab("a");
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${E(__("List"))}</button><div class="right">
				${e ? U.write_btn("Save", "btn-default", "d-save") : ""} ${e && H.amdDclrNo ? U.write_btn("Submit", "btn-primary", "d-sbmt") : ""}
				${e && H.amdDclrNo && !H.sbmtDt ? U.write_btn("Delete", "btn-danger", "d-del") : ""}</div>`);
			$act.find("#d-list").on("click", () => CG.go("cgme0302011q"));
			const send = action => confirm_call(action === "sbmt" ? "Do you want to submit?" : "Do you want to save?", "simpl_amd_save",
				{ header: { ...H, ...U.read_form($head) }, info: INFO, items: ITEMS, bf_vehicles: BV, af_vehicles: AV, containers: CN, action }, __("Sending to TANeSW..."),
				r => { frappe.show_alert({ message: __("Done"), indicator: "green" }); const n = (r && (r.amdDclrNo || (r.cgmeDclrAmdMDto || {}).amdDclrNo)) || H.amdDclrNo; CG.st.last_key = null; CG.go("cgme0302012s", n); });
			$act.find("#d-save").on("click", () => send("save"));
			$act.find("#d-sbmt").on("click", () => send("sbmt"));
			$act.find("#d-del").on("click", () => confirm_call("Delete this amendment?", "simpl_amd_delete", { header: H }, __("Deleting..."), () => CG.go("cgme0302011q")));
		}
		function tab(t) {
			$tabs.find(".ji-tabs a").removeClass("active").filter(`[data-t="${t}"]`).addClass("active");
			const $tb = $tabs.find(".ji-tb"), e = ed();
			const amd_col = { label: "Amendment Type", render: r => E({ O: "", A: __("Add"), C: __("Change"), D: __("Delete") }[r.dtlAmdTpCd] ?? r.dtlAmdTpCd) };
			if (t === "c") return U.grid($tb, { rows: CN, columns: SIMPL_CNTR_COLS });
			if (t === "b") return U.grid($tb, { rows: BV, columns: CG.VHCL_COLS() });
			U.grid($tb, {
				rows: AV, row_cls: r => `amd-${r.dtlAmdTpCd}`,
				columns: [amd_col].concat(CG.VHCL_COLS()).concat(e ? [{ label: "", render: (r, i) => `<button class="btn btn-xs btn-default" data-ed="${i}">${E(__("Edit"))}</button> <button class="btn btn-xs btn-default" data-tg="${i}">${E(r.dtlAmdTpCd === "D" ? __("Undo") : __("Delete"))}</button>` }] : []),
				toolbar: e ? `<div class="ji-actions" style="margin:0 0 8px"><span></span><div class="right"><button class="btn btn-xs btn-primary" id="v-add">${E(__("Add"))}</button></div></div>` : "",
				bind: $h => {
					$h.find("#v-add").on("click", () => CG.vehicle_dialog(null, row => { AV.push({ ...row, dtlAmdTpCd: "A" }); tab("a"); }));
					$h.find("[data-ed]").on("click", function () { const i = Number($(this).attr("data-ed")); CG.vehicle_dialog(AV[i], row => { AV[i] = { ...row, dtlAmdTpCd: AV[i].dtlAmdTpCd === "A" ? "A" : "C" }; tab("a"); }); });
					$h.find("[data-tg]").on("click", function () { const i = Number($(this).attr("data-tg")); const r = AV[i]; r.dtlAmdTpCd === "A" ? AV.splice(i, 1) : (r.dtlAmdTpCd = r.dtlAmdTpCd === "D" ? "O" : "D"); tab("a"); });
				},
			});
		}
	}

	function simpl_cncl($body, no) {
		const { U } = C();
		const is_new = !no || no === "new";
		const $info = card($body), $head = card($body), $tabs = card($body), $act = actions($body);
		let H = {}, INFO = {}, CN = [];
		const ed = () => CG.EDITABLE.includes(H.prcssStatCd || "");
		const adopt = d => {
			INFO = { ...d }; const c = d.cgmeDclrCnclMDto || {};
			H = { ...H, ...c, reffDclrNo: d.dclrNo || H.reffDclrNo, crn: d.crn };
			if (c.dclrAmdPnltD && c.dclrAmdPnltD.pnltImpsYn === "Y") Object.assign(H, { pnltImpsYn: "Y", pnltUsdAmt: c.dclrAmdPnltD.pnltUsdAmt, bllNo: c.dclrAmdPnltD.bllNo });
			CN = d.trsfSimplCntrRList || []; draw();
		};
		ensure_codes(["CGM0064"]).then(() => {
			if (!is_new) return U.call("simpl_cncl", { cncl_dclr_no: no }).then(adopt);
			$info.html(`<div class="ji-muted">${E(__("Select the approved simple transfer to cancel."))}</div><div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary" id="c-pick">${E(__("Select Declaration"))}</button></div></div>`);
			$info.find("#c-pick").on("click", () => pick_simpl_target("STC", t => U.call("simpl_cncl_init", { dclr_no: t.dclrNo }, __("Loading...")).then(adopt)));
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${E(__("List"))}</button>`).find("#d-list").on("click", () => CG.go("cgme0302021q"));
		});
		function draw() {
			const e = ed();
			$info.html(`<div class="ji-card-title">${E(__("Declaration"))}</div>` + U.form_grid([
				["Before Declaration No", CG.dclr_fmt(INFO.dclrNo)], ["CRN", E(INFO.crn)],
				["Transfer Period", CG.period(INFO)], ["Transfer Type", U.code("CGM0064", INFO.trsfTpCd)],
				["Place of Departure", CG.wh_cell(INFO.dptrWrhsCd)], ["Place of Destination", CG.wh_cell(INFO.dstnWrhsCd)],
			]));
			$head.html(`<div class="ji-card-title">${E(__("Cancellation"))}</div>` + U.form_grid([
				["Cancel Declaration No", CG.dclr_fmt(H.cnclDclrNo)], ["Status", CG.status(H.prcssStatCd, H.prcssDtm, H.cnclDclrNo, "STC")],
				["Cancellation Reason", e ? `<textarea class="form-control" data-f="cnclCn">${E(H.cnclCn)}</textarea>` : E(H.cnclCn), { req: true, wide: true }],
				...CG.penalty_rows(H),
			]));
			U.grid($tabs, { title: "Container Information", rows: CN, columns: SIMPL_CNTR_COLS });
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${E(__("List"))}</button><div class="right">
				${e ? U.write_btn("Save", "btn-default", "d-save") : ""} ${e && H.cnclDclrNo ? U.write_btn("Submit", "btn-primary", "d-sbmt") : ""}
				${e && H.cnclDclrNo && !H.sbmtDt ? U.write_btn("Delete", "btn-danger", "d-del") : ""}</div>`);
			$act.find("#d-list").on("click", () => CG.go("cgme0302021q"));
			const send = action => confirm_call(action === "sbmt" ? "Do you want to submit?" : "Do you want to save?", "simpl_cncl_save",
				{ header: { ...H, ...U.read_form($head) }, containers: CN, action }, __("Sending to TANeSW..."),
				r => { frappe.show_alert({ message: __("Done"), indicator: "green" }); const n = (r && (r.cnclDclrNo || (r.cgmeDclrCnclMDto || {}).cnclDclrNo)) || H.cnclDclrNo; CG.st.last_key = null; CG.go("cgme0302022s", n); });
			$act.find("#d-save").on("click", () => send("save"));
			$act.find("#d-sbmt").on("click", () => send("sbmt"));
			$act.find("#d-del").on("click", () => confirm_call("Delete this cancellation?", "simpl_cncl_delete", { cncl_dclr_no: H.cnclDclrNo }, __("Deleting..."), () => CG.go("cgme0302021q")));
		}
	}

	// =================================================================== Carry-In / Carry-Out shared
	function crio_list($body, kind) {
		const { U, T } = C();
		const cri = kind === "cri";
		const tp = cri ? "CGM0062" : "CGM0063";
		ensure_codes([tp, "CGM0093"]).then(() => CG.list_screen($body, cri ? "cgme0401001q" : "cgme0401008q",
			// Portal default: today ~ +1 week.
			() => ({ srch_aprv_dt_from: T.today(), srch_aprv_dt_to: T.add_days(T.today(), 7), srch_rpt_stat: ["N", "P", "Y"], srch_exit_cfrm_yn: "" }),
			f => [
				["Approval Date", U.date_range("srch_aprv_dt_from", "srch_aprv_dt_to", f), { req: true, wide: true }],
				["Cargo Reference No", upper("srch_crn", f.srch_crn)], ["Reference No", input("srch_reff_no", f.srch_reff_no)],
			].concat(cri ? [["Container No.", upper("srch_cntr_no", f.srch_cntr_no)], ["Barcode (Scan Doc)", input("srch_bcode_no", f.srch_bcode_no)]] : [])
				.concat([
					[cri ? "Carry-In Type" : "Carry-Out Type", select(cri ? "srch_cri_tp_cd" : "srch_cro_tp_cd", C().S.codes[tp], f[cri ? "srch_cri_tp_cd" : "srch_cro_tp_cd"])],
					["Processing Unit", select("srch_crio_prcss_ut_cd", C().S.codes.CGM0093, f.srch_crio_prcss_ut_cd)],
					["Status", U.checks("srch_rpt_stat", STATUS_RPT, f.srch_rpt_stat) + (cri ? "" : `<div class="ji-checks" style="margin-top:4px">${[["", "All"], ["N", "Not Exit"], ["Y", "Exit Confirm"]].map(([v, l]) =>
						`<label><input type="radio" name="cro-exit" data-f="srch_exit_cfrm_yn" value="${v}" ${(f.srch_exit_cfrm_yn || "") === v ? "checked" : ""}> ${E(__(l))}</label>`).join("")}</div>`), { wide: true, req: true }],
				]),
			[
				{ label: "Cargo Reference No / M B/L No", render: r => r.crn ? CG.crn_fmt(r.crn) : E(r.mblNo) },
				{ label: cri ? "Carry-In Type" : "Carry-Out Type", render: r => U.code(tp, cri ? r.criTpCd : r.croTpCd) },
				{ label: "Reference No.", render: (r, i) => `<a class="ji-link" data-i="${i}">${E(cri ? r.criBaseNo : r.croBaseNo)}</a>` },
			].concat(cri ? [] : [{ label: "Customs Value (TZS)", cls: "num", render: r => CG.num(r.cstmAmt ?? r.cstmVal) }]).concat([
				{ label: "Approval Date", render: r => CG.fd(r.aprvDt) },
				{ label: "Processing Unit", render: r => U.code("CGM0093", r.crioPrcssUtCd) },
				{ label: "Target", cls: "num", render: r => E(r.trgtCnt) }, { label: "Registration", cls: "num", render: r => E(r.rgsrCnt) },
				{ label: "Submitted", cls: "num", render: r => E(r.sbmtCnt) }, { label: "Approved", cls: "num", render: r => E(r.aprvCnt) },
				{ label: "Status", render: r => E(r.rptStatNm) },
			]).concat(cri ? [{ label: "Comment", render: (r, i) => (r.criRprtYn !== "Y" && Number(r.trgtCnt) > Number(r.sbmtCnt)) ? editable_input("cm", i, r.dcltOpinCn) : E(r.dcltOpinCn) }] : []),
			cri ? "cri_list" : "cro_list",
			{
				validate: f => (f.srch_rpt_stat || []).length ? true : (frappe.show_alert({ message: __("Select at least one status"), indicator: "orange" }), false),
				select: cri ? r => r.criRprtYn !== "Y" && Number(r.trgtCnt) > Number(r.sbmtCnt) : null,
				toolbar: cri ? `${C().U.write_btn("Submit Comments", "btn-default btn-xs", "cg-cm")} <button class="btn btn-xs btn-default" id="cg-bulk">${E(__("Bulk Carry-In"))}</button>` : "",
				bind: ($h, rows, reload) => {
					$h.on("change", ".cm", function () { rows[Number($(this).attr("data-i"))].dcltOpinCn = $(this).val(); });
					$h.find("[data-i].ji-link").on("click", function () {
						const r = rows[Number($(this).attr("data-i"))];
						const d = x => x || "-";
						if (cri) return r.mblNo ? CG.go("cgme0401003s", d(r.hblNo), r.mblNo, r.wrhsCd, r.criBaseNo)
							: CG.go("cgme0401002s", r.crn, r.wrhsCd, r.criBaseNo);
						U.call("cro_gate_check", { row: r }, __("Checking gate confirmation...")).then(x => {
							const g = x && x.croBaseNo ? { ...r, ...x } : r;
							if (g.mblNo) CG.go("cgme0401017s", g.croBaseNo, g.mblNo, d(g.hblNo), g.wrhsCd, g.croTpCd);
							else CG.go("cgme0401009s", g.croBaseNo, g.crn, g.wrhsCd, d(g.mrn));
						});
					});
					$h.find("#cg-bulk").on("click", () => CG.go("cgme0401005q"));
					$h.find("#cg-cm").on("click", () => {
						const sel = $h.selected();
						if (!sel.length) return frappe.show_alert({ message: __("Select rows to submit"), indicator: "orange" });
						confirm_call("Do you want to submit?", "cri_report_comments", { form: CG.st.store.cgme0401001q.form, rows: sel }, __("Submitting..."), reload);
					});
				},
			}));
	}

	// unit-specific grid definitions. edit: fields the portal lets you type in.
	const W_E = ["Truck Weight (empty)", "emptWght", "n"], W_L = ["Truck Weight (loaded)", "loadWght", "n"];
	const CRIO_UNITS = {
		cri: {
			B: { list: "wrhsCriBlList", cols: [["Report No", "dclrNo"], ["Carry-In Date", "criDt", "d"], ["Packages", "criPckgNo", "n", "pckgUtCd"], ["Weight", "criWght", "n", "wghtUtCd"]], edit: ["criPckgNo", "criWght"] },
			V: { list: "wrhsCriVhclList", cols: [["Report No.", "dclrNo"], ["Carry-In Date", "criDt", "d"], ["Driver", "drvrNm"], ["License No.", "drvrLcneNo"], ["Trip No.", "trpNo"], ["Driving Type", "drivTpCd"], ["Vehicle No.", "vhclNo"], ["Chassis No.", "chssNo"], ["Trailer / Semi-Trailer", "trlrNo"], ["Container No.", "cntrInfo"]], edit: [] },
			C: { list: "wrhsCriCntrList", cols: [["Report No", "dclrNo"], ["Carry-In Date", "criDt", "d"], ["Container No.", "cntrNo"], ["Container Size", "cntrSizeCd"], ["Seal No#1", "sealNo1"], ["Seal No#2", "sealNo2"], ["Seal No#3", "sealNo3"], ["Package / Weight", "cntrPckgNo", "n", "pckgUtCd"]], edit: [] },
			I: { list: "wrhsCriItmList", cols: [["Report No", "dclrNo"], ["Carry-In Date", "criDt", "d"], ["HS Code", "hsCd"], ["SPCD", "spcd"], ["Description of Goods", "godsDesc"], ["Quantity", "criQty", "n"], ["Weight", "criWght", "n"]], edit: [] },
		},
		cro: {
			B: { list: "wrhsCroBlLst", cols: [["Report No", "dclrNo"], ["Driver Name", "drvrNm"], ["Licence No.", "drvrLcneNo"], ["Carry-Out Date", "croDt", "d"], ["Vehicle No.", "vhclNo"], ["Packages", "croPckgNo", "n", "pckgUtCd"], W_E, W_L, ["Carry-Out Weight", "croWght", "n", "wghtUtCd"]], edit: ["drvrNm", "drvrLcneNo", "croDt", "vhclNo", "croPckgNo", "emptWght", "loadWght"] },
			// 009S Vehicle unit: the portal only shows/edits truck weights for bulk cargo without escrow oil (schema jje);
			// otherwise (schema Pje) only the date and comment are editable. vehicle_unit() picks between them.
			V: { list: "wrhsCroVhclLst", cols: [["Report No", "dclrNo"], ["Carry-Out Date", "croDt", "d"], ["Driver", "drvrNm"], ["Licence No.", "drvrLcneNo"], ["Container No.", "cntrInfo"], ["Trip No", "trpNo"], ["Driving Type", "drivTpCd"], ["Vehicle No.", "vhclNo"], ["Chassis No.", "chssNo"], ["Trailer / Semi-Trailer", "trlrNo"]], edit: ["croDt"] },
			C: { list: "wrhsCroCntrLst", cols: [["Report No", "dclrNo"], ["Carry-Out Date", "croDt", "d"], ["Container No.", "cntrNo"], ["Container Size", "cntrSizeCd"], ["Seal No#1", "sealNo1"], ["Seal No#2", "sealNo2"], ["Seal No#3", "sealNo3"], ["Package / Weight", "cntrPckgNo", "n", "pckgUtCd"]], edit: ["croDt"] },
			I: { list: "wrhsCroItmLst", cols: [["Report No", "dclrNo"], ["Carry-Out Date", "croDt", "d"], ["HS Code", "hsCd"], ["SPCD", "spcd"], ["Description of Goods", "godsDesc"], ["Quantity", "aprvQty", "n"], ["Weight", "aprvWght", "n"]], edit: ["croDt"] },
		},
		// B/L based screens (003S / 017S): only B/L and Container units exist.
		cri_bl: {
			B: { list: "wrhsCriBlList", cols: [["Report No", "dclrNo"], ["Carry-In Date", "criDt", "d"], ["Packages", "criPckgNo", "n", "pckgUtCd"], ["Weight", "criWght", "n", "wghtUtCd"], ["Checked (Gate)", "chkDt", "d"], ["Analysis Verdict", "scnrRdngRsltCd"], ["Inspection Verdict", "scnrInscRsltCd"]], edit: ["criPckgNo", "criWght"] },
			C: { list: "wrhsCriCntrList", cols: [["Container No.", "cntrNo"], ["Report No", "dclrNo"], ["Carry-In Date", "criDt", "d"]], edit: [] },
		},
		cro_bl: {
			B: { list: "wrhsCroBlLst", cols: [["Report No", "dclrNo"], ["Driver Name", "drvrNm"], ["Licence No.", "drvrLcneNo"], ["Carry-Out Date", "croDt", "d"], ["Vehicle No.", "vhclNo"], ["Packages", "croPckgNo", "n", "pckgUtCd"], W_E, ["Carry-Out Weight", "croWght", "n", "wghtUtCd"], W_L], edit: ["drvrNm", "drvrLcneNo", "croDt", "vhclNo", "croPckgNo", "emptWght", "croWght", "loadWght"] },
			C: { list: "wrhsCroCntrLst", cols: [["Report No", "dclrNo"], ["Carry-Out Date", "croDt", "d"], ["Container No.", "cntrNo"], ["Container Size", "cntrSizeCd"], ["Seal No#1", "sealNo1"], ["Seal No#2", "sealNo2"], ["Seal No#3", "sealNo3"], ["Package / Weight", "cntrPckgNo", "n", "pckgUtCd"]], edit: ["croDt"] },
		},
	};
	function unit_def(kind, unit, H) {
		const def = (CRIO_UNITS[kind] || {})[unit] || CRIO_UNITS[kind].B;
		if (kind === "cro" && unit === "V" && H.bulkYn === "Y" && H.im4EscrowOilYn === "N")
			return { ...def, cols: def.cols.slice(0, 2).concat([["Carry-Out Weight", "croWght", "n", "wghtUtCd"]], def.cols.slice(2, 4), [W_E], def.cols.slice(5, 7), [W_L], def.cols.slice(7)), edit: ["croDt", "emptWght", "loadWght"] };
		if (kind === "cro_bl" && unit === "B" && H.trptModeCd === "40")  // weights are not typed for this transport mode
			return { ...def, edit: def.edit.filter(f => !["emptWght", "loadWght"].includes(f)) };
		return def;
	}

	// CGME-0401-007Q driver licence popup: pick a row to fill the barcode.
	function driver_popup(lic, on_pick) {
		const { U } = C();
		const d = U.modal("Driver License", `<div class="ji-g"></div>`, "large");
		const $g = d.$body.find(".ji-g");
		const st = { size: 10 };
		const load = page => { U.loading($g, 5); U.call("cri_driver_lookup", { drvr_lcne_no: lic, page, size: st.size }).then(res => U.grid($g, {
			columns: [
				{ label: "Container No / Chassis No", render: r => E(r.cntrNo) }, { label: "Driver Name", cls: "left", render: r => E(r.drvrNm) },
				{ label: "Vehicle Registration No", render: r => E(r.vhclNo) },
				{ label: "Barcode", render: (r, i) => `<a class="ji-link" data-i="${i}">${E(r.bcodeNo)}</a>` },
			], rows: res.content, meta: res.page, size: st.size, onPage: load, onSize: z => { st.size = z; load(0); },
			bind: ($h, rows) => $h.find("[data-i]").on("click", function () { d.hide(); on_pick(rows[Number($(this).attr("data-i"))]); }),
		})); };
		load(0);
	}

	// kind: cri | cro (import/transfer reports, 002S / 009S) or cri_bl | cro_bl (B/L based, 003S / 017S).
	function crio_detail($body, kind, args) {
		const { U, T } = C();
		const cri = kind.startsWith("cri"), bl = kind.endsWith("_bl");
		const M = {  // server methods per screen
			cri: { save: "cri_save", sbmt: "cri_submit", del: "cri_delete", list: "cgme0401001q" },
			cro: { save: "cro_save", sbmt: "cro_submit", del: "cro_delete", list: "cgme0401008q" },
			cri_bl: { save: "cri_bl_save", sbmt: "cri_bl_submit", del: "cri_bl_delete", list: "cgme0401001q" },
			cro_bl: { save: "cro_bl_save", sbmt: "cro_bl_submit", del: "cro_bl_delete", list: "cgme0401008q" },
		}[kind];
		const $head = card($body), $grid = card($body), $cd = card($body).hide();
		const $rc = kind === "cri" ? card($body).hide() : $();  // "Receive into ERP" (icd_tz Container Reception)
		const $act = actions($body);
		let H = {}, ROWS = [], DRIVERS = [], VCNTR = "";
		const RC = { on: false, receive: true, clerk: "", def_loc: "", locs: {}, ctl: {} };
		if (kind === "cri") U.call("tanesw_integration.icd_link.carry_in_context").then(c => {
			RC.on = !!(c && c.enabled); RC.clerk = RC.clerk || (c && c.default_clerk) || ""; if (H.crn) draw_receive();
		}).catch(() => {});
		const arg = i => (args[i] === "-" ? "" : args[i]);
		const load = () => {
			const call = {
				cri: () => U.call("cri_detail", { crn: arg(0), wrhs_cd: arg(1), cri_base_no: arg(2) }),
				cro: () => U.call("cro_detail", { cro_base_no: arg(0), crn: arg(1), wrhs_cd: arg(2), mrn: arg(3) }),
				cri_bl: () => U.call("cri_bl_detail", { hbl_no: arg(0), mbl_no: arg(1), wrhs_cd: arg(2), cri_base_no: arg(3) }),
				cro_bl: () => U.call("cro_bl_detail", { cro_base_no: arg(0), mbl_no: arg(1), hbl_no: arg(2), wrhs_cd: arg(3), cro_tp_cd: arg(4) }),
			}[kind];
			return call().then(adopt);
		};
		const all_lists = () => [].concat(...["cri", "cro", "cri_bl", "cro_bl"].map(k => Object.values(CRIO_UNITS[k]).map(u => u.list)));
		const adopt = d => {
			if (!d || !Object.keys(d).length) { $head.html(`<div class="text-danger">${E(__("No data found."))}</div>`); return; }
			H = { ...d };
			const unit = H.crioPrcssUtCd || "B";
			ROWS = (d[unit_def(kind, unit, H).list] || []).map(r => ({ ...r }));
			all_lists().forEach(l => delete H[l]);
			draw();
		};
		ensure_codes([cri ? "CGM0062" : "CGM0063", "CGM0093"]).then(load).catch(() => $head.html(`<div class="text-danger">${E(__("Failed to load"))}</div>`));
		if (kind === "cro_bl") U.call("cro_bl_driver_suggestions", { mbl_no: arg(1), hbl_no: arg(2) }).then(l => { DRIVERS = l || []; }).catch(() => {});

		const editable_row = r => EDIT_ROW(r.prcssStatCd);
		// 003S: a B/L row can be ticked only once the gate check allows it (portal checkbox rule).
		const gate_ok = r => r.gateInCheckCoYn === "N" || (r.gateInCheckCoYn === "Y" && r.entryCfrmYn === "N"
			&& (["C", "R"].includes(r.scnrRdngRsltCd) || r.scnrInscRsltCd === "C"));
		const selectable = r => r.addRow === "I" || (editable_row(r) && (kind !== "cri_bl" || gate_ok(r)));

		function header_fields(unit) {
			// Portal 002S "Details" block (the barcode / driver-licence search sits in its own card above).
			if (kind === "cri") return [
				["Reference No.", E(H.criBaseNo)], ["Approval Date", CG.fd(H.aprvDt)],
				["Carry-In Type", U.code("CGM0062", H.criTpCd)], ["Expected Carry-in Date", CG.fd(H.trsfEndDt)],
				["Cargo Ref No", CG.crn_fmt(H.crn)], ["Warehouse", CG.wh_cell(H.wrhsCd, H.wrhsNm)],
				["Number of Packages", `${CG.num(H.criXptdPckgNo)} ${E(H.pckgUtCd || "")}`], ["Net Weight", `${CG.num(H.criXptdWght)} ${E(H.wghtUtCd || "")}`],
				["Description of Goods", E(H.godsDesc), { wide: true }],
			];
			if (kind === "cri_bl") return [
				["Barcode (Scan Doc)", `${input("srchBcodeNo", "")}<button class="btn btn-xs btn-primary" id="h-bc">${E(__("Search"))}</button>`, { wide: true }],
				["Verdict Source", E(H.rdngTp)], ["Reference No", E(H.expCriBaseNo || H.criBaseNo)],
				["Approval Date", CG.fd(H.aprvDt)], ["Carry-In Type", U.code("CGM0062", H.criTpCd)],
				["Expected Carry-In Date", CG.fd(H.trsfEndDt)], ["B/L No", `${E(H.mblNo)}${H.hblNo && H.hblNo !== H.mblNo ? ` / ${E(H.hblNo)}` : ""}`],
				["Processing Unit", U.code("CGM0093", unit)], ["Warehouse", CG.wh_cell(H.wrhsCd, H.wrhsNm)],
				["Number of Packages", `${CG.num(H.criXptdPckgNo)} ${E(H.pckgUtCd || "")}`], ["Net Weight", `${CG.num(H.criXptdWght)} ${E(H.wghtUtCd || "")}`],
			];
			const rows = [
				["Reference No.", E(H.croBaseNo)], ["Approval Date", CG.fd(H.aprvDt)],
				["Carry-Out Type", U.code("CGM0063", H.croTpCd)], ["Country Of Destination", E(H.cntyCd)],
				["Cargo Ref No", CG.crn_fmt(H.crn)],
				["Processing Unit", kind === "cro_bl" ? U.code("CGM0093", unit) : `${U.code("CGM0093", unit)} ${C().S.ctx.write_enabled && ROWS.some(r => editable_row(r)) ? `<select class="form-control" id="h-unit" style="width:auto;display:inline-block;height:26px">${Object.entries(C().S.codes.CGM0093 || {}).map(([k, n]) => `<option value="${E(k)}" ${k === unit ? "selected" : ""}>${E(n)}</option>`).join("")}</select> ${U.write_btn("Change", "btn-xs btn-default", "h-chg")}` : ""}`],
				["M B/L No", E(H.mblNo)], ["H B/L No", E(H.hblNo)],
				["Number of Packages", `${CG.num(H.aprvPckgNo)} ${E(H.pckgUtCd || "")}`], ["Net Weight", `${CG.num(H.aprvWght)} ${E(H.wghtUtCd || "")}`],
				["Description of Goods", E(H.godsDesc), { wide: true }], ["Customs Value", CG.num(H.cstmAmt)],
			];
			if (kind === "cro_bl") rows.push(["Total Approved Carry-Out Packages", `${CG.num(H.totCatPckg)} ${E(H.pckgUtCd || "")}`], ["Total Approved Carry-Out Weight", `${CG.num(H.totCatWght)} ${E(H.wghtUtCd || "")}`]);
			if (kind === "cro" && H.im4EscrowOilYn === "Y") rows.push(  // IM4 escrow oil: portal shows the approved/total quantity block
				["Approved Carry-Out Quantity", `${CG.num(H.aprvCroQty)} ${E(H.croQtyUtCd || "")}`], ["Approved Carry-Out Weight", `${CG.num(H.aprvCroWght)} ${E(H.croWghtUtCd || "")}`],
				["Approved Item Bond Value", CG.num(H.aprvBondVal)], ["Total Carry-Out Quantity", `${CG.num(H.totCroQty)} ${E(H.croQtyUtCd || "")}`],
				["Total Carry-Out Weight", `${CG.num(H.totCroWght)} ${E(H.croWghtUtCd || "")}`], ["Total Item Bond Value", CG.num(H.totBondVal)]);
			if (kind === "cro" && unit === "V" && H.bulkYn === "Y") rows.push(["Total Approved Weight (Vehicles)", `${CG.num(H.totVhclAprvWght)} ${E(H.wghtUtCd || "")}`]);
			rows.push(["Remain Package", `${CG.num(H.stckPckgNo)} ${E(H.pckgUtCd || "")}`], ["Remain Weight", `${CG.num(H.stckWght)} ${E(H.wghtUtCd || "")}`]);
			return rows;
		}

		// Truck weights -> carry-out weight, as the portal computes it.
		function cro_weight(r, k) {
			const blank = x => x === null || x === "" || x === undefined;
			if (k === "croWght") { if (Number(r.croWght) > 0) { r.emptWght = null; r.loadWght = null; } return; }
			if (blank(r.emptWght) || blank(r.loadWght)) { r.croWght = null; return; }
			const diff = Number(r.loadWght) - Number(r.emptWght);
			if (kind === "cro_bl") r.croWght = diff > 0 ? diff : null;
			else r.croWght = Number(r.emptWght) === 0 ? Number(r.loadWght) : (diff > 0 ? diff : Number(r.loadWght));
		}

		function draw() {
			const unit = H.crioPrcssUtCd || "B";
			const def = unit_def(kind, unit, H);
			const srch = kind === "cri" ? `<div class="ji-s mb-2">${U.form_grid([
				["Bar code(Scan T Doc)", input("srchBcodeNo", "")],
				["Driver License No", `${upper("srchDrvrLcneNo", "")}<button class="btn btn-xs btn-default" id="h-dl" title="${E(__("Find the barcode by driver licence"))}">${frappe.utils.icon("search", "xs")}</button>`],
			])}<div class="ji-actions"><button class="btn btn-sm" id="h-rst">${E(__("Reset"))}</button><div class="right"><button class="btn btn-sm btn-primary" id="h-bc">${E(__("Search"))}</button></div></div></div>` : "";
			$head.html(srch + `<div class="ji-card-title">${E(__(kind === "cri" ? "Details" : (cri ? "Carry-In Report" : "Carry-out Report")))}${bl ? ` <span class="ji-muted">(${E(__("B/L based"))})</span>` : ""}</div>` + U.form_grid(header_fields(unit)));
			$head.find("#h-rst").on("click", () => $head.find(".ji-s input").val(""));
			const bc = () => $head.find('[data-f="srchBcodeNo"]'), dl = () => $head.find('[data-f="srchDrvrLcneNo"]');
			const bc_search = () => (kind === "cri_bl"
				? U.call("cri_bl_search", { srch_bcode_no: bc().val() }, __("Searching..."))
				: U.call("cri_search", { crn: H.crn, wrhs_cd: H.wrhsCd, cri_base_no: H.criBaseNo, srch_bcode_no: bc().val(), srch_drvr_lcne_no: dl().val() }, __("Searching..."))).then(adopt);
			$head.find("#h-bc").on("click", bc_search);
			bc().on("keydown", e => { if (e.key === "Enter") bc_search(); });  // barcode scanners send Enter
			$head.find("#h-dl").on("click", () => {
				const lic = (dl().val() || "").trim();
				if (!lic) return frappe.msgprint(__("Enter the driver licence number."));
				driver_popup(lic, row => { bc().val(row.bcodeNo); bc_search(); });
			});
			$head.find("#h-chg").on("click", () => confirm_call("Change the processing unit?", "cro_change_unit", { header: { ...H, crioPrcssUtCd: $head.find("#h-unit").val() } }, __("Changing..."), load));
			const can_edit = r => editable_row(r) && C().S.ctx.write_enabled;
			const cols = def.cols.map(([label, f, type, ut]) => ({
				label, cls: type === "n" ? "num" : "",
				render: (r, i) => {
					const locked = (f === "criPckgNo" || f === "croPckgNo") && H.bulkYn === "Y";
					if (can_edit(r) && def.edit.includes(f) && !locked) {
						const v = type === "d" ? T.iso_date(r[f] || (f === "croDt" ? T.today() : "")) : r[f];
						const list = f === "drvrNm" && DRIVERS.length ? ' list="cro-drv"' : "";
						return editable_input("ed", i, v, type === "n" ? "number" : (type === "d" ? "date" : "text")).replace('class="form-control ed"', `class="form-control ed" data-k="${f}"${list}`) + (ut ? ` ${E(r[ut] || "")}` : "");
					}
					if (f === "dclrNo") return r.dclrNo ? CG.dclr_fmt(r.dclrNo) : (r.addRow === "I" ? `<i class="ji-muted">${E(__("new"))}</i>` : "");
					if (f === "chkDt") return r.chkDt ? `${E(r.gainChkIsprId || "")} [${CG.fd(r.chkDt)}]` : "";
					return type === "d" ? CG.fd(r[f]) : type === "n" ? `${CG.num(r[f])} ${E(ut ? r[ut] || "" : "")}` : E(r[f]);
				},
			})).concat([
				{ label: "Status", render: r => r.prcssStatCd ? CG.status(r.prcssStatCd, r.prcssDtm, r.dclrNo, cri ? "CRI" : "CRO") : "" },
				{ label: "Declarant Comment", render: (r, i) => can_edit(r) ? `<textarea class="form-control ed" data-i="${i}" data-k="dcltOpinCn" rows="1">${E(r.dcltOpinCn)}</textarea>` : E(r.dcltOpinCn) },
			]);
			const can_add = unit === "B" && (!bl || H.newableYn === "Y");
			const has_edit = ROWS.some(r => editable_row(r) || r.addRow === "I") || (bl && H.newableYn === "Y");
			const has_reg = ROWS.some(r => ["A01", "A05", "D09"].includes(r.prcssStatCd));
			U.grid($grid, {
				title: { B: "B/L", V: "Vehicle", C: "Container", I: "Item" }[unit] + (cri ? " Carry-in" : " Carry-out"),
				rows: ROWS, columns: cols, select: selectable,
				toolbar: `${DRIVERS.length ? `<datalist id="cro-drv">${DRIVERS.map(d => `<option value="${E(d.drvrNm)}">${E([d.drvrNm, d.drvrLcneNo, d.vhclNo].join(", "))}</option>`).join("")}</datalist>` : ""}
					${kind === "cri" && unit === "V" ? `<div class="ji-actions" style="margin:0 0 6px"><span></span><div class="right"><label class="mb-0 mr-1">${E(__("Container No."))}</label>
						<input class="form-control" id="v-cntr" value="${E(VCNTR)}" style="width:170px;display:inline-block;height:26px;text-transform:uppercase">
						<button class="btn btn-xs btn-primary" id="v-cntr-go">${E(__("Search"))}</button></div></div>` : ""}
					<div class="ji-actions" style="margin:0 0 8px"><span class="ji-muted">${kind === "cri_bl" && unit === "B" ? E(__("Rows unlock after gate check-in and scanner verdict.")) : ""}</span><div class="right">${can_add && has_edit ? U.write_btn("Add", "btn-xs btn-primary", "r-add") : ""} ${has_edit ? U.write_btn("Delete", "btn-xs btn-default", "r-del") : ""}</div></div>`,
				bind: $h => {
					$h.on("change", ".ed", function () {
						const r = ROWS[Number($(this).attr("data-i"))]; const k = $(this).attr("data-k");
						r[k] = $(this).attr("type") === "number" ? ($(this).val() === "" ? null : Number($(this).val())) : $(this).val();
						if (k === "drvrNm") {  // picking a suggested driver fills licence + vehicle (portal grid_drvrNm_onChange)
							const m = DRIVERS.find(d => d.drvrNm === r.drvrNm);
							if (m) { r.drvrLcneNo = r.drvrLcneNo || m.drvrLcneNo; r.vhclNo = r.vhclNo || m.vhclNo; draw(); }
						}
						if (!cri && ["emptWght", "loadWght", "croWght"].includes(k)) { cro_weight(r, k); draw(); }
					});
					const vsearch = () => { const c = ($h.find("#v-cntr").val() || "").trim().toUpperCase();
						U.call("cri_vehicle_search", { header: H, srch_cntr_no: c }, __("Searching...")).then(d => { VCNTR = c; adopt(d); }); };
					$h.find("#v-cntr-go").on("click", vsearch);
					$h.find("#v-cntr").on("keydown", e => { if (e.key === "Enter") vsearch(); });
					$h.find("#r-add").on("click", () => {
						const f = ROWS[0] || {};
						ROWS.unshift(cri ? { addRow: "I", criDt: f.criDt || T.today(), criPckgNo: null, criWght: null, pckgUtCd: f.pckgUtCd || H.pckgUtCd, wghtUtCd: f.wghtUtCd || H.wghtUtCd, wrhsCd: f.wrhsCd || H.wrhsCd, criTpCd: f.criTpCd || H.criTpCd, criBaseNo: f.criBaseNo || H.criBaseNo, crn: f.crn || H.crn,
							mblNo: f.mblNo || H.mblNo, hblNo: f.hblNo || H.hblNo, chkDt: f.chkDt, gainChkIsprId: f.gainChkIsprId, scnrRdngRsltCd: f.scnrRdngRsltCd, scnrInscRsltCd: f.scnrInscRsltCd, entryCfrmYn: f.entryCfrmYn, prcssStatCd: null }
							: { addRow: "I", croDt: T.today(), croPckgNo: null, croWght: null, pckgUtCd: f.pckgUtCd || H.pckgUtCd, wghtUtCd: f.wghtUtCd || H.wghtUtCd, wrhsCd: f.wrhsCd || H.wrhsCd, croTpCd: f.croTpCd || H.croTpCd, croBaseNo: f.croBaseNo || H.croBaseNo, crn: f.crn || H.crn, prcssStatCd: null });
						draw();
					});
					$h.find("#r-del").on("click", () => {
						const sel = $h.selected();
						if (!sel.length) return frappe.show_alert({ message: __("Select rows"), indicator: "orange" });
						const local = sel.filter(r => r.addRow === "I");
						const remote = sel.filter(r => r.addRow !== "I");
						ROWS = ROWS.filter(r => !local.includes(r));
						if (!remote.length) return draw();
						confirm_call("Do you want to delete?", M.del, { header: H, rows: remote }, __("Deleting..."), r => { frappe.show_alert({ message: __("{0} deleted", [(r && r.delCnt) || remote.length]), indicator: "green" }); load(); });
					});
					if (cri && unit === "C") $h.find("tbody tr").on(bl ? "click" : "dblclick", function () {
						const r = ROWS[$(this).index()];
						r && U.call(bl ? "cri_bl_container_detail" : "cri_container_detail", { row: { ...H, ...r } }).then(cd => show_cntr(cd));
					});
				},
			});
			if (bl && cri && unit === "C" && ROWS[0]) U.call("cri_bl_container_detail", { row: { ...H, ...ROWS[0] } }).then(show_cntr).catch(() => {});
			if (kind === "cri") draw_receive();
			const show_save = has_edit && !(kind === "cri_bl" && H.criRprtYn === "Y");
			const tm = kind === "cri" && C().S.ctx.test_mode;  // TEST MODE: Submit simulated, offered on any carry-in
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${E(__("List"))}</button><div class="right">${show_save && !tm ? U.write_btn("Save", "btn-default", "d-save") : ""} ${has_reg || (tm && ROWS.some(r => EDIT_ROW(r.prcssStatCd))) ? U.write_btn(tm ? "Submit (test)" : "Submit", "btn-primary", "d-sbmt") : ""}</div>`);
			$act.find("#d-list").on("click", () => CG.go(M.list));
			$act.find("#d-save").on("click", () => {
				const sel = $grid.selected();
				if (!sel.length) return frappe.show_alert({ message: __("Tick the rows to save"), indicator: "orange" });
				confirm_call("Do you want to save?", M.save, { header: H, rows: sel }, __("Saving in TANeSW..."), () => { frappe.show_alert({ message: __("Saved"), indicator: "green" }); load(); });
			});
			$act.find("#d-sbmt").on("click", () => {
				const reception = kind === "cri" ? receive_args() : null;
				if (reception === false) return;
				confirm_call(C().S.ctx.test_mode ? "TEST MODE: nothing is sent to TANeSW. Create the ERP records for this carry-in?"
					: reception ? "Submit the carry-in to TANeSW and receive the containers into the ERP?" : "Do you want to submit?",
					M.sbmt, { header: H, ...(reception ? { reception } : {}) }, __("Submitting to TANeSW..."), r => {
						frappe.show_alert({ message: __("Submitted"), indicator: "green" });
						if (r && (r.icd_reception || r.icd_reception_error)) show_receive_result(r.icd_reception || [], r.icd_reception_error);
						load();
					});
			});
		}

		// ---- Receive into ERP: the two things only the gate knows, so the Container Reception can be SUBMITTED
		function containers_on_carry_in() {
			const out = [];
			ROWS.forEach(r => {
				if (r.cntrNo) out.push(String(r.cntrNo).toUpperCase());
				(String(r.cntrInfo || "").toUpperCase().match(/[A-Z]{4}\d{7}/g) || []).forEach(c => out.push(c));
			});
			return [...new Set(out)];
		}
		function link_control($parent, options, value, label, onchange) {
			const ctl = frappe.ui.form.make_control({ parent: $parent, render_input: true,
				df: { fieldtype: "Link", options, label: __(label), fieldname: frappe.scrub(label), onchange: () => onchange(ctl.get_value()) } });
			ctl.set_value(value || "");
			if (options === "Employee") ctl.get_query = () => ({ filters: { status: "Active" } });
			return ctl;
		}
		function draw_receive() {
			const cntrs = containers_on_carry_in();
			const tm = !!C().S.ctx.test_mode;
			// already reported (e.g. made in the TANeSW portal): only the ERP side is left, nothing goes to TANeSW
			const reported = !ROWS.some(r => EDIT_ROW(r.prcssStatCd));  // one button per state: Submit before reporting, Receive into ERP after
			if (!RC.on || !cntrs.length) { $rc.hide(); return; }
			if (reported) RC.receive = true;
			$rc.show().html(`<div class="ji-card-title">${E(__("Receive into ERP (Container Reception)"))}</div>
				<p class="ji-muted" style="margin:0 0 8px">${E(reported
					? __("This carry-in is already reported to TANeSW. Give the yard location and clerk, then press Receive into ERP: each container's Container Reception is created from its Movement Order and submitted. Nothing is sent to TANeSW.")
					: __("Fill these in at the gate: when TANeSW accepts the carry-in, each container's Container Reception is created from its Movement Order and submitted. Untick to only send the carry-in to TANeSW (the reception then waits on this screen)."))}</p>
				${tm ? `<div class="alert alert-warning" style="padding:6px 10px;margin:0 0 8px">${E(__("TEST MODE: Submit will NOT send this carry-in to TANeSW; it only creates the ERP records."))}</div>` : ""}
				${reported ? "" : `<label style="font-weight:600"><input type="checkbox" id="rc-on" ${RC.receive ? "checked" : ""}> ${E(__("Also receive in ERP"))}</label>`}
				<div class="row rc-fields" style="margin-top:6px"><div class="col-sm-4 rc-clerk"></div><div class="col-sm-4 rc-def"></div></div>
				<table class="table table-sm rc-fields" style="margin:4px 0 0"><thead><tr><th>${E(__("Container No."))}</th><th>${E(__("Yard Location (if different)"))}</th></tr></thead>
				<tbody>${cntrs.map(c => `<tr><td style="vertical-align:middle">${E(c)}</td><td class="rc-loc" data-c="${E(c)}"></td></tr>`).join("")}</tbody></table>
				${reported ? `<div style="text-align:right;margin-top:8px"><button class="btn btn-sm btn-primary" id="rc-receive">${E(__("Receive into ERP"))}</button></div>` : ""}`);
			$rc.find("#rc-receive").on("click", () => {
				const reception = receive_args();
				if (!reception) return;
				confirm_call("Create and submit the Container Reception for each container on this carry-in? Nothing is sent to TANeSW.",
					"tanesw_integration.icd_link.receive_reported", { crn: H.crn, cri_base_no: H.criBaseNo, reception },
					__("Receiving into ERP..."), r => show_receive_result(r || []));
			});
			const toggle = () => $rc.find(".rc-fields").toggle(RC.receive);
			$rc.find("#rc-on").on("change", function () { RC.receive = this.checked; toggle(); });
			RC.ctl.clerk = link_control($rc.find(".rc-clerk"), "Employee", RC.clerk, "Clerk", v => { RC.clerk = v; });
			RC.ctl.def = link_control($rc.find(".rc-def"), "Container Location", RC.def_loc, "Yard Location (all containers)", v => { RC.def_loc = v; });
			$rc.find(".rc-loc").each(function () {
				const c = $(this).attr("data-c");
				link_control($(this), "Container Location", RC.locs[c], "Yard Location", v => { RC.locs[c] = v; }).$wrapper.find(".control-label").hide();
			});
			toggle();
		}
		function receive_args() {
			if (!RC.on || !RC.receive || !$rc.is(":visible")) return null;
			const missing = containers_on_carry_in().filter(c => !(RC.locs[c] || RC.def_loc));
			if (!RC.clerk || missing.length) {
				frappe.msgprint({ title: __("Receive into ERP"), indicator: "orange", message: !RC.clerk
					? __("Choose the Clerk receiving these containers, or untick 'Also receive in ERP'.")
					: __("Choose a Yard Location for: {0}", [missing.join(", ")]) });
				return false;
			}
			return { clerk: RC.clerk, default_location: RC.def_loc, locations: RC.locs };
		}
		function show_receive_result(rows, error) {
			const color = { "Reception Submitted": "green", "Reception Drafted": "orange", "Awaiting Reception": "orange", "Order Linked": "blue", "Waiting for Order": "orange", "Exception": "red" };
			const link = (dt, n) => n ? `<a href="/app/${frappe.router.slug(dt)}/${encodeURIComponent(n)}" target="_blank">${E(n)}</a>` : "";
			frappe.msgprint({ title: __("Received into ERP"), wide: true, indicator: error ? "red" : "green", message:
				(error ? `<p class="text-danger">${E(error)}</p>` : "") +
				(rows.length ? `<table class="table table-sm"><thead><tr><th>${E(__("Container"))}</th><th>${E(__("Result"))}</th><th>${E(__("Container Reception"))}</th><th>${E(__("Movement Order"))}</th></tr></thead><tbody>${rows.map(r =>
					`<tr><td>${E(r.container_no)}</td><td><span class="indicator-pill ${color[r.status] || "gray"}">${E(__(r.status))}</span><div class="ji-muted small">${E(r.message || "")}</div></td><td>${link("Container Reception", r.container_reception)}</td><td>${link("Container Movement Order", r.movement_order)}</td></tr>`).join("")}</tbody></table>`
				: `<p>${E(__("No containers were found on this carry-in."))}</p>`) });
		}
		function show_cntr(d) {
			if (!d) return;
			$cd.show().html(`<div class="ji-card-title">${E(__("Container Detail"))}</div>` + U.form_grid([
				["Check-in On", E(d.chkDt)], ["Scanned On", E(d.scnrRdngDt || d.scanDt)], ["Inspected On", E(d.scnrInscDt)],
				["Analysis Verdict", E(d.scnrRdngRsltCd)], ["Inspection Verdict", E(d.scnrInscRsltCd)], ["Container Type", E(d.loadTpCd)],
				["Container Size", E(d.cntrSizeCd)], ["Freight Indicator", E(d.frghIdcrCd)],
				["Seals", E([d.sealNo1, d.sealNo2, d.sealNo3].filter(Boolean).join(" / "))], ["Package / Weight", `${CG.num(d.cntrPckgNo)} ${E(d.pckgUtCd || "")} / ${CG.num(d.cntrWght)} ${E(d.wghtUtCd || "")}`],
			]));
		}
	}

	// =================================================================== Bulk Carry-In (005Q list / 006S register)
	function cri_bulk_list($body) {
		const { U, T } = C();
		CG.list_screen($body, "cgme0401005q",
			() => ({ srch_aprv_dt_from: T.today(), srch_aprv_dt_to: T.add_days(T.today(), 7), srch_rpt_stat: ["N", "P", "Y"] }),
			f => [
				["Approval Date", U.date_range("srch_aprv_dt_from", "srch_aprv_dt_to", f), { req: true, wide: true }],
				["MRN", upper("srch_mrn", f.srch_mrn)], ["B/L No", upper("srch_bl_no", f.srch_bl_no)],
				["Status", U.checks("srch_rpt_stat", STATUS_RPT, f.srch_rpt_stat), { wide: true, req: true }],
			],
			[
				{ label: "MRN", render: (r, i) => `<a class="ji-link" data-i="${i}" data-y="N">${E(r.mrn)}</a>` },
				{ label: "M AWB Count", cls: "num", render: r => E(r.msnCnt) },
				{ label: "Approval Date", render: r => CG.fd(r.aprvDt) },
				{ label: "Report Count", cls: "num", render: (r, i) => `<a class="ji-link" data-i="${i}" data-y="Y">${E(r.rptCnt)}</a>` },
				{ label: "Not Report Count", cls: "num", render: (r, i) => `<a class="ji-link" data-i="${i}" data-y="N">${E(r.unprcsRptCnt)}</a>` },
				{ label: "Partially Reported", cls: "num", render: (r, i) => `<a class="ji-link" data-i="${i}" data-y="P">${E(r.partRptCnt)}</a>` },
			],
			"cri_bulk_list",
			{
				validate: f => (f.srch_rpt_stat || []).length ? true : (frappe.show_alert({ message: __("Select at least one status"), indicator: "orange" }), false),
				bind: ($h, rows) => $h.find("a[data-i]").on("click", function () {
					const r = rows[Number($(this).attr("data-i"))];
					CG.go("cgme0401006s", r.mrn, r.criTpCd || "-", r.criBaseNo || "-", T.iso_date(r.aprvDt) || "-", $(this).attr("data-y"));
				}),
			});
		actions($body).html(`<button class="btn btn-sm btn-default">${E(__("List"))}</button>`).find("button").on("click", () => CG.go("cgme0401001q"));
	}

	function cri_bulk_detail($body, mrn, cri_tp_cd, cri_base_no, aprv_dt, report_yn) {
		const { U, T } = C();
		const v = x => (x === "-" ? "" : x);
		const editable = (report_yn || "N") === "N";
		const $head = card($body), $grid = card($body), $act = actions($body);
		let H = {}, ROWS = [];
		const load = () => U.call("cri_bulk_detail", { mrn, cri_base_no: v(cri_base_no), report_yn: report_yn || "N" }).then(d => {
			H = { ...(d || {}) }; ROWS = (H.wrhsCriBulkList || []).map(r => ({ ...r })); delete H.wrhsCriBulkList;
			if (!H.criDt) H.criDt = T.today();
			draw();
		});
		ensure_codes(["COM0023"]).then(load);
		// portal checkbox rule: unprocessed rows; WT* (terminal) warehouses only before entry confirmation
		const selectable = r => !r.prcssStatCd && !(String(r.wrhsCd || "").startsWith("WT") && r.entryCfrmYn !== "N");
		function draw() {
			$head.html(`<div class="ji-card-title">${E(__("MRN"))}</div>` + U.form_grid([
				["Expected Carry-in Date", editable && C().S.ctx.write_enabled ? `<input type="date" class="form-control ji-date" data-f="criDt" value="${E(T.iso_date(H.criDt))}">` : CG.fd(H.criDt), { req: true, wide: true }],
			]) + `<div class="ji-card-title mt-2">${E(__("MRN Detail"))}</div>` + U.form_grid([
				["MRN", E(H.mrn || mrn)], ["Approval Date", CG.fd(v(aprv_dt))],
				["Flight No", E(H.airFlno)], ["Arrival Date", CG.fd(H.arvlXptdDt)],
				["Port of Departure", U.pair(H.dptrPortCd, H.dptrPortNm)], ["Port of Discharge", U.pair(H.dscgPortCd, H.dscgPortNm)],
				["Carrier", E(H.carrNm), { wide: true }],
				["Report Count", CG.num(H.criRptYCnt)], ["Not Report Count", CG.num(H.criRptNCnt)],
				["Partially Reported", CG.num(H.criRptPCnt)], ["Not Reported (Carry-In Registered)", CG.num(H.criSaveCnt)],
			]));
			$head.find('[data-f="criDt"]').on("change", function () { H.criDt = $(this).val(); });
			U.grid($grid, {
				title: "Master B/L List", rows: ROWS, select: editable ? selectable : null,
				columns: [
					{ label: "Reference No", render: r => CG.crn_fmt(r.crn) }, { label: "Master B/L No", render: r => E(r.awb || r.mblNo) },
					{ label: "Number of Packages", cls: "num", render: r => `${CG.num(r.criXptdPckgNo)} ${E(r.pckgUtCd || "")}` },
					{ label: "Net Weight", cls: "num", render: r => `${CG.num(r.criXptdWght)} ${E(r.wghtUtCd || "")}` },
					{ label: "Approval Date", render: r => CG.fd(r.aprvDt) },
					{ label: "Carry-In", render: r => r.prcssStatCd ? CG.status(r.prcssStatCd, r.prcssDtm, r.dclrNo, "CRI") : "" },
					{ label: "Report", render: r => E(r.rptYnNm) },
				],
			});
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${E(__("List"))}</button><div class="right">${editable ? `${U.write_btn("Save", "btn-default", "d-save")} ${U.write_btn("Submit", "btn-primary", "d-sbmt")}` : ""}</div>`);
			$act.find("#d-list").on("click", () => CG.go("cgme0401005q"));
			$act.find("#d-save").on("click", () => {
				const sel = $grid.selected();
				if (!H.criDt) return frappe.msgprint(__("Carry-in date is required"));
				if (!sel.length) return frappe.show_alert({ message: __("Tick the master B/Ls to carry in"), indicator: "orange" });
				confirm_call("Do you want to save?", "cri_bulk_save", { header: H, rows: sel }, __("Saving in TANeSW..."), () => { frappe.show_alert({ message: __("Saved"), indicator: "green" }); load(); });
			});
			$act.find("#d-sbmt").on("click", () => confirm_call("Do you want to submit?", "cri_bulk_submit", { header: H, cri_base_no: v(cri_base_no), cri_tp_cd: v(cri_tp_cd) }, __("Submitting to TANeSW..."), () => { frappe.show_alert({ message: __("Submitted"), indicator: "green" }); load(); }));
		}
	}

	// =================================================================== Stripping
	const STRP_TP = r => C().U.code("CGM0089", r.strpngRsltTpCd);
	function strp_schedule($body) {
		const { U, T } = C();
		ensure_codes(["CGM0002"]).then(() => CG.list_screen($body, "cgme0406001q",
			() => ({ rgsr_dt_from: T.add_days(T.today(), -7), rgsr_dt_to: T.today(), prcss_stat_cd: "All" }),  // portal: last 7 days
			f => [
				["Date of Register", U.date_range("rgsr_dt_from", "rgsr_dt_to", f), { wide: true }],
				["MRN", upper("mrn", f.mrn)], ["CRN", upper("crn", f.crn)],
				["Status", lbl_select("prcss_stat_cd", [["All", "All"], ["Register Enable", "Register Enable"], ["Registered", "Registered"]], f.prcss_stat_cd), { wide: true }],
			],
			[
				{ label: "MRN", render: r => E(r.mrn) }, { label: "CRN", render: r => CG.crn_fmt(r.crn) },
				{ label: "Cargo Type", render: r => U.code("CGM0002", r.cagClsfCd) },
				{ label: "MBL No", render: r => E(r.mblNo) }, { label: "HBL No", render: r => E(r.hblNo) },
				{ label: "Place of Destination", render: r => CG.wh_cell(r.dstnPlcCd) },
				{ label: "Status", render: r => E(r.prcssStatCd) }, { label: "Stock", render: r => E(r.stckYn) },
				{ label: "Registered Date", render: r => CG.fdt(r.frstRgsrDtm) },
			], "strp_schedule"));
	}

	function strp_list($body, sid, method, open_sid, prcd, no_field, opts_no) {
		const { U, T } = C();
		Promise.all([ensure_codes(["CGM0089"]), U.call("procedure_codes", { comn_cd: prcd }).catch(() => ({}))]).then(([, st]) => CG.list_screen($body, sid,
			() => ({ rgsr_dt_from: T.add_days(T.today(), -7), rgsr_dt_to: T.today(), gen_item: "rprtNo",  // portal: last 7 days
				// portal's default ticked statuses: report list = open reports; amendment/cancellation = also approved & waiting payment
				srch_stat_cd: (sid === "cgme0406002q" ? ["A01", "A04", "D01", "J07", "A05"] : ["A01", "A04", "D01", "D06", "A05", "D15"]).filter(c => !Object.keys(st || {}).length || c in st) }),
			f => [
				["Date of Register", U.date_range("rgsr_dt_from", "rgsr_dt_to", f), { wide: true }],
				[lbl_select("gen_item", opts_no, f.gen_item), input("srch_opt", f.srch_opt), { wide: true }],
			].concat(Object.keys(st || {}).length ? [["Status", U.checks("srch_stat_cd", st, f.srch_stat_cd), { wide: true }]] : []),
			[
				{ label: no_field === "rprtNo" ? "Report No." : (no_field === "amdDclrNo" ? "Amend Declaration No." : "Cancel Report No"), render: r => `<a class="ji-link" data-no="${E(r[no_field])}">${CG.dclr_fmt(r[no_field])}</a>` },
			].concat(no_field !== "rprtNo" ? [{ label: "Report No.", render: r => CG.dclr_fmt(r.rprtNo) }] : []).concat([
				{ label: "MRN", render: r => E(r.mrn) }, { label: "Stripping Type", render: STRP_TP },
			]).concat(no_field !== "cnclDclrNo" ? [
				{ label: "Total B/L", cls: "num", render: r => E(r.totBlCnt) }, { label: "Short/Over Count", cls: "num", render: r => E(r.shrtOverCnt) },
				{ label: "Waiting Amend Count", cls: "num", render: r => E(r.amdCnt) }, { label: "Stripping Date", render: r => CG.fd(r.strpngDt) }]
				.concat(no_field === "amdDclrNo" ? [{ label: "Registration Date", render: r => CG.fd(r.rgsrDt) }, { label: "Submission Date", render: r => CG.fd(r.sbmtDt) }] : []) : [
				{ label: "Submission Date", render: r => CG.fd(r.sbmtDt) }]).concat(no_field !== "rprtNo" ? [{ label: "Penalty", render: r => E(r.pnltImpsYn) }] : [])
				.concat([{ label: "Status", render: r => CG.status(r.prcssStatCd, r.prcssDtm, r[no_field], { rprtNo: "SRR", amdDclrNo: "SRA", cnclDclrNo: "SRC" }[no_field]) }]),
			method, {
				validate: f => (f.srch_stat_cd || []).length || !Object.keys(st || {}).length ? true : (frappe.show_alert({ message: __("Select at least one status"), indicator: "orange" }), false),
				// portal: "New Report"/"New Amendment" + "Delete" (only registered / received-error rows never submitted)
				select: r => ["A01", "A05"].includes(r.prcssStatCd) && !r.sbmtDt,
				toolbar: `${C().U.write_btn(no_field === "amdDclrNo" ? "New Amendment" : "New Report", "btn-default btn-xs", "cg-new")} ${C().U.write_btn("Delete", "btn-danger btn-xs", "cg-del")}`,
				bind: ($h, rows, reload) => {
					$h.find("[data-no]").on("click", function () { CG.go(open_sid, $(this).attr("data-no")); });
					$h.find("#cg-new").on("click", () => CG.go(open_sid, "new"));
					$h.find("#cg-del").on("click", () => {
						const sel = $h.selected();
						if (!sel.length) return frappe.show_alert({ message: __("Select rows to delete"), indicator: "orange" });
						const m = { rprtNo: ["strp_report_delete", "rprt_no"], amdDclrNo: ["strp_amd_delete", "amd_dclr_no"], cnclDclrNo: ["strp_cncl_delete", "cncl_dclr_no"] }[no_field];
						frappe.confirm(__("Delete {0} record(s)?", [sel.length]), () =>
							sel.reduce((p, r) => p.then(() => C().U.call(m[0], { [m[1]]: r[no_field] })), Promise.resolve()).then(() => { frappe.show_alert({ message: __("Deleted"), indicator: "green" }); reload(); }));
					});
				},
			}));
	}

	const NRML_COLS = [
		{ label: "M B/L No", render: r => E(r.mblNo) }, { label: "H B/L No", render: r => E(r.hblNo) }, { label: "CRN", render: r => CG.crn_fmt(r.crn) },
		{ label: "Package", cls: "num", render: r => `${CG.num(r.strpngPckgNo)} ${UNIT("COM0007", r.pckgUtCd)}` },
		{ label: "Weight", cls: "num", render: r => `${CG.num(r.strpngWght)} ${UNIT("COM0005", r.wghtUtCd)}` },
		{ label: "Vehicle Count", cls: "num", render: (r, i) => `<a class="ji-link" data-veh="${i}">${E(r.vhclCnt ?? 0)}</a>` },
	];
	const ABNR_COLS = [
		{ label: "Update Type", render: r => C().U.code("CGM0088", r.strpngAmdTpCd) },
		{ label: "MBL No", render: r => E(r.mblNo) }, { label: "HBL No", render: r => E(r.hblNo) }, { label: "CRN", render: r => CG.crn_fmt(r.crn) },
		{ label: "Package", cls: "num", render: r => `${CG.num(r.blPckgNo)} ${UNIT("COM0007", r.pckgUtCd)}` },
		{ label: "Weight", cls: "num", render: r => `${CG.num(r.blNwght)} ${UNIT("COM0005", r.nwghtUtCd)}` },
		{ label: "Processed", render: r => E(r.prcssYn) }, { label: "Amendment Reference", render: r => E(r.reffDclrNo) },
	];

	// Registration (003S) and Amendment (009S) share the B/L tabs.
	function strp_report($body, no, mode) {
		const { U, T } = C();
		const amd = mode === "amd";
		const is_new = !no || no === "new";
		const $head = card($body), $tabs = card($body).hide(), $act = actions($body);
		let H = {}, NB = [], MB = [], HB = [];
		const ed = () => CG.EDITABLE.includes(H.prcssStatCd || "");
		const key_no = () => amd ? H.amdDclrNo : H.rprtNo;
		const load = () => (amd ? U.call("strp_amd", { no: H.amdDclrNo || no }) : U.call("strp_report", { rprt_no: H.rprtNo || no })).then(adopt);
		const adopt = d => {
			const a = d.cgmeDclrAmdMDto || {};
			H = { ...d, ...(amd ? { amdDclrNo: d.amdDclrNo || a.amdDclrNo, prcssStatCd: a.prcssStatCd || "", prcssDtm: a.prcssDtm, amdRsn: a.amdRsn || d.amdRsn } : {}) };
			if (a.dclrAmdPnltD && a.dclrAmdPnltD.pnltImpsYn === "Y") Object.assign(H, { pnltImpsYn: "Y", pnltUsdAmt: a.dclrAmdPnltD.pnltUsdAmt, bllNo: a.dclrAmdPnltD.bllNo });
			NB = d.strpngRsltBlRList || [];
			const extra = d.strpngRsltAbnrAmdRList || [];
			MB = [...(d.strpngRsltAbnrMBlRList || []), ...extra.filter(r => r.hblNo === "SIMPLE")];
			HB = [...(d.strpngRsltAbnrHBlRList || []), ...extra.filter(r => r.hblNo !== "SIMPLE")];
			draw();
		};
		ensure_codes(["CGM0089", "CGM0088", "COM0007"]).then(() => {
			if (!is_new) return load();
			if (amd) {
				$head.html(`<div class="ji-muted">${E(__("Select the stripping result report to amend."))}</div><div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary" id="p">${E(__("Select Report"))}</button></div></div>`);
				$head.find("#p").on("click", () => strp_pick_target("amd", t => U.call("strp_amd", { no: t.rprtNo }, __("Loading...")).then(adopt)));
			} else { H = { prcssStatCd: "", strpngDt: T.today() }; draw(); }
		});
		function draw() {
			const e = ed();
			$head.html(`<div class="ji-card-title">${E(__(amd ? "Stripping Result Amendment" : "Details"))}</div>` + U.form_grid((amd ? [
				["Amend Declaration No", E(H.amdDclrNo)], ["Status", CG.status(H.prcssStatCd, H.prcssDtm, H.amdDclrNo, "SRA")],
				["Report No", E(H.rprtNo)], ["MRN", E(H.mrn)], ["Customs", CSTM(H.cstmOfceCd)], ["Stripping Date", CG.fd(H.strpngDt)],
				["Stripping Type", STRP_TP(H)], [" ", ""],
				["Amendment Comment", e ? `<textarea class="form-control" data-f="amdRsn" maxlength="2000">${E(H.amdRsn)}</textarea>` : E(H.amdRsn), { req: true, wide: true }],
				...CG.penalty_rows(H),
			] : [
				["Report No.", CG.dclr_fmt(H.rprtNo)], ["Status", CG.status(H.prcssStatCd, H.prcssDtm, H.rprtNo, "SRR")],
				["MRN", e && !H.rprtNo ? upper("mrn", H.mrn) : E(H.mrn), { req: true }], ["Customs Office Code", e ? input("cstmOfceCd", H.cstmOfceCd) : CSTM(H.cstmOfceCd)],
				["Stripping Date", e ? `<input type="date" class="form-control ji-date" data-f="strpngDt" value="${E(T.iso_date(H.strpngDt))}">` : CG.fd(H.strpngDt), { req: true }],
				["Stripping Type", e && !Object.keys(C().S.codes.CGM0089 || {}).length ? input("strpngRsltTpCd", H.strpngRsltTpCd) : e ? Object.entries(C().S.codes.CGM0089 || {}).map(([k, n]) => `<label class="mr-3"><input type="radio" name="sp-tp" data-f="strpngRsltTpCd" value="${E(k)}" ${H.strpngRsltTpCd === k ? "checked" : ""}> ${E(n)}</label>`).join("") : STRP_TP(H), { req: true }],
				["Stripping Comment", e ? `<textarea class="form-control" data-f="strpngCmntCn" maxlength="2000">${E(H.strpngCmntCn)}</textarea>` : E(H.strpngCmntCn), { wide: true }],
			])));
			if (key_no()) {
				// Portal: the M B/L tab shows only if a normal B/L is SIMPLE, the H B/L tab only if one is not.
				const has_m = NB.some(r => r.hblNo === "SIMPLE") || MB.length, has_h = NB.some(r => r.hblNo !== "SIMPLE") || HB.length;
				$tabs.show().html(`<div class="ji-tabs"><a class="active" data-t="n">${E(__("Normal B/L List"))}</a>${has_m ? `<a data-t="m">${E(__("Short/Over Mbl List"))}</a>` : ""}${has_h ? `<a data-t="h">${E(__("Short/Over Hbl List"))}</a>` : ""}</div><div class="ji-tb"></div>`);
				$tabs.find(".ji-tabs a").on("click", function () { tab($(this).attr("data-t")); });
				tab("n");
			}
			const list_sid = amd ? "cgme0406008q" : "cgme0406002q";
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${E(__("List"))}</button><div class="right">
				${e ? U.write_btn("Save", "btn-default", "d-save") : ""} ${e && key_no() ? U.write_btn("Submit", "btn-primary", "d-sbmt") : ""}
				${e && key_no() && !H.sbmtDt ? U.write_btn("Delete", "btn-danger", "d-del") : ""}</div>`);
			$act.find("#d-list").on("click", () => CG.go(list_sid));
			const send = action => {
				const header = { ...H, ...U.read_form($head) };
				delete header.strpngRsltBlRList; delete header.strpngRsltAbnrMBlRList; delete header.strpngRsltAbnrHBlRList; delete header.strpngRsltAbnrAmdRList;
				if (header.strpngDt && H.strpngDt && !String(H.strpngDt).includes("-")) header.strpngDt = String(header.strpngDt).replace(/-/g, "");
				if (action === "sbmt" && !amd && !NB.length) return frappe.msgprint(__("Normal B/L List is empty."));
				if (action === "sbmt" && !amd && header.strpngRsltTpCd === "V" && NB.some(r => !Number(r.vhclCnt))) return frappe.msgprint(__("Register the vehicles for every B/L before submitting."));
				confirm_call(action === "sbmt" ? "Do you want to submit?" : "Do you want to save?", amd ? "strp_amd_save" : "strp_report_save", { header, action }, __("Sending to TANeSW..."), r => {
					frappe.show_alert({ message: __("Done"), indicator: "green" });
					const n = amd ? ((r && r.amdDclrNo) || H.amdDclrNo) : ((r && r.rprtNo) || H.rprtNo);
					CG.st.last_key = null; CG.go(amd ? "cgme0406009s" : "cgme0406003s", n);
				});
			};
			$act.find("#d-save").on("click", () => send("save"));
			$act.find("#d-sbmt").on("click", () => send("sbmt"));
			$act.find("#d-del").on("click", () => confirm_call("Do you want to delete?", amd ? "strp_amd_delete" : "strp_report_delete", amd ? { amd_dclr_no: H.amdDclrNo } : { rprt_no: H.rprtNo }, __("Deleting..."), () => CG.go(list_sid)));
		}
		function tab(t) {
			$tabs.find(".ji-tabs a").removeClass("active").filter(`[data-t="${t}"]`).addClass("active");
			const $tb = $tabs.find(".ji-tb"), e = ed();
			const rows = { n: NB, m: MB, h: HB }[t];
			const toolbar = e ? `<div class="ji-actions" style="margin:0 0 8px"><span></span><div class="right">
				${(t === "n" && !amd) || t !== "n" ? U.write_btn("Add", "btn-xs btn-primary", "t-add") : ""} ${U.write_btn("Delete", "btn-xs btn-default", "t-del")}</div></div>` : "";
			U.grid($tb, {
				rows, columns: t === "n" ? NRML_COLS : (amd ? [{ label: "Type", render: r => E(r.dtlAmdTpCd) }].concat(ABNR_COLS) : ABNR_COLS),
				select: e ? () => true : null, toolbar,
				bind: $h => {
					$h.find("[data-veh]").on("click", function () { strp_vehicles(NB[Number($(this).attr("data-veh"))], !e, load); });
					$h.find("#t-add").on("click", () => t === "n" ? strp_add_normal(H, load) : strp_abnormal_dialog(t === "m" ? "mbl" : "hbl", H, amd ? H.amdDclrNo : null, load));
					$h.find("#t-del").on("click", () => {
						const sel = $h.selected();
						if (!sel.length) return frappe.show_alert({ message: __("Select rows"), indicator: "orange" });
						const keys = sel.map(r => amd ? `${H.amdDclrNo}!${r.mblNo}!${r.hblNo}!${r.crn}!${r.dtlAmdTpCd}` : `${H.rprtNo}!${r.mblNo}!${r.hblNo}!${r.crn}`);
						confirm_call("Do you want to delete?", "strp_delete_rows", { kind: { n: "nrml", m: "mbl", h: "hbl" }[t], keys }, __("Deleting..."), load);
					});
				},
			});
		}
	}

	function strp_pick_target(kind, on_pick) {
		const { U, T } = C();
		const f = { rgsr_dt_from: T.add_days(T.today(), -7), rgsr_dt_to: T.today() };  // portal: last 7 days
		const d = U.modal("Stripping Result Report", `<div class="ji-s">${U.form_grid([
			["Date of Register", U.date_range("rgsr_dt_from", "rgsr_dt_to", f), { wide: true }],
			[lbl_select("gen_item", [["rprtNo", "Report No"], ["mrn", "MRN"]], "rprtNo"), input("srch_opt", ""), { wide: true }],
		])}<div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary ji-search">${E(__("Search"))}</button></div></div></div><div class="ji-g mt-2"></div>`, "extra-large");
		U.bind_range(d.$body);
		const $g = d.$body.find(".ji-g");
		const load = (page = 0) => {
			U.loading($g, 6);
			U.call("strp_targets", { kind, ...U.read_form(d.$body.find(".ji-s")), page, size: 10 }).then(res => U.grid($g, {
				rows: res.content, meta: res.page, size: 10, onPage: load, onSize: () => load(0),
				columns: [{ label: "Report No", render: (r, i) => `<a class="ji-link" data-i="${i}">${E(r.rprtNo)}</a>` }, { label: "MRN", render: r => E(r.mrn) },
					{ label: "Stripping Type", render: STRP_TP }, { label: "Total B/L", render: r => E(r.totBlCnt) },
					{ label: "Stripping Date", render: r => CG.fd(r.strpngDt) }, { label: "Status", render: r => CG.status(r.prcssStatCd) }],
				bind: ($h, rows) => $h.find("[data-i]").on("click", function () { d.hide(); on_pick(rows[Number($(this).attr("data-i"))]); }),
			}));
		};
		d.$body.find(".ji-search").on("click", () => load(0));
		load(0);
	}

	function strp_add_normal(H, done) {
		const { U } = C();
		const d = U.modal("LCL Cargo", `<div class="ji-s">${U.form_grid([
			["CRN", upper("crn", "")], ["Status", lbl_select("prcss_stat_cd", [["All", "All"], ["Register Enable", "Register Enable"], ["Registered", "Registered"]], "Register Enable")],
		])}<div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary ji-search">${E(__("Search"))}</button></div></div></div><div class="ji-g mt-2"></div>
			<div class="ji-actions"><span></span><div class="right">${U.write_btn("Save", "btn-primary", "p-ok")}</div></div>`, "extra-large");
		const $g = d.$body.find(".ji-g");
		const load = (page = 0) => {
			U.loading($g, 4);
			U.call("strp_lcl_candidates", { mrn: H.mrn, rprt_no: H.rprtNo, ...U.read_form(d.$body.find(".ji-s")), page, size: 50 }).then(res => U.grid($g, {
				rows: res.content, meta: res.page, size: 50, onPage: load, onSize: () => load(0), select: r => r.prcssStatCd === "Register Enable",
				columns: [{ label: "MRN", render: r => E(r.mrn) }, { label: "CRN", render: r => CG.crn_fmt(r.crn) }, { label: "Status", render: r => E(r.prcssStatCd) }],
			}));
		};
		d.$body.find(".ji-search").on("click", () => load(0));
		d.$body.find("#p-ok").on("click", () => {
			const rows = $g.selected ? $g.selected() : [];
			if (!rows.length) return frappe.show_alert({ message: __("Select at least one B/L"), indicator: "orange" });
			confirm_call("Do you want to save?", "strp_add_normal_bls", { rprt_no: H.rprtNo, mrn: H.mrn, rows }, __("Saving..."), () => { d.hide(); done(); });
		});
		load(0);
	}

	function strp_abnormal_dialog(kind, H, amd_no, done) {
		const { U } = C();
		U.call("strp_normal_bls", { rprt_no: H.rprtNo, mrn: H.mrn }).then(nrml => {
			const simple = (nrml || []).filter(r => r.hblNo === "SIMPLE");
			const opts = (kind === "mbl" ? simple : (nrml || []).filter(r => r.hblNo !== "SIMPLE"));
			const blf = kind === "mbl" ? "mblNo" : "hblNo";
			const d = U.modal(kind === "mbl" ? "Short/Over-landed MBL" : "Short/Over-landed HBL", U.form_grid([
				["Update Type", Object.entries(C().S.codes.CGM0088 || { I: "Insert", U: "Update", D: "Delete" }).map(([k, n]) => `<label class="mr-3"><input type="radio" name="ab-tp" data-f="strpngAmdTpCd" value="${E(k)}" ${k === "I" ? "checked" : ""}> ${E(n)}</label>`).join(""), { wide: true }],
				[kind === "mbl" ? "MBL No" : "HBL No", `<input class="form-control ab-new" data-f="${blf}" style="text-transform:uppercase">
					<select class="form-control ab-ex" data-f="crn" style="display:none"><option value=""></option>${opts.map(r => `<option value="${CG.crn_fmt(r.crn)}">${E(r[blf] === "SIMPLE" ? r.mblNo : r[blf])} [${CG.crn_fmt(r.crn)}]</option>`).join("")}</select>`, { wide: true }],
				["Packages", `<input type="number" class="form-control" data-f="blPckgNo" style="width:120px"> <select class="form-control" data-f="pckgUtCd" style="width:auto">${Object.entries(C().S.codes.COM0007 || {}).map(([k, n]) => `<option value="${E(k)}">[${E(k)}] ${E(n)}</option>`).join("")}</select>`],
				["Weight", `<input type="number" class="form-control" data-f="blNwght" style="width:120px"> <input class="form-control" data-f="nwghtUtCd" value="KG" style="width:70px">`],
			]) + `<div class="ji-actions"><span></span><div class="right">${U.write_btn("Save", "btn-primary", "ab-ok")}</div></div>`);
			const $b = d.$body;
			const sync = () => { const ins = $b.find('[data-f="strpngAmdTpCd"]:checked').val() === "I"; $b.find(".ab-new").toggle(ins); $b.find(".ab-ex").toggle(!ins); };
			$b.on("change", '[data-f="strpngAmdTpCd"]', sync); sync();
			$b.on("change", ".ab-ex", function () {
				const r = (nrml || []).find(x => x.crn === $(this).val()); if (!r) return;
				$b.find('[data-f="blPckgNo"]').val(r.strpngPckgNo); $b.find('[data-f="pckgUtCd"]').val(r.pckgUtCd); $b.find('[data-f="blNwght"]').val(r.strpngWght);
			});
			$b.find("#ab-ok").on("click", () => {
				const f = U.read_form($b);
				const tp = f.strpngAmdTpCd;
				let base;
				if (tp === "I") {
					if (!f[blf]) return frappe.show_alert({ message: __("B/L No is required"), indicator: "orange" });
					base = { ...(simple[0] || (nrml || [])[0] || {}), [blf]: f[blf].toUpperCase() };
				} else {
					base = (nrml || []).find(r => r.crn === f.crn);
					if (!base) return frappe.show_alert({ message: __("Select the B/L"), indicator: "orange" });
				}
				if (tp !== "D" && (f.blPckgNo === "" || f.blNwght === "")) return frappe.show_alert({ message: __("Packages and weight are required"), indicator: "orange" });
				const row = { ...base, blPckgNo: f.blPckgNo, pckgUtCd: f.pckgUtCd, blNwght: f.blNwght, nwghtUtCd: f.nwghtUtCd, strpngAmdTpCd: tp, rprtNo: H.rprtNo, amdDclrNo: amd_no || undefined };
				confirm_call("Do you want to save?", "strp_save_abnormal", { kind, row }, __("Saving..."), () => { d.hide(); done(); });
			});
		});
	}

	function strp_vehicles(bl, readonly, done) {
		const { U } = C();
		U.call("strp_bl_containers", { row: bl }).then(list => {
			let rows = (list || []).map(r => ({ ...r }));
			const d = U.modal("Stripping Vehicles", `${U.form_grid([
				["Report No", E(bl.rprtNo)], ["CRN", E(bl.crn)], ["MBL No", E(bl.mblNo)], ["HBL No", E(bl.hblNo)],
				["Package", `${CG.num(bl.strpngPckgNo)} ${E(bl.pckgUtCd || "")}`], ["Weight", `${CG.num(bl.strpngWght)} ${E(bl.wghtUtCd || "")}`],
			])}<div class="ji-g mt-2"></div><div class="ji-actions"><span></span><div class="right">${readonly ? "" : U.write_btn("Save", "btn-primary", "v-ok")}</div></div>`, "extra-large");
			const $g = d.$body.find(".ji-g");
			const draw = () => U.grid($g, {
				rows, select: readonly ? null : () => true,
				columns: [
					{ label: "Type", render: (r, i) => readonly ? E(r.vhclTpCd) : editable_input("vv", i, r.vhclTpCd).replace('class="form-control vv"', 'class="form-control vv" data-k="vhclTpCd"') },
					{ label: "Chassis / Vehicle No", render: (r, i) => readonly ? E(r.cntrNo) : editable_input("vv", i, r.cntrNo).replace('class="form-control vv"', 'class="form-control vv" data-k="cntrNo"') },
					{ label: "Package", render: (r, i) => readonly ? CG.num(r.cntrPckgNo) : editable_input("vv", i, r.cntrPckgNo, "number").replace('class="form-control vv"', 'class="form-control vv" data-k="cntrPckgNo"') },
					{ label: "Weight", render: (r, i) => readonly ? CG.num(r.cntrWght) : editable_input("vv", i, r.cntrWght, "number").replace('class="form-control vv"', 'class="form-control vv" data-k="cntrWght"') },
				],
				toolbar: readonly ? "" : `<div class="ji-actions" style="margin:0 0 8px"><span></span><div class="right"><button class="btn btn-xs btn-primary" id="v-add">${E(__("Add"))}</button> ${U.write_btn("Delete", "btn-xs btn-default", "v-del")}</div></div>`,
				bind: $h => {
					$h.on("change", ".vv", function () { rows[Number($(this).attr("data-i"))][$(this).attr("data-k")] = $(this).val(); });
					$h.find("#v-add").on("click", () => { rows.push({ mrn: bl.mrn, msn: bl.msn, hsn: bl.hsn, crn: bl.crn, __type: "added" }); draw(); });
					$h.find("#v-del").on("click", () => {
						const sel = $h.selected();
						const remote = sel.filter(r => r.__type !== "added");
						rows = rows.filter(r => !sel.includes(r) || r.__type !== "added");
						if (!remote.length) return draw();
						confirm_call("Do you want to delete?", "strp_delete_bl_containers", { keys: remote.map(r => `${bl.rprtNo}-${r.cntrNo}-${r.crn}`) }, __("Deleting..."), () => { d.hide(); done(); });
					});
				},
			});
			draw();
			d.$body.find("#v-ok").on("click", () => confirm_call("Do you want to save?", "strp_save_bl_containers", { row: bl, containers: rows.map(r => { const x = { ...r }; delete x.__type; return x; }) }, __("Saving..."), () => { d.hide(); done(); }));
		});
	}

	function strp_cncl($body, no) {
		const { U } = C();
		const is_new = !no || no === "new";
		const $head = card($body), $tabs = card($body), $act = actions($body);
		let H = {};
		const ed = () => CG.EDITABLE.includes(H.prcssStatCd || "");
		const adopt = d => { const c = d.cgmeDclrCnclMDto || {}; H = { ...d, ...c, cnclDclrNo: c.cnclDclrNo || d.cnclDclrNo, prcssStatCd: c.prcssStatCd || d.prcssStatCd || "" }; draw(); };
		ensure_codes(["CGM0089", "CGM0088"]).then(() => {
			if (!is_new) return U.call("strp_cncl", { no }).then(adopt);
			$head.html(`<div class="ji-muted">${E(__("Select the stripping result report to cancel."))}</div><div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-primary" id="p">${E(__("Select Report"))}</button></div></div>`);
			$head.find("#p").on("click", () => strp_pick_target("cncl", t => U.call("strp_cncl", { no: t.rprtNo }, __("Loading...")).then(adopt)));
		});
		function draw() {
			const e = ed();
			$head.html(`<div class="ji-card-title">${E(__("Stripping Result Cancellation"))}</div>` + U.form_grid([
				["Cancel Report No", E(H.cnclDclrNo)], ["Status", CG.status(H.prcssStatCd, H.prcssDtm, H.cnclDclrNo, "SRC")],
				["Report No", E(H.rprtNo)], ["MRN", E(H.mrn)], ["Customs", CSTM(H.cstmOfceCd)], ["Stripping Date", CG.fd(H.strpngDt)],
				["Stripping Type", STRP_TP(H)], ["Registered", CG.fdt(H.prcssDtm)],
				["Cancellation Comment", e ? `<textarea class="form-control" data-f="cnclCn" maxlength="2000">${E(H.cnclCn)}</textarea>` : E(H.cnclCn), { req: true, wide: true }],
				...CG.penalty_rows(H),
			]));
			U.grid($tabs, { title: "Normal B/L List", rows: H.strpngRsltBlRList || [], columns: NRML_COLS.slice(0, 5) });
			$act.html(`<button class="btn btn-sm btn-default" id="d-list">${E(__("List"))}</button><div class="right">
				${e ? U.write_btn("Save", "btn-default", "d-save") : ""} ${e && H.cnclDclrNo ? U.write_btn("Submit", "btn-primary", "d-sbmt") : ""}
				${e && H.cnclDclrNo && !H.sbmtDt ? U.write_btn("Delete", "btn-danger", "d-del") : ""}</div>`);
			$act.find("#d-list").on("click", () => CG.go("cgme0406012q"));
			const send = action => {
				const header = { ...H, ...U.read_form($head) }; delete header.strpngRsltBlRList;
				confirm_call(action === "sbmt" ? "Do you want to submit?" : "Do you want to save?", "strp_cncl_save", { header, action }, __("Sending to TANeSW..."),
					r => { frappe.show_alert({ message: __("Done"), indicator: "green" }); CG.st.last_key = null; CG.go("cgme0406013s", (r && r.cnclDclrNo) || H.cnclDclrNo); });
			};
			$act.find("#d-save").on("click", () => send("save"));
			$act.find("#d-sbmt").on("click", () => send("sbmt"));
			$act.find("#d-del").on("click", () => confirm_call("Delete this cancellation?", "strp_cncl_delete", { cncl_dclr_no: H.cnclDclrNo }, __("Deleting..."), () => CG.go("cgme0406012q")));
		}
	}

	// =================================================================== Cargo Tracking
	function tracking($body, crn_arg) {
		const { U } = C();
		const s = CG.st.store.cgme0910001q || (CG.st.store.cgme0910001q = { form: {} });
		const $s = $(`<div class="ji-card">${U.form_grid([
			["Cargo Reference No", upper("srch_crn", s.form.srch_crn)], ["B/L No", upper("srch_bl_no", s.form.srch_bl_no)],
			["Container No / Chassis No", upper("srch_cntr_no", s.form.srch_cntr_no), { wide: true }],
		])}<div class="ji-actions"><button class="btn btn-sm ji-reset">${E(__("Reset"))}</button><div class="right"><button class="btn btn-sm btn-primary ji-search">${E(__("Search"))}</button></div></div></div>`).appendTo($body);
		const $d = card($body).hide(), $p = card($body).hide(), $c = card($body).hide();
		ensure_codes(["CGM0002", "CGM0009", "CGM0010", "CGM0021", "CGM0017"]);
		const show = t => {
			if (!t || !Object.keys(t).length) return;
			// Field set and order of the portal's "B/L Information" block (CGME-0910-001Q).
			const sh = c => (C().S.parties.organisations || {})[c];
			$d.show().html(`<div class="ji-card-title">${E(__("B/L Information"))}</div>` + U.form_grid([
				["Cargo Reference No", CG.crn_fmt(t.crn)], ["B/L / AWB No", E(t.blNo || t.mblNo)],
				["Current Status", E(t.cagTrkngPrcssCdNm || t.cagTrkngPrcssCd)], ["Vessel Name/Flight No", E(t.vsslNm)],
				["Arrival Date", CG.fd(t.actlArvlDt)], ["Entry Customs", U.pair(t.cstmOfceCd, t.cstmOfceCdNm)],
				["Nationality of Vessel(Aircraft)", U.pair(t.natCd, t.natCdNm)], ["Carrier", E(t.carrNm || t.carrCd)],
				["Shipping Agent", U.pair(t.shagCd, t.shagNm || sh(t.shagCd))], ["Cargo Type", U.code("CGM0002", t.cagClsfCd)],
				["B/L (AWB) Type", U.code("CGM0009", t.blTpCd)], ["Forwarder", t.fwdrCd ? U.pair(t.fwdrCd, t.fwdrNm) : E(t.fwdrNm)],
				["Port Of Loading", U.pair(t.loadPortCd, t.loadPortCdNm)], ["Port of Discharge", U.pair(t.dscgPortCd, t.dscgPortCdNm)],
				["Number of Containers(Vehicles)", CG.num(t.blCntrNo)], ["Package", `${CG.num(t.blPckgNo)} ${E(t.blPckgUtCd || t.pckgUtCd || "")}`],
				["Gross Weight", `${CG.num(t.blGwght)} ${E(t.blGwghtUtCd || "")}`], ["Net Weight", `${CG.num(t.blNwght)} ${E(t.blNwghtUtCd || "")}`],
				["Description of Goods", E(t.godsDesc), { wide: true }],
				["Packing Type", U.code("CGM0010", t.pckgTpCd)], ["Place of Delivery", CG.wh_cell(t.dlvrPlcCd, t.dlvrPlcCdNm)],
				["Final Destination", U.pair(t.dstnPlcCd, t.dstnPlcCdNm)], ["Last Location", CG.wh_cell(t.lastGodsLoctCd, t.lastGodsLoctCdNm)],
				["Stock Location", CG.wh_cell(t.stckWrhsCd, t.stckWrhsCdNm)], ["Remarks", E(t.rmrk)],
			].concat(t.asycudCagRgsrNo || t.asycudVygNo ? [["ASYCUDA Registration No", E(t.asycudCagRgsrNo)], ["ASYCUDA Voyage No", E(t.asycudVygNo)]] : [])));
			U.grid($p.show(), { title: "Tracking List", rows: t.blPrcssLst || [], columns: [
				{ label: "Processing Status", cls: "left", render: r => E(r.cagTrkngPrcssCdNm) }, { label: "Processing Date", render: r => CG.fdt(r.prcssDt) },
				{ label: "Location Code", render: r => E(r.wrhsCd) }, { label: "Location Name", cls: "left", render: r => E(r.wrhsCdNm) },
				{ label: "Processing Package", cls: "num", render: r => `${CG.num(r.prcssPckgNo)} ${E(r.prcssPckgUtCd || "")}` }, { label: "Processing Weight", cls: "num", render: r => `${CG.num(r.prcssWght)} ${E(r.prcssWghtUtCd || "")}` },
				{ label: "Carry In-Out Type", render: r => E(r.crioTpCd) }, { label: "Carry In-Out Date", render: r => CG.fdt(r.crioDt) },
				{ label: "Reference No.", render: r => E(r.reffNo) }, { label: "Declaration No", render: r => CG.dclr_fmt(r.dclrNo) },
			] });
			U.grid($c.show(), { title: "Container List", rows: t.blCntrLst || [], columns: [
				{ label: "Container No.", render: (r, i) => `<a class="ji-link" data-c="${i}">${E(r.cntrNo)}</a>` }, { label: "Size", render: r => E(r.cntrSizeCd) },
				{ label: "Type", render: r => U.code("CGM0021", r.loadTpCd) }, { label: "Seal No#1", render: r => E(r.sealNo1) },
				{ label: "Seal No#2", render: r => E(r.sealNo2) }, { label: "Seal No#3", render: r => E(r.sealNo3) },
				{ label: "Freight Indicator", render: r => E(r.frghIdcrCd) }, { label: "Volume", render: r => E(r.cntrVlm) },
				{ label: "Origin Type", render: r => E(r.cagTrkngCntrStatCd) }, { label: "Last Location", render: r => E(r.lastGodsLoctCdNm) },
				{ label: "Stock Location", render: r => E(r.stckWrhsCdNm) }, { label: "Status", render: r => E(r.cagTrkngPrcssCdNm) },
			], bind: ($h, rows) => $h.find("[data-c]").on("click", function () { container(t.crn, rows[Number($(this).attr("data-c"))].cntrNo); }) });
		};
		const container = (crn, cntr) => U.call("tracking_container", { crn, cntr_no: cntr }, __("Loading container...")).then(x => {
			const d = U.modal("Container Detail", U.form_grid([
				["CRN", E(x.crn || crn)], ["Container No.", E(x.cntrNo || cntr)], ["B/L No", E(x.blNo)], ["Vessel", E(x.vsslNm)],
				["Arrival Date", CG.fd(x.actlArvlDt)], ["Container Type", E(x.loadTpCd)], ["Size", E(x.cntrSizeCd)],
				["Seals", E([x.sealNo1, x.sealNo2, x.sealNo3].filter(Boolean).join(" / "))],
				["Package", `${E(x.cntrPckgNo)} ${E(x.pckgUtCd || "")}`], ["Weight", `${E(x.cntrWght)} ${E(x.wghtUtCd || "")}`],
			]) + `<div class="ji-g mt-2"></div>`, "extra-large");
			U.grid(d.$body.find(".ji-g"), { title: "Processing History", rows: x.cntrPrcssLst || [], columns: [
				{ label: "Processing Status", cls: "left", render: r => E(r.cagTrkngPrcssCdNm) }, { label: "Processing Date", render: r => CG.fdt(r.prcssDt) },
				{ label: "Location Code", render: r => E(r.wrhsCd) }, { label: "Location Name", cls: "left", render: r => E(r.wrhsCdNm) },
				{ label: "CRI/CRO Type", render: r => E(r.crioTpCd) }, { label: "CRI/CRO Date", render: r => CG.fdt(r.crioDt) },
				{ label: "Reference No", render: r => E(r.reffNo) }, { label: "Declaration No", render: r => E(r.dclrNo) },
			] });
		});
		const search = () => {
			const f = U.read_form($s); s.form = f;
			U.call("tracking_search", f, __("Searching...")).then(r => {
				if (!r || !r.count) return frappe.msgprint(__("No data found."));
				if (r.count === 1) return show(r.detail);
				const d = U.modal("Cargo Reference No List", `<div class="ji-g"></div>`, "extra-large");
				U.grid(d.$body.find(".ji-g"), { rows: r.crns, columns: [
					{ label: "Cargo Reference No (Full)", render: (x, i) => `<a class="ji-link" data-i="${i}">${CG.crn_fmt(x.crn)}</a>` },
					{ label: "MBL No", render: x => E(x.mblNo) }, { label: "HBL No", render: x => E(x.hblNo) },
					{ label: "Arrival Date", render: x => CG.fd(x.arvlDt) }, { label: "Port of Discharge", render: x => E(x.dscgPortCd) }, { label: "Carrier", render: x => E(x.carrNm) }],
				bind: ($h, rows) => $h.find("[data-i]").on("click", function () { d.hide(); U.call("tracking_detail", { crn: rows[Number($(this).attr("data-i"))].crn }).then(show); }) });
			});
		};
		$s.find(".ji-search").on("click", search);
		$s.find(".ji-reset").on("click", () => { delete CG.st.store.cgme0910001q; CG.st.last_key = null; CG.render(); });
		if (crn_arg) { $s.find('[data-f="srch_crn"]').val(crn_arg); search(); }
	}

	Object.assign(CG.HANDLERS, {
		cgme0302001q: $b => simpl_list($b, "cgme0302001q", "simpl_list", "cgme0302002s", "dclrNo", [["dclrNo", "Declaration No"], ["crn", "CRN"], ["cntrNo", "Container No."]]),
		cgme0302002s: simpl_decl,
		cgme0302011q: $b => simpl_list($b, "cgme0302011q", "simpl_amd_list", "cgme0302012s", "amdDclrNo", [["dclrNo", "Amend Declaration No."], ["bfDclrNo", "Before Declaration No"], ["crn", "CRN"], ["cntrNo", "Container No."]]),
		cgme0302012s: simpl_amd,
		cgme0302021q: $b => simpl_list($b, "cgme0302021q", "simpl_cncl_list", "cgme0302022s", "cnclDclrNo", [["dclrNo", "Cancel Declaration No"], ["bfDclrNo", "Before Declaration No"], ["crn", "CRN"], ["cntrNo", "Container No."]]),
		cgme0302022s: simpl_cncl,
		cgme0401001q: $b => crio_list($b, "cri"),
		cgme0401002s: ($b, ...a) => crio_detail($b, "cri", a),
		cgme0401003s: ($b, ...a) => crio_detail($b, "cri_bl", a),
		cgme0401005q: $b => cri_bulk_list($b),
		cgme0401006s: ($b, ...a) => cri_bulk_detail($b, ...a),
		cgme0401008q: $b => crio_list($b, "cro"),
		cgme0401017s: ($b, ...a) => crio_detail($b, "cro_bl", a),
		cgme0401009s: ($b, ...a) => crio_detail($b, "cro", a),
		cgme0406001q: strp_schedule,
		cgme0406002q: $b => strp_list($b, "cgme0406002q", "strp_report_list", "cgme0406003s", "SRR", "rprtNo", [["rprtNo", "Report No."], ["mrn", "MRN"], ["cntrNo", "Container No."]]),
		cgme0406003s: ($b, no) => strp_report($b, no, "rpt"),
		cgme0406008q: $b => strp_list($b, "cgme0406008q", "strp_amd_list", "cgme0406009s", "SRA", "amdDclrNo", [["rprtNo", "Report No."], ["mrn", "MRN"]]),
		cgme0406009s: ($b, no) => strp_report($b, no, "amd"),
		cgme0406012q: $b => strp_list($b, "cgme0406012q", "strp_cncl_list", "cgme0406013s", "SRC", "cnclDclrNo", [["rprtNo", "Report No."], ["mrn", "MRN"]]),
		cgme0406013s: strp_cncl,
		cgme0910001q: tracking,
	});
})();
