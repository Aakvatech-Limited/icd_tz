// LPCO > Joint Inspection — desk mirror of the TANeSW portal module.
// Routes: /app/tanesw-joint-inspection/<screenId>[/<tansadNo>]
//   eswe0105005q  Inspection Target List      eswe0105006s/<TANSAD>  Target Details
//   eswe0105002q  Inspection Booking List     eswe0105003s/<TANSAD>  Booking Details
//   eswe0105007q  Inspection Result Search
// Popups: 001S Booking Registration, 004S Booking Modify, Booked Result
// Registration, Objection Apply, Attached File List.
(() => {
	const PAGE = "tanesw-joint-inspection";
	const API = "tanesw_integration.joint_inspection.";
	const SIZES = [10, 20, 30, 50, 100, 500, 1000];
	const CODE_GROUPS = ["RKM0019", "ESW0076", "ESW0029", "ESW0009", "CLR0072", "CLR0037",
		"CGM0021", "CGM0010", "CGM0017", "COM0007", "CLR0018", "ESW0040"];
	const SCREENS = {
		eswe0105005q: { title: "Inspection Target List", ui: "UI-ESWE-0105-005Q", menu: true },
		eswe0105006s: { title: "Inspection Target Details", ui: "UI-ESWE-0105-006S", parent: "eswe0105005q" },
		eswe0105002q: { title: "Inspection Booking List", ui: "UI-ESWE-0105-002Q", menu: true },
		eswe0105003s: { title: "Joint Inspection Booking Details", ui: "UI-ESWE-0105-003S", parent: "eswe0105002q" },
		eswe0105007q: { title: "Inspection Result Search", ui: "UI-ESWE-0105-007Q", menu: true },
	};
	const DEFAULT_SCREEN = "eswe0105002q";

	const S = {
		ctx: {}, codes: {}, parties: { warehouses: {}, organisations: {} },
		store: {}, ready: null, $main: null, $nav: null, last_key: null, tin_names: {},
	};

	// ------------------------------------------------------------------ utils
	const esc = v => frappe.utils.escape_html(v == null ? "" : String(v));
	const crn_fmt = v => { const r = String(v || "").replace(/-/g, ""); return r.length > 11 ? esc([r.slice(0, 11), r.slice(11, 15), r.slice(15)].filter(Boolean).join("-")) : esc(v); };  // portal CRN mask 11-4-3
	const today = () => frappe.datetime.get_today();
	const add_days = (d, n) => frappe.datetime.add_days(d, n);
	const add_months = (d, n) => frappe.datetime.add_months(d, n);
	const raw_tansad = v => String(v || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
	const fmt_tansad = v => {
		const r = raw_tansad(v);
		return r.length > 6 ? `${r.slice(0, 4)}-${r.slice(4, 6)}-${r.slice(6, 13)}` : r;
	};
	const ref_no = r => [r.reffTin, r.reffYy, r.reffSrno].filter(Boolean).join("-");

	function parse_dt(v) {
		if (!v) return null;
		const s = String(v).replace(/[^0-9]/g, "");
		if (s.length < 8) return null;
		return { y: s.slice(0, 4), m: s.slice(4, 6), d: s.slice(6, 8), H: s.slice(8, 10), M: s.slice(10, 12) };
	}
	const iso_date = v => { const p = parse_dt(v); return p ? `${p.y}-${p.m}-${p.d}` : ""; };
	const fmt_date = v => { const p = parse_dt(v); return p ? `${p.d}/${p.m}/${p.y}` : ""; };
	const fmt_dt = v => {
		const p = parse_dt(v);
		if (!p) return "";
		return p.H ? `${p.d}/${p.m}/${p.y} ${p.H}:${p.M || "00"}` : `${p.d}/${p.m}/${p.y}`;
	};
	const code = (group, c) => {
		if (c == null || c === "") return "";
		const name = (S.codes[group] || {})[c];
		return name ? `[${esc(c)}] ${esc(name)}` : `[${esc(c)}]`;
	};
	const wh = c => {
		if (!c) return "";
		const n = S.parties.warehouses[c];
		return n ? `[${esc(c)}] ${esc(n)}` : `[${esc(c)}]`;
	};
	const party = c => {
		if (!c) return "";
		const n = String(c).startsWith("OGA") ? S.parties.organisations[c] : S.parties.warehouses[c];
		return n ? `[${esc(c)}] ${esc(n)}` : `[${esc(c)}]`;
	};

	function call(method, args, freeze_message) {
		return new Promise((resolve, reject) => {
			frappe.call({
				method: method.includes(".") ? method : API + method,
				args: args || {},
				freeze: !!freeze_message,
				freeze_message,
				callback: r => resolve(r.message),
				error: e => reject(e),
			});
		});
	}

	function has_auth(key) {
		const list = S.ctx.auth_list || [];
		if (list.length) {
			return key === "warehouse" ? list.some(a => /^auth_cgme00/.test(a)) : list.includes(key);
		}
		// usrInfo did not expose authList: infer from company type as the portal menus do
		return key === "warehouse" ? !S.ctx.is_cfa : S.ctx.is_cfa;
	}

	function write_btn(label, cls, id) {
		const disabled = S.ctx.write_enabled ? "" : `disabled title="${esc(__("Enable write operations in TANeSW Settings"))}"`;
		return `<button class="btn btn-sm ${cls}" id="${id}" ${disabled}>${esc(__(label))}</button>`;
	}

	// ------------------------------------------------------------------ page shell
	frappe.pages[PAGE].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Joint Inspection"), single_column: true });
		// Same menu as Cargo Management (tanesw_nav.js), so every TANeSW screen is one click away.
		const $root = $(`
			<div class="ji-page">
				<nav class="ji-nav" aria-label="${esc(__("TANeSW menu"))}"></nav>
				<div class="ji-col"><div class="tn-status-host"></div><div class="ji-main"></div></div>
			</div>`).appendTo(page.body);
		S.$main = $root.find(".ji-main");
		S.$status = $root.find(".tn-status-host");
		S.$nav = $root.find(".ji-nav");

		S.ready = frappe.require(["/assets/tanesw_integration/css/tanesw_ui.css", "/assets/tanesw_integration/js/tanesw_nav.js"]).then(() => {
			S.nav = window.tanesw_nav.mount(S.$nav);
		}).then(() => Promise.all([
			call("context").then(c => { S.ctx = c || {}; S.$status.html(window.tanesw_nav.status_bar(S.ctx)); }),
			call("codes", { comn_cds: CODE_GROUPS }).then(c => (S.codes = c || {})),
			call("parties").then(p => (S.parties = p || S.parties)).catch(() => {}),
		])).then(() => {  // highlight the current screen once the menu exists
			const sc = SCREENS[frappe.get_route()[1]] ? frappe.get_route()[1] : DEFAULT_SCREEN;
			S.nav.set_active(PAGE, SCREENS[sc].parent || sc);
		});
		frappe.router && frappe.router.on && frappe.router.on("change", () => {
			if (frappe.get_route()[0] === PAGE) render();
		});
	};

	frappe.pages[PAGE].on_page_show = () => {
		render();
		S.ready && S.ready.then(() => call("context").then(c => {  // pick up a changed "Enable Write Operations"
			const changed = !!(c && c.write_enabled) !== !!S.ctx.write_enabled;
			S.ctx = c || S.ctx;
			S.$status && S.$status.html(window.tanesw_nav.status_bar(S.ctx));
			if (changed) { S.last_key = null; render(); }
		}));
	};

	function go(screen, arg) {
		arg ? frappe.set_route(PAGE, screen, arg) : frappe.set_route(PAGE, screen);
	}

	function render() {
		if (!S.$main) return;
		const route = frappe.get_route();
		const screen = SCREENS[route[1]] ? route[1] : DEFAULT_SCREEN;
		const arg = route[2];
		const key = `${screen}/${arg || ""}`;
		if (key === S.last_key && S.$main.children().length) return;
		S.last_key = key;
		const meta = SCREENS[screen];
		const menu_id = meta.parent || screen;
		S.nav && S.nav.set_active(PAGE, menu_id);
		S.$main.html(`
			<div class="ji-title-row">
				<h4 class="ji-title">${esc(__(meta.title))} (${meta.ui})</h4>
				<div class="ji-crumb">LPCO / Joint Inspection / <span>${esc(__(SCREENS[menu_id].title))}</span></div>
			</div>
			<div class="ji-body"><div class="ji-muted p-3">${esc(__("Loading..."))}</div></div>`);
		const $body = S.$main.find(".ji-body");
		S.ready.then(() => {
			const handlers = {
				eswe0105005q: screen_target_list, eswe0105006s: screen_target_detail,
				eswe0105002q: screen_booking_list, eswe0105003s: screen_booking_detail,
				eswe0105007q: screen_result_search,
			};
			$body.empty();
			handlers[screen]($body, arg);
		}).catch(() => {
			$body.html(`<div class="ji-card text-danger">${esc(__("Could not reach TANeSW. Check TANeSW User Account and Settings."))}</div>`);
		});
	}

	// ------------------------------------------------------------------ building blocks
	function tansad_inputs(prefix, v, opts = {}) {
		const ro = opts.readonly ? "readonly" : "";
		return `
			<input class="form-control ji-seg ji-tansad-paste" data-f="${prefix}cstm_ofce_cd" maxlength="4" value="${esc(v.cstm_ofce_cd)}" ${ro} style="text-transform:uppercase">
			<span class="ji-dash">-</span>
			<input class="form-control ji-seg w60" data-f="${prefix}tansad_yy" maxlength="2" inputmode="numeric" value="${esc(v.tansad_yy)}" ${ro}>
			<span class="ji-dash">-</span>
			<input class="form-control ji-seg w110" data-f="${prefix}tansad_srno" maxlength="7" inputmode="numeric" value="${esc(v.tansad_srno)}" ${ro}>`;
	}

	function bind_tansad_paste($el, prefix = "") {
		// Portal behaviour: pasting 'TZDL-26-1747957' into the first box fills all three.
		$el.on("paste", ".ji-tansad-paste", function (e) {
			const t = ((e.originalEvent || e).clipboardData.getData("Text") || "").replace(/[^\w]/g, "").toUpperCase();
			e.preventDefault();
			$el.find(`[data-f="${prefix}cstm_ofce_cd"]`).val(t.slice(0, 4));
			if (t.length > 4) $el.find(`[data-f="${prefix}tansad_yy"]`).val(t.slice(4, 6));
			if (t.length > 6) $el.find(`[data-f="${prefix}tansad_srno"]`).val(t.slice(6, 13));
		});
		$el.on("input", `[data-f="${prefix}tansad_yy"], [data-f="${prefix}tansad_srno"]`, function () {
			this.value = this.value.replace(/[^0-9]/g, "");
		});
	}

	function bind_ref_paste($el) {
		$el.on("paste", ".ji-ref-paste", function (e) {
			const t = ((e.originalEvent || e).clipboardData.getData("Text") || "").replace(/[^\w]/g, "");
			e.preventDefault();
			if (S.ctx.is_cfa && t.length >= 9 && t.slice(0, 9) !== S.ctx.tin) {
				frappe.msgprint(__("The copied TIN number is incorrect."));
				return;
			}
			$el.find('[data-f="reff_tin"]').val(t.slice(0, 9));
			if (t.length > 9) $el.find('[data-f="reff_yy"]').val(t.slice(9, 11));
			if (t.length > 11) $el.find('[data-f="reff_srno"]').val(t.slice(11, 18));
		});
	}

	function date_range(start_f, end_f, v) {
		return `
			<input type="date" class="form-control ji-date" data-f="${start_f}" value="${esc(v[start_f])}">
			<span class="ji-dash">~</span>
			<input type="date" class="form-control ji-date" data-f="${end_f}" value="${esc(v[end_f])}">
			<button class="btn btn-default btn-xs ji-range-btn" data-range="-1M">-1M</button>
			<button class="btn btn-default btn-xs ji-range-btn" data-range="-1W">-1W</button>
			<button class="btn btn-default btn-xs ji-range-btn" data-range="T">${esc(__("Today"))}</button>
			<button class="btn btn-default btn-xs ji-range-btn" data-range="+1W">+1W</button>`;
	}

	function bind_range($el, start_f, end_f) {
		$el.on("click", ".ji-range-btn", function (e) {
			e.preventDefault();
			const t = today();
			const map = { "-1M": [add_months(t, -1), t], "-1W": [add_days(t, -7), t], T: [t, t], "+1W": [t, add_days(t, 7)] };
			const [a, b] = map[$(this).attr("data-range")];
			$el.find(`[data-f="${start_f}"]`).val(a);
			$el.find(`[data-f="${end_f}"]`).val(b);
		});
	}

	function read_form($el) {
		const out = {};
		$el.find("[data-f]").each(function () {
			const $i = $(this);
			if ($i.is(":radio")) { if ($i.is(":checked")) out[$i.attr("data-f")] = $i.val(); return; }
			out[$i.attr("data-f")] = ($i.val() || "").trim();
		});
		return out;
	}

	function grid($host, cfg) {
		// cfg: {columns:[{label, cls, render(row, i)}], rows, meta, size, onPage, onSize, title, index}
		const meta = cfg.meta || { number: 0, totalPages: 1, totalElements: (cfg.rows || []).length };
		const rows = cfg.rows || [];
		const start = (meta.number || 0) * (cfg.size || 10);
		const head = (cfg.index !== false ? "<th></th>" : "") + cfg.columns.map(c => `<th>${esc(__(c.label))}</th>`).join("");
		const body = rows.length ? rows.map((r, i) => `<tr>
			${cfg.index !== false ? `<td class="idx">${cfg.index === "desc" ? rows.length - i : start + i + 1}</td>` : ""}
			${cfg.columns.map(c => `<td class="${c.cls || ""}">${c.render(r, i) ?? ""}</td>`).join("")}
		</tr>`).join("") : `<tr><td class="ji-empty" colspan="${cfg.columns.length + 1}">${esc(__("No data found."))}</td></tr>`;

		let pager = "";
		if (cfg.onPage) {
			const total_pages = Math.max(1, meta.totalPages || 1);
			const cur = meta.number || 0;
			const first = Math.max(0, Math.min(cur - 4, total_pages - 10));
			const last = Math.min(total_pages, first + 10);
			const nums = [];
			for (let p = first; p < last; p++) nums.push(`<button class="btn btn-xs ${p === cur ? "btn-primary" : "btn-default"}" data-page="${p}">${p + 1}</button>`);
			pager = `<div class="ji-pager">
				<div class="left">
					<span>${esc(__("Page"))} : ${rows.length ? cur + 1 : 0} / ${rows.length ? total_pages : 0}</span>
					<select class="form-control ji-size">${SIZES.map(s => `<option ${s === cfg.size ? "selected" : ""}>${s}</option>`).join("")}</select>
					<span>${esc(__("Total"))} : ${meta.totalElements || 0}</span>
				</div>
				<div class="pages">
					<button class="btn btn-xs btn-default" data-page="${Math.max(0, cur - 1)}" ${cur === 0 ? "disabled" : ""}>&lsaquo;</button>
					${nums.join("")}
					<button class="btn btn-xs btn-default" data-page="${Math.min(total_pages - 1, cur + 1)}" ${cur >= total_pages - 1 ? "disabled" : ""}>&rsaquo;</button>
				</div>
			</div>`;
		}
		$host.html(`${cfg.title ? `<div class="ji-card-title">${esc(__(cfg.title))}</div>` : ""}
			<div class="ji-table-wrap"><table class="ji-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${pager}`);
		if (cfg.onPage) {
			$host.find(".pages [data-page]").on("click", function () { cfg.onPage(Number($(this).attr("data-page"))); });
			$host.find(".ji-size").on("change", function () { cfg.onSize(Number($(this).val())); });
		}
		if (cfg.bind) cfg.bind($host, rows);
	}

	function loading($host, cols) {
		$host.html(`<div class="ji-table-wrap"><table class="ji-table"><tbody><tr><td class="ji-empty" colspan="${cols}">
			<span class="spinner-border spinner-border-sm"></span> ${esc(__("Loading from TANeSW..."))}</td></tr></tbody></table></div>`);
	}

	function content_cell(label1, val1, label2, val2) {
		return `<table class="ji-table" style="margin:-1px 0"><tr><td class="left" style="width:45%">${esc(__(label1))}</td><td class="left">${esc(val1 || "")}</td></tr>
			<tr><td class="left">${esc(__(label2))}</td><td class="left">${esc(val2 || "")}</td></tr></table>`;
	}

	// ------------------------------------------------------------------ 005Q Inspection Target List
	function screen_target_list($body) {
		const st = S.store.eswe0105005q || (S.store.eswe0105005q = {
			form: { srch_dt_strt: add_days(today(), -7), srch_dt_end: today(), cplt_yn: "N" }, page: 0, size: 10,
		});
		const f = st.form;
		const $search = $(`<div class="ji-card">
			<div class="ji-form">
				<div class="ji-l">${esc(__("TANSAD Date"))}<span class="req">*</span></div>
				<div class="ji-v wide">${date_range("srch_dt_strt", "srch_dt_end", f)}</div>
				<div class="ji-l">${esc(__("TANSAD No."))}</div><div class="ji-v">${tansad_inputs("", f)}</div>
				<div class="ji-l">${esc(__("Complete"))}</div>
				<div class="ji-v">
					<label class="mr-3"><input type="radio" name="ji-cplt" data-f="cplt_yn" value="Y" ${f.cplt_yn === "Y" ? "checked" : ""}> Y</label>
					<label><input type="radio" name="ji-cplt" data-f="cplt_yn" value="N" ${f.cplt_yn !== "Y" ? "checked" : ""}> N</label>
				</div>
			</div>
			<div class="ji-actions"><button class="btn btn-sm ji-reset">${esc(__("Reset"))}</button>
				<div class="right"><button class="btn btn-sm btn-primary ji-search">${esc(__("Search"))}</button></div></div>
		</div>`).appendTo($body);
		const $grid = $(`<div class="ji-card"></div>`).appendTo($body);
		bind_tansad_paste($search);
		bind_range($search, "srch_dt_strt", "srch_dt_end");

		const columns = [
			{ label: "TANSAD No.", render: r => `<a class="ji-link" data-open="${esc(`${r.cstmOfceCd}-${r.tansadYy}-${r.tansadSrno}`)}">${esc(fmt_tansad(`${r.cstmOfceCd}${r.tansadYy}${r.tansadSrno}`))}</a>` },
			{ label: "Date", render: r => esc(fmt_date(r.isprAsinDt)) },
			{ label: "Declarant", render: r => esc(r.dcltTin) },
			{ label: "Importer/Exporter", render: r => esc(r.tin) },
			{ label: "AEO", render: r => esc(r.aeoYn) },
			{ label: "Item Qty", render: r => esc(r.totItmNo) },
			{ label: "HS Code", render: r => esc(r.hsCd) },
			{ label: "Scanning Report Date", render: r => esc(fmt_dt(r.scnnDt)) },
			{ label: "Booking", render: (r, i) => st.searched_cplt === "N"
				? `<button class="btn btn-xs btn-primary" data-book="${i}" ${S.ctx.write_enabled ? "" : "disabled"}>${esc(__("Booking"))}</button>` : "" },
		];

		function load(page) {
			const form = read_form($search);
			if (!form.srch_dt_strt || !form.srch_dt_end) {
				frappe.show_alert({ message: __("TANSAD Date is required"), indicator: "orange" });
				return;
			}
			Object.assign(st, { form, page: page || 0 });
			st.searched_cplt = form.cplt_yn;
			loading($grid, columns.length + 1);
			call("target_list", { ...form, page: st.page, size: st.size }).then(res => {
				grid($grid, {
					columns, rows: res.content, meta: res.page, size: st.size,
					onPage: p => load(p), onSize: s => { st.size = s; load(0); },
					bind: ($h, rows) => {
						$h.find("[data-open]").on("click", function () { go("eswe0105006s", $(this).attr("data-open")); });
						$h.find("[data-book]").on("click", function () {
							const r = rows[Number($(this).attr("data-book"))];
							open_booking_registration({
								tansad_no: `${r.cstmOfceCd}-${r.tansadYy}-${r.tansadSrno}`, reff_no: ref_no(r), bl_no: r.blNo,
								gods_loct_wrhs_cd: r.godsLoctReffCn, cscl_pln_cd: r.csclPlnCd, regm_cd: r.regmCd,
								gpc_cd: r.gpcCd, epc_cd: r.epcCd, dstn_cnty_cd: r.dstnCntyCd,
							}, () => load(st.page));
						});
					},
				});
			}).catch(() => grid($grid, { columns, rows: [] }));
		}
		$search.find(".ji-search").on("click", () => load(0));
		$search.find(".ji-reset").on("click", () => {
			delete S.store.eswe0105005q; S.last_key = null; render();
		});
		load(st.page);
	}

	// ------------------------------------------------------------------ 006S Inspection Target Details
	function screen_target_detail($body, tansad) {
		const $info = $(`<div class="ji-card"><div class="ji-muted">${esc(__("Loading..."))}</div></div>`).appendTo($body);
		const $grids = $(`<div class="ji-card"></div>`).appendTo($body);
		$(`<div class="ji-actions"><button class="btn btn-sm btn-default">${esc(__("List"))}</button></div>`)
			.appendTo($body).find("button").on("click", () => go("eswe0105005q"));

		call("target_detail", { tansad_no: tansad }).then(d => {
			const c = (d.criteria || [])[0];
			if (!c) {
				frappe.msgprint({ message: __("No data found."), indicator: "orange" });
				go("eswe0105005q");
				return;
			}
			const scan = d.scanning || {};
			const gd = d.guideline || {};
			$info.html(`<div class="ji-form">
				<div class="ji-l">${esc(__("TANSAD No."))}</div><div class="ji-v">${esc(fmt_tansad(`${c.cstmOfceCd || c.cstmOfcdCd || ""}${c.tansadYy}${c.tansadSrno}`))}</div>
				<div class="ji-l">${esc(__("Date"))}</div><div class="ji-v">${esc(fmt_date(c.tansadDt))}</div>
				<div class="ji-l">${esc(__("Importer/Exporter"))}</div><div class="ji-v">${esc([c.imppnTin, c.coNm].filter(Boolean).join(", "))}</div>
				<div class="ji-l">${esc(__("CRN"))}</div><div class="ji-v">${crn_fmt(c.crn)}</div>
				<div class="ji-l">${esc(__("Selectivity Result"))}</div><div class="ji-v">${code("CLR0037", c.sltvRsltCd)}</div>
				<div class="ji-l">${esc(__("Selectivity Date"))}</div><div class="ji-v">${esc(fmt_dt(c.sltvDt))}</div>
				${scan.aprvPrcssStatCd ? `<div class="ji-l">${esc(__("Scanning"))}</div><div class="ji-v">${esc(scan.aprvPrcssStatCd)}</div>
				<div class="ji-l">${esc(__("Scanning Report Date"))}</div><div class="ji-v">${esc(fmt_dt(scan.aprvPrcssDtm))}</div>` : ""}
				${gd.gdlnCn ? `<div class="ji-l">${esc(__("Inspection Guideline"))}</div><div class="ji-v wide">${esc(gd.gdlnCn)}</div>` : ""}
			</div>`);
			const $a = $("<div></div>").appendTo($grids);
			grid($a, { title: "Selectivity Criteria", rows: d.criteria, columns: [
				{ label: "Item No.", render: r => esc(r.itmNo) },
				{ label: "Criteria Register No.", render: r => esc(r.ctraRgsrNo) },
				{ label: "Selectivity Result", render: r => code("CLR0037", r.sltvRsltCd) },
				{ label: "Inspection Guideline", cls: "left", render: r => esc(r.inscIdtnCn) },
			] });
			if ((d.criteria_change || []).length) {
				grid($("<div class='mt-3'></div>").appendTo($grids), { title: "Selectivity Change", rows: d.criteria_change, columns: [
					{ label: "Register Date", render: r => esc(fmt_dt(r.sltvRsltChgDtm)) },
					{ label: "Register Officer", render: r => esc(r.sltvChgOfcrNm) },
					{ label: "Before Selectivity", render: r => code("CLR0037", r.chgBfSltvRsltCd) },
					{ label: "After Selectivity", render: r => code("CLR0037", r.chgAfSltvRsltCd) },
					{ label: "Remark", cls: "left", render: r => esc(r.sltvChgRmrk) },
				] });
			}
			grid($("<div class='mt-3'></div>").appendTo($grids), { title: "Item List", rows: d.items || [], index: false, columns: [
				{ label: "No", render: r => esc(r.itmNo) },
				{ label: "HS Code", render: r => esc(r.hsCd) },
				{ label: "Product Name", cls: "left", render: r => esc(r.hsDesc) },
				{ label: "Country of Origin", render: r => esc(r.origCntyCd) },
				{ label: "Modified HS Code", render: r => esc(r.mdfyHsCd) },
				{ label: "Modified Country of Origin", render: r => esc(r.mdfyOrigCntyCd) },
				{ label: "Detection", render: r => esc(r.dtcnYn) },
			] });
		}).catch(() => $info.html(`<div class="text-danger">${esc(__("Failed to load target details"))}</div>`));
	}

	// ------------------------------------------------------------------ 002Q Inspection Booking List
	function screen_booking_list($body) {
		const st = S.store.eswe0105002q || (S.store.eswe0105002q = {
			form: { srch_dt_strt: add_months(today(), -1), srch_dt_end: today(), reff_tin: S.ctx.is_cfa ? S.ctx.tin : "" },
			page: 0, size: 10,
		});
		const f = st.form;
		const statuses = S.codes.RKM0019 || {};
		const $search = $(`<div class="ji-card">
			<div class="ji-form">
				<div class="ji-l">${esc(__("TANSAD No."))}</div><div class="ji-v">${tansad_inputs("", f)}</div>
				<div class="ji-l">${esc(__("Reference No."))}</div>
				<div class="ji-v">
					<input class="form-control ji-seg w110 ji-ref-paste" data-f="reff_tin" maxlength="9" inputmode="numeric" value="${esc(f.reff_tin)}" ${S.ctx.is_cfa ? "readonly" : ""}>
					<span class="ji-dash">-</span><input class="form-control ji-seg w60" data-f="reff_yy" maxlength="2" inputmode="numeric" value="${esc(f.reff_yy)}">
					<span class="ji-dash">-</span><input class="form-control ji-seg w110" data-f="reff_srno" maxlength="7" inputmode="numeric" value="${esc(f.reff_srno)}">
				</div>
				<div class="ji-l">${esc(__("Date"))}</div><div class="ji-v">${date_range("srch_dt_strt", "srch_dt_end", f)}</div>
				<div class="ji-l">${esc(__("Status"))}</div>
				<div class="ji-v"><select class="form-control" data-f="srch_stat_cd">
					<option value="">${esc(__("All"))}</option>
					${Object.entries(statuses).map(([k, v]) => `<option value="${esc(k)}" ${f.srch_stat_cd === k ? "selected" : ""}>${esc(v)}</option>`).join("")}
				</select></div>
			</div>
			<div class="ji-actions"><button class="btn btn-sm ji-reset">${esc(__("Reset"))}</button>
				<div class="right"><button class="btn btn-sm btn-primary ji-search">${esc(__("Search"))}</button></div></div>
		</div>`).appendTo($body);
		const $grid = $(`<div class="ji-card"></div>`).appendTo($body);
		bind_tansad_paste($search);
		bind_ref_paste($search);
		bind_range($search, "srch_dt_strt", "srch_dt_end");
		$search.on("input", '[data-f^="reff_"]', function () { this.value = this.value.replace(/[^0-9]/g, ""); });

		const columns = [
			{ label: "TANSAD No.", render: r => `<a class="ji-link" data-open="${esc(raw_tansad(r.tansadNo))}">${esc(fmt_tansad(r.tansadNo))}</a>` },
			{ label: "Reference No.", render: r => esc(ref_no(r)) },
			{ label: "Cargo Type", render: r => esc(r.cntrLstCn) },
			{ label: "Booking Request Date", render: r => esc(fmt_date(r.bkngRqstDt)) },
			{ label: "Booking Approval Date", render: r => esc(fmt_dt(r.bkngAprvDtm)) },
			{ label: "Approval Date", render: r => esc(fmt_dt(r.aprvDtm)) },
			{ label: "Inspection Confirmation Date", render: r => esc(fmt_dt(r.bkngCfrmDtm)) },
			{ label: "Inspection Type", render: r => code("ESW0076", r.jntInscTpCd) },
			{ label: "Status", render: (r, i) => r.prcsStatCd === "G"
				? `<button class="btn btn-xs btn-primary" data-rebook="${i}" ${S.ctx.write_enabled ? "" : "disabled"}>${esc(__("Booking"))}</button>`
				: code("RKM0019", r.prcsStatCd) },
		];

		function load(page) {
			const form = read_form($search);
			Object.assign(st, { form, page: page || 0 });
			loading($grid, columns.length + 1);
			call("booking_list", { ...form, page: st.page, size: st.size }).then(res => {
				grid($grid, {
					columns, rows: res.content, meta: res.page, size: st.size,
					onPage: p => load(p), onSize: s => { st.size = s; load(0); },
					bind: ($h, rows) => {
						$h.find("[data-open]").on("click", function () { go("eswe0105003s", $(this).attr("data-open")); });
						$h.find("[data-rebook]").on("click", function () {
							const r = rows[Number($(this).attr("data-rebook"))];
							open_booking_registration({
								tansad_no: fmt_tansad(r.tansadNo), reff_no: ref_no(r), bl_no: r.blNo,
								gods_loct_wrhs_cd: r.godsLoctReffCn, prcs_stat_cd: r.prcsStatCd, is_resubmit: 1,
							}, () => load(st.page));
						});
					},
				});
			}).catch(() => grid($grid, { columns, rows: [] }));
		}
		$search.find(".ji-search").on("click", () => load(0));
		$search.find(".ji-reset").on("click", () => { delete S.store.eswe0105002q; S.last_key = null; render(); });
		load(st.page);
	}

	// ------------------------------------------------------------------ 003S Booking Details
	function screen_booking_detail($body, tansad) {
		const $head = $(`<div class="ji-card"><div class="ji-muted">${esc(__("Loading..."))}</div></div>`).appendTo($body);
		const $tabs = $(`<div class="ji-card"></div>`).appendTo($body);

		call("booking_detail", { tansad_no: tansad }).then(d => {
			const b = d.jntInscBkngInfo;
			if (!b) {
				frappe.msgprint({ message: __("No data found."), indicator: "orange" });
				go("eswe0105002q");
				return;
			}
			const t = d.tansadInfo || {};
			const st = b.prcsStatCd;
			const loc = b.mdfyGodsLoctWrhsCd != null ? b.mdfyGodsLoctWrhsCd : b.godsLoctWrhsCd;
			const extra = st === "B"
				? `<div class="ji-l">${esc(__("Booking Approval Date"))}</div><div class="ji-v wide">${esc(fmt_dt(b.bkngAprvDtm))}</div>`
				: st === "C"
					? `<div class="ji-l">${esc(__("Booking Approval Date"))}</div><div class="ji-v">${esc(fmt_dt(b.bkngAprvDtm))}</div>
					   <div class="ji-l">${esc(__("Inspection Confirmation Date"))}</div><div class="ji-v">${esc(fmt_dt(b.inscCfrmDt))}</div>
					   <div class="ji-l">${esc(__("Approval Date"))}</div><div class="ji-v wide">${esc(fmt_dt(b.aprvDtm))}</div>`
					: "";
			const can_modify = has_auth("auth_clre0001") && b.cagBkngYn !== "Y" && st === "B";
			const can_register = has_auth("warehouse") && b.cagBkngYn === "Y" && st === "B";

			$head.html(`<div class="ji-form">
					<div class="ji-l">${esc(__("TANSAD No."))}</div><div class="ji-v">${esc(fmt_tansad(b.tansadNo).replace(/-/g, " - "))}</div>
					<div class="ji-l">${esc(__("Status"))}</div><div class="ji-v">${code("RKM0019", st)}</div>
					<div class="ji-l">${esc(__("B/L No"))}</div><div class="ji-v">${esc(b.blNo)}</div>
					<div class="ji-l">${esc(__("Location of Goods"))}</div><div class="ji-v">${wh(loc)}</div>
					<div class="ji-l">${esc(__("Container Count"))}</div><div class="ji-v">${esc(b.cntrCnt)}</div>
					<div class="ji-l">${esc(__("Container List"))}</div><div class="ji-v">${esc(b.cntrLstCn)}</div>
					<div class="ji-l">${esc(__("Booking Request Date"))}</div><div class="ji-v">${esc(fmt_date(b.bkngRqstDt))}</div>
					<div class="ji-l">${esc(__("Booking Modify Date"))}</div><div class="ji-v">${esc(fmt_date(b.bkngMdfyRqstDt))}</div>
					<div class="ji-l">${esc(__("Inspection Zone"))}</div><div class="ji-v wide">${esc(b.jntInscZoneAddr)}</div>
					${st !== "A" ? extra : ""}
				</div>
				<div class="ji-actions">
					<button class="btn btn-sm btn-default" id="ji-list">${esc(__("List"))}</button>
					<div class="right">
						${can_modify ? write_btn("Modify", "btn-danger", "ji-modify") : ""}
						${can_register ? write_btn("Booked Result Registration", "btn-primary", "ji-result-reg") : ""}
						<button class="btn btn-sm btn-default" id="ji-erp">${esc(__("Save to ERPNext"))}</button>
						<a class="btn btn-sm btn-default" href="/app/tanesw-inspection-booking/${esc(raw_tansad(b.tansadNo))}" target="_blank">${esc(__("Open in Desk"))}</a>
					</div>
				</div>`);
			$head.find("#ji-list").on("click", () => go("eswe0105002q"));
			$head.find("#ji-modify").on("click", () => open_booking_modify({
				tansad_no: fmt_tansad(b.tansadNo), reff_no: ref_no(t), bkng_dt: b.bkngRqstDt, bl_no: t.blNo || b.blNo,
				gods_loct_wrhs_cd: b.godsLoctWrhsCd, cntr_lst_cn: b.cntrLstCn, jnt_insc_zone_addr: b.jntInscZoneAddr,
			}, () => { S.last_key = null; render(); }));
			$head.find("#ji-result-reg").on("click", () => open_result_registration(raw_tansad(b.tansadNo), () => { S.last_key = null; render(); }));
			$head.find("#ji-erp").on("click", function () {
				const $b = $(this);
				call("tanesw_integration.api.import_booking_record", { tansad_no: raw_tansad(b.tansadNo) }, __("Saving to ERPNext...")).then(r => {
					if (r && r.status === "ok") { frappe.show_alert({ message: __("Saved {0}", [r.name]), indicator: "green" }); $b.prop("disabled", true).text(__("Saved")); }
				});
			});
			render_booking_tabs($tabs, b, d);
		}).catch(() => $head.html(`<div class="text-danger">${esc(__("Failed to load booking details"))}</div>`));
	}

	function render_booking_tabs($tabs, b, d) {
		$tabs.html(`<div class="ji-tabs"><a class="active" data-tab="g">${esc(__("TANSAD General"))}</a><a data-tab="h">${esc(__("Approval History"))}</a></div>
			<div class="ji-tab-body"></div>`);
		const $tb = $tabs.find(".ji-tab-body");
		const show = tab => {
			$tabs.find(".ji-tabs a").removeClass("active").filter(`[data-tab="${tab}"]`).addClass("active");
			tab === "g" ? render_tansad_general($tb, d) : render_approval_history($tb, b.tansadNo);
		};
		$tabs.find(".ji-tabs a").on("click", function () { show($(this).attr("data-tab")); });
		show("g");
	}

	function tin_label(tin, fallback_name) {
		if (!tin) return "";
		const name = S.tin_names[tin] || fallback_name;
		return name ? `[${esc(tin)}] ${esc(name)}` : `[${esc(tin)}]`;
	}

	function resolve_tin_names($host, tins) {
		tins.filter(x => x && !S.tin_names[x]).forEach(tin => {
			call("tanesw_integration.api.tin_no_list", { tin_no: tin }).then(rows => {
				const row = (Array.isArray(rows) ? rows : []).find(r => Object.values(r || {}).includes(tin));
				const name = row && (row.coNm || row.tinNm || row.txpyrNm || row.nm);
				if (name) { S.tin_names[tin] = name; $host.find(`[data-tin="${tin}"]`).html(tin_label(tin)); }
			}).catch(() => {});
		});
	}

	function render_tansad_general($tb, d) {
		const t = d.tansadInfo || {};
		const cntrs = Array.isArray(d.cntrInfo) ? d.cntrInfo : [];
		const booked = new Set((d.jntInscCntrInfo || []).map(c => c.cntrNo));
		const pckg = (d.blInfo || {}).pckgTpCd;
		$tb.html(`<div class="ji-card-title">${esc(__("Declaration Details"))}</div>
			<div class="ji-form">
				<div class="ji-l">${esc(__("Mode of Declaration"))}</div><div class="ji-v">${code("CLR0072", t.decMode)}</div>
				<div class="ji-l">${esc(__("Selectivity Result"))}</div><div class="ji-v">${code("CLR0037", t.sltvRsltCd)}</div>
				<div class="ji-l">${esc(__("Importer/Exporter"))}</div><div class="ji-v" data-tin="${esc(t.tin)}">${tin_label(t.tin, t.coNm || t.imppnNm)}</div>
				<div class="ji-l">${esc(__("Declarant"))}</div><div class="ji-v" data-tin="${esc(t.dcltTin)}">${tin_label(t.dcltTin, t.dcltNm)}</div>
				<div class="ji-l">${esc(__("CRN"))}</div><div class="ji-v">${t.crn ? `<a class="ji-link" target="_blank" href="https://tanesw.tra.go.tz/cgme/mnfs/imp/sea/CGME0101027Q/${esc(t.crn)}">${crn_fmt(t.crn)}</a>` : ""}</div>
				<div class="ji-l">${esc(__("Location of Goods"))}</div><div class="ji-v">${wh(t.godsLoctReffCn)}</div>
			</div>
			<div class="ji-cntr mt-3"></div>`);
		resolve_tin_names($tb, [t.tin, t.dcltTin]);
		if (cntrs.length && pckg !== "B" && pckg !== "L") {
			const $c = $tb.find(".ji-cntr");
			grid($c, {
				title: `${__("Total Containers/Vehicles available for Inspection")} : ${cntrs.length}`,
				rows: cntrs,
				columns: [
					{ label: "", render: r => `<input type="checkbox" disabled ${booked.has(r.CNTR_NO) ? "checked" : ""}>` },
					{ label: "Container No.", render: r => esc(r.CNTR_NO) },
					{ label: "Loading Type", render: r => code("CGM0021", r.LOAD_TP_CD) },
					{ label: "Container Size", render: r => code("CGM0010", r.CNTR_SIZE_CD) },
					{ label: "Seal #1", render: r => esc(r.SEAL_NO_1) },
					{ label: "Seal #2", render: r => esc(r.SEAL_NO_2) },
					{ label: "Seal #3", render: r => esc(r.SEAL_NO_3) },
					{ label: "Freight Indicator", render: r => code("CGM0017", r.FRGH_IDCR_CD) },
					{ label: "Package Unit", render: r => code("COM0007", r.PCKG_UT_CD) },
					{ label: "Container Weight", render: r => r.CNTR_WGHT == null ? "" : esc(Number(r.CNTR_WGHT).toLocaleString()) },
					{ label: "Weight Unit", render: r => esc(r.WGHT_UT_CD) },
				],
			});
		}
	}

	function render_approval_history($tb, tansad_no) {
		$tb.html(`<div class="ji-card-title">${esc(__("Approval History"))}</div><div class="ji-h"></div>`);
		const $h = $tb.find(".ji-h");
		loading($h, 6);
		call("approval_history", { tansad_no }).then(rows => {
			grid($h, { rows: rows || [], index: "desc", columns: [
				{ label: "Target", cls: "left", render: r => party(r.orgCd) },
				{ label: "Status", render: r => r.prcssStatCd ? esc((S.codes.ESW0029 || {})[r.prcssStatCd] || r.prcssStatCd) : "" },
				{ label: "Processing Status", render: r => r.asnmtOfcrTpCd ? code("ESW0009", r.asnmtOfcrTpCd) : "" },
				{ label: "Process Date", render: r => esc(fmt_dt(r.prcssDtm)) },
				{ label: "Content", cls: "left", render: r => content_cell("Conditions of Approval", r.prcssCn, "Remarks", r.rmrk) },
			] });
		}).catch(() => grid($h, { rows: [], columns: [{ label: "Target", render: () => "" }] }));
	}

	// ------------------------------------------------------------------ 007Q Inspection Result Search
	function screen_result_search($body) {
		const st = S.store.eswe0105007q || (S.store.eswe0105007q = { form: {}, page: 0, size: 10 });
		const $search = $(`<div class="ji-card">
			<div class="ji-form">
				<div class="ji-l">${esc(__("TANSAD No."))}<span class="req">*</span></div><div class="ji-v wide">${tansad_inputs("", st.form)}</div>
			</div>
			<div class="ji-actions"><button class="btn btn-sm ji-reset">${esc(__("Reset"))}</button>
				<div class="right"><button class="btn btn-sm btn-primary ji-search">${esc(__("Search"))}</button></div></div>
		</div>`).appendTo($body);
		const $grid = $(`<div class="ji-card" style="display:none"></div>`).appendTo($body);
		bind_tansad_paste($search);

		const columns = [
			{ label: "OGA", cls: "left", render: r => esc(r.orgNm || r.orgCd) },
			{ label: "Status", render: r => esc(r.prcssStatNm || r.prcssStatCd) },
			{ label: "Processing Status", render: r => esc(r.asnmtOfcrTpNm) },
			{ label: "Process Date", render: r => esc(fmt_dt(r.prcssDtm)) },
			{ label: "Content", cls: "left", render: r => content_cell("Conditions of Approval", r.prcssCn, "Remarks", r.rmrk) },
			{ label: "Attached File", render: (r, i) => Number(r.atcmCnt) > 0 ? `<button class="btn btn-xs btn-primary" data-atcm="${i}">${esc(__("Attached File"))}</button>` : "" },
			{ label: "Objection Apply", render: (r, i) => (r.orgCd === "OGAM0001" && !r.objtAplyNo)
				? `<button class="btn btn-xs btn-primary" data-objt="${i}" ${S.ctx.write_enabled ? "" : "disabled"}>${esc(__("Objection Apply"))}</button>`
				: esc(r.objtAplyNo) },
		];

		function load(page) {
			const form = read_form($search);
			if (!form.cstm_ofce_cd || !form.tansad_yy || !form.tansad_srno) {
				frappe.show_alert({ message: __("TANSAD No. is required"), indicator: "orange" });
				return;
			}
			Object.assign(st, { form, page: page || 0 });
			const tansad_no = `${form.cstm_ofce_cd.toUpperCase()}${form.tansad_yy}${form.tansad_srno}`;
			$grid.show();
			loading($grid, columns.length + 1);
			call("inspection_results", { tansad_no, page: st.page, size: st.size }).then(res => {
				grid($grid, {
					title: "Inspection Results", columns, rows: res.content, meta: res.page, size: st.size,
					onPage: p => load(p), onSize: s => { st.size = s; load(0); },
					bind: ($h, rows) => {
						$h.find("[data-atcm]").on("click", () => open_attachments(tansad_no));
						$h.find("[data-objt]").on("click", function () {
							const r = rows[Number($(this).attr("data-objt"))];
							open_objection({ tansad_no: r.tansadNo || tansad_no, org_cd: r.orgCd, bl_no: r.blNo }, () => load(st.page));
						});
					},
				});
			}).catch(() => grid($grid, { title: "Inspection Results", columns, rows: [] }));
		}
		$search.find(".ji-search").on("click", () => load(0));
		$search.find(".ji-reset").on("click", () => { delete S.store.eswe0105007q; S.last_key = null; render(); });
		if (st.form.tansad_srno) load(st.page);
	}

	// ------------------------------------------------------------------ popups
	function modal(title, html, size = "large") {
		const d = new frappe.ui.Dialog({ title: __(title), size });
		d.$body.html(`<div class="ji-modal">${html}</div>`);
		d.show();
		return d;
	}

	function wh_datalist(id) {
		return `<datalist id="${id}">${Object.entries(S.parties.warehouses || {})
			.map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</datalist>`;
	}

	function confirm_then(msg, fn) { frappe.confirm(__(msg), fn); }

	// 001S Joint Inspection Booking Registration
	function open_booking_registration(p, done) {
		const resubmit = !!p.is_resubmit;
		const d = modal("Joint Inspection Booking Registration", `
			<div class="ji-form">
				<div class="ji-l">${esc(__("TANSAD No."))}<span class="req">*</span></div><div class="ji-v">${esc(p.tansad_no)}</div>
				<div class="ji-l">${esc(__("Reference No."))}<span class="req">*</span></div><div class="ji-v">${esc(p.reff_no)}</div>
				<div class="ji-l">${esc(__("B/L No"))}<span class="req">*</span></div><div class="ji-v"><input class="form-control" data-f="bl_no" value="${esc(p.bl_no)}"></div>
				<div class="ji-l">${esc(__("Booking Date"))}<span class="req">*</span></div><div class="ji-v"><input type="date" class="form-control ji-date" data-f="bkng_dt" min="${today()}" value="${today()}"></div>
				<div class="ji-l">${esc(__("Cargo Deposit Station"))}<span class="req">*</span></div>
				<div class="ji-v"><input class="form-control" list="ji-wh-a" data-f="gods_loct_wrhs_cd" value="${esc(p.gods_loct_wrhs_cd)}" ${resubmit ? "readonly" : ""}>${wh_datalist("ji-wh-a")}</div>
				<div class="ji-l">${esc(__("Cargo Type"))}<span class="req">*</span></div>
				<div class="ji-v"><select class="form-control" data-f="cntr_lst_cn"><option value=""></option>${(S.ctx.cargo_types || []).map(c => `<option>${c}</option>`).join("")}</select></div>
				${resubmit ? `<div class="ji-l">${esc(__("Modified Cargo Deposit Station"))}<span class="req">*</span></div>
					<div class="ji-v wide"><input class="form-control" list="ji-wh-b" data-f="mdfy_gods_loct_wrhs_cd">${wh_datalist("ji-wh-b")}</div>` : ""}
				<div class="ji-l">${esc(__("Inspection Zone"))}</div><div class="ji-v wide"><textarea class="form-control" data-f="jnt_insc_zone_addr"></textarea></div>
			</div>
			<div class="ji-actions"><button class="btn btn-sm ji-reset">${esc(__("Reset"))}</button>
				<div class="right">${write_btn("Submit", "btn-primary", "ji-submit")}</div></div>`);
		const $b = d.$body;
		if (p.prcs_stat_cd === "G") {
			// Re-submit: the portal pre-fills from the existing booking
			call("booking_detail", { tansad_no: p.tansad_no }).then(r => {
				const b = (r || {}).jntInscBkngInfo || {};
				const t = (r || {}).tansadInfo || {};
				if (b.blNo) $b.find('[data-f="bl_no"]').val(b.blNo);
				if (b.bkngRqstDt && iso_date(b.bkngRqstDt) >= today()) $b.find('[data-f="bkng_dt"]').val(iso_date(b.bkngRqstDt));
				if (b.godsLoctWrhsCd) $b.find('[data-f="gods_loct_wrhs_cd"]').val(b.godsLoctWrhsCd);
				if (b.cntrLstCn) $b.find('[data-f="cntr_lst_cn"]').val(b.cntrLstCn);
				if (b.jntInscZoneAddr) $b.find('[data-f="jnt_insc_zone_addr"]').val(b.jntInscZoneAddr);
				if (t.reffTin) $b.find(".ji-v").eq(1).text(ref_no(t));
			}).catch(() => {});
		}
		$b.find(".ji-reset").on("click", () => $b.find("input:not([readonly]), select, textarea").val(""));
		$b.find("#ji-submit").on("click", () => {
			const form = { ...p, ...read_form($b) };
			confirm_then("Do you want to submit?", () =>
				call("register_booking", { form }, __("Submitting booking to TANeSW...")).then(() => {
					frappe.show_alert({ message: __("Booking submitted"), indicator: "green" });
					d.hide(); done && done();
				}));
		});
	}

	// 004S Booking Modify
	function open_booking_modify(p, done) {
		const d = modal("Joint Inspection Booking Modify", `
			<div class="ji-form">
				<div class="ji-l">${esc(__("TANSAD No."))}</div><div class="ji-v">${esc(p.tansad_no)}</div>
				<div class="ji-l">${esc(__("Reference No."))}</div><div class="ji-v">${esc(p.reff_no)}</div>
				<div class="ji-l">${esc(__("B/L No"))}</div><div class="ji-v">${esc(p.bl_no)}</div>
				<div class="ji-l">${esc(__("Booking Date"))}</div><div class="ji-v">${esc(fmt_date(p.bkng_dt))}</div>
				<div class="ji-l">${esc(__("Cargo Deposit Station"))}</div><div class="ji-v">${wh(p.gods_loct_wrhs_cd)}</div>
				<div class="ji-l">${esc(__("Cargo Type"))}</div><div class="ji-v">${esc(p.cntr_lst_cn)}</div>
				<div class="ji-l">${esc(__("Modified Cargo Deposit Station"))}<span class="req">*</span></div>
				<div class="ji-v"><input class="form-control" list="ji-wh-m" data-f="mdfy_gods_loct_wrhs_cd">${wh_datalist("ji-wh-m")}</div>
				<div class="ji-l">${esc(__("Booking Modify Date"))}<span class="req">*</span></div>
				<div class="ji-v"><input type="date" class="form-control ji-date" data-f="bkng_mdfy_rqst_dt" min="${today()}"></div>
				<div class="ji-l">${esc(__("Inspection Zone"))}</div><div class="ji-v wide"><textarea class="form-control" data-f="jnt_insc_zone_addr">${esc(p.jnt_insc_zone_addr)}</textarea></div>
			</div>
			<div class="ji-actions"><button class="btn btn-sm ji-reset">${esc(__("Reset"))}</button>
				<div class="right">${write_btn("Submit", "btn-primary", "ji-submit")}</div></div>`);
		const $b = d.$body;
		$b.find(".ji-reset").on("click", () => $b.find("input, textarea").val(""));
		$b.find("#ji-submit").on("click", () => {
			const form = { ...p, ...read_form($b) };
			confirm_then("Do you want to submit?", () =>
				call("modify_booking", { form }, __("Submitting modification to TANeSW...")).then(() => {
					frappe.show_alert({ message: __("Booking modified"), indicator: "green" });
					d.hide(); done && done();
				}));
		});
	}

	// Booked Result Registration (verification result by the cargo-booking warehouse)
	function open_result_registration(tansad_no, done) {
		call("result_registration_info", { tansad_no }, __("Loading booking...")).then(info => {
			const b = info.booking || {};
			const a = info.approval || {};
			const d = modal("Booked Result Registration", `
				${info.can_save ? "" : `<div class="ji-banner warn">${esc(__("The booked inspection date has not arrived. Set a Booking Modify Date to register the result."))}</div>`}
				<div class="ji-card-title">${esc(__("Verification Result"))}</div>
				<div class="ji-form">
					<div class="ji-l">${esc(__("TANSAD No."))}</div><div class="ji-v">${esc(fmt_tansad(tansad_no))}</div>
					<div class="ji-l">${esc(__("Reference No."))}</div><div class="ji-v">${esc(ref_no(b))}</div>
					<div class="ji-l">${esc(__("B/L No"))}</div><div class="ji-v">${esc(b.blNo)}</div>
					<div class="ji-l">${esc(__("Booking Request Date"))}</div><div class="ji-v">${esc(fmt_date(b.bkngRqstDt))}</div>
					<div class="ji-l">${esc(__("Location of Goods"))}</div><div class="ji-v">${wh(b.godsLoctWrhsCd)}</div>
					${info.needs_modify_date ? `<div class="ji-l">${esc(__("Booking Modify Date"))}<span class="req">*</span></div>
						<div class="ji-v"><input type="date" class="form-control ji-date" data-f="bkng_mdfy_rqst_dt" value="${esc(iso_date(b.bkngMdfyRqstDt))}"></div>`
						: `<div class="ji-l"></div><div class="ji-v"></div>`}
					<div class="ji-l">${esc(__("Verification Result"))}<span class="req">*</span></div>
					<div class="ji-v wide"><select class="form-control" data-f="prcss_stat_cd"><option value="AP">${esc(__("Approved"))}</option></select></div>
					<div class="ji-l">${esc(__("Verification Reason"))}<span class="req">*</span></div>
					<div class="ji-v wide"><textarea class="form-control" data-f="prcss_rsn_cn">${esc(a.prcssRsnCn)}</textarea></div>
					<div class="ji-l">${esc(__("Inspection Remarks"))}</div>
					<div class="ji-v wide"><textarea class="form-control" data-f="rmrk">${esc(a.rmrk)}</textarea></div>
				</div>
				<div class="ji-actions"><span></span><div class="right">
					${info.can_save || info.needs_modify_date ? write_btn("Save", "btn-default", "ji-save") : ""}
					${info.can_confirm ? write_btn("Confirm", "btn-primary", "ji-confirm") : ""}
				</div></div>`);
			const $b = d.$body;
			const submit = action => {
				const form = read_form($b);
				if (!form.prcss_rsn_cn) { frappe.show_alert({ message: __("Verification Reason is required"), indicator: "orange" }); return; }
				if (!info.can_save && !form.bkng_mdfy_rqst_dt) { frappe.show_alert({ message: __("Booking Modify Date is required"), indicator: "orange" }); return; }
				confirm_then(action === "save" ? "Do you want to save?" : "Do you want to submit?", () =>
					call("save_result_registration", { tansad_no, action, ...form },
						action === "save" ? __("Saving result in TANeSW...") : __("Confirming result in TANeSW...")).then(() => {
						frappe.show_alert({ message: action === "save" ? __("Saved") : __("Confirmed"), indicator: "green" });
						d.hide();
						action === "save" ? open_result_registration(tansad_no, done) : (done && done());
					}));
			};
			$b.find("#ji-save").on("click", () => submit("save"));
			$b.find("#ji-confirm").on("click", () => submit("sbmt"));
		});
	}

	function open_attachments(tansad_no) {
		const d = modal("Attached File List", `<div class="ji-atcm"></div>
			<div class="ji-actions"><span></span><div class="right"><button class="btn btn-sm btn-danger ji-close">${esc(__("Close"))}</button></div></div>`, "small");
		d.$body.find(".ji-close").on("click", () => d.hide());
		const $h = d.$body.find(".ji-atcm");
		const st = { page: 0, size: 10 };
		const columns = [
			{ label: "Document Type", cls: "left", render: r => code("CLR0018", r.atcmTpCd) },
			{ label: "Attached File", cls: "left", render: r => esc(r.atchFile && (r.atchFile.fileNm || r.atchFile.orgnFileNm || r.atchFile.name) || r.atchFileNm || r.atchFile) },
		];
		const load = page => {
			st.page = page;
			loading($h, 3);
			call("inspection_attachments", { tansad_no, page, size: st.size }).then(res => grid($h, {
				columns, rows: res.content, meta: res.page, size: st.size,
				onPage: p => load(p), onSize: s => { st.size = s; load(0); },
			}));
		};
		load(0);
	}

	function open_objection(p, done) {
		const d = modal("Joint Inspection Objection Apply", `
			<div class="ji-form">
				<div class="ji-l">${esc(__("TIN"))}<span class="req">*</span></div><div class="ji-v">${esc(S.ctx.tin)}</div>
				<div class="ji-l">${esc(__("Year"))}<span class="req">*</span></div><div class="ji-v">${esc(today().slice(2, 4))}</div>
				<div class="ji-l">${esc(__("TANSAD No."))}<span class="req">*</span></div><div class="ji-v">${esc(fmt_tansad(p.tansad_no))}</div>
				<div class="ji-l">${esc(__("B/L No"))}</div><div class="ji-v">${esc(p.bl_no)}</div>
				<div class="ji-l">${esc(__("Objection Type"))}<span class="req">*</span></div>
				<div class="ji-v wide"><select class="form-control" data-f="jnt_insc_rslt_accpt_cd"><option value=""></option>
					${Object.entries(S.codes.ESW0040 || {}).map(([k, v]) => `<option value="${esc(k)}">[${esc(k)}] ${esc(v)}</option>`).join("")}</select></div>
				<div class="ji-l">${esc(__("Objection Content"))}<span class="req">*</span></div>
				<div class="ji-v wide"><textarea class="form-control" maxlength="2000" data-f="apear_rsn"></textarea></div>
			</div>
			<div class="ji-actions"><button class="btn btn-sm ji-reset">${esc(__("Reset"))}</button>
				<div class="right">${write_btn("Submit", "btn-primary", "ji-submit")}</div></div>`, "large");
		const $b = d.$body;
		$b.find(".ji-reset").on("click", () => $b.find("select, textarea").val(""));
		$b.find("#ji-submit").on("click", () => {
			const form = read_form($b);
			confirm_then("Do you want to submit?", () =>
				call("submit_objection", { ...p, ...form }, __("Submitting objection to TANeSW...")).then(() => {
					frappe.show_alert({ message: __("Objection submitted"), indicator: "green" });
					d.hide(); done && done();
				}));
		});
	}
})();
