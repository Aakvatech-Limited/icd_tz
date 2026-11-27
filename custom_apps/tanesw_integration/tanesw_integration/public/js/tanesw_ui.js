// Shared helpers for TANeSW portal-style desk pages (window.tanesw_ui).
(() => {
	if (window.tanesw_ui) return;
	const SIZES = [10, 20, 30, 50, 100, 500, 1000];
	const esc = v => frappe.utils.escape_html(v == null ? "" : String(v));
	const today = () => frappe.datetime.get_today();
	const add_days = (d, n) => frappe.datetime.add_days(d, n);
	const add_months = (d, n) => frappe.datetime.add_months(d, n);

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
	const fmt_num = v => (v == null || v === "" || isNaN(Number(v))) ? esc(v) : esc(Number(v).toLocaleString());

	function make(api_prefix) {
		const S = { codes: {}, parties: { warehouses: {}, organisations: {} }, ctx: {} };

		function call(method, args, freeze_message) {
			return new Promise((resolve, reject) => {
				frappe.call({
					method: method.includes(".") ? method : api_prefix + method,
					args: args || {},
					freeze: !!freeze_message,
					freeze_message,
					callback: r => resolve(r.message),
					error: e => reject(e),
				});
			});
		}
		const code = (group, c) => {
			if (c == null || c === "") return "";
			const name = (S.codes[group] || {})[c];
			return name ? `[${esc(c)}] ${esc(name)}` : `[${esc(c)}]`;
		};
		const wh = (c, name) => {
			if (!c) return "";
			const n = name || S.parties.warehouses[c];
			return n ? `[${esc(c)}] ${esc(n)}` : `[${esc(c)}]`;
		};
		const pair = (c, n) => c ? (n ? `[${esc(c)}] ${esc(n)}` : `[${esc(c)}]`) : esc(n || "");
		function write_btn(label, cls, id, extra = "") {
			const disabled = S.ctx.write_enabled ? "" : `disabled title="${esc(__("Enable write operations in TANeSW Settings"))}"`;
			return `<button class="btn btn-sm ${cls}" id="${id}" ${disabled} ${extra}>${esc(__(label))}</button>`;
		}
		function date_range(start_f, end_f, v, buttons = ["-1M", "-1W", "T", "+1W"]) {
			const lbl = { "-6M": "-6M", "-3M": "-3M", "-1M": "-1M", "-1W": "-1W", T: __("Today"), "+1W": "+1W" };
			return `<input type="date" class="form-control ji-date" data-f="${start_f}" value="${esc(v[start_f])}">
				<span class="ji-dash">~</span>
				<input type="date" class="form-control ji-date" data-f="${end_f}" value="${esc(v[end_f])}">
				${buttons.map(b => `<button class="btn btn-default btn-xs ji-range-btn" data-range="${b}" data-s="${start_f}" data-e="${end_f}">${esc(lbl[b])}</button>`).join("")}`;
		}
		function bind_range($el) {
			$el.on("click", ".ji-range-btn", function (e) {
				e.preventDefault();
				const t = today();
				const map = { "-6M": [add_months(t, -6), t], "-3M": [add_months(t, -3), t], "-1M": [add_months(t, -1), t],
					"-1W": [add_days(t, -7), t], T: [t, t], "+1W": [t, add_days(t, 7)] };
				const [a, b] = map[$(this).attr("data-range")];
				$el.find(`[data-f="${$(this).attr("data-s")}"]`).val(a);
				$el.find(`[data-f="${$(this).attr("data-e")}"]`).val(b);
			});
		}
		function read_form($el) {
			const out = {};
			$el.find("[data-f]").each(function () {
				const $i = $(this);
				const f = $i.attr("data-f");
				if ($i.is(":radio")) { if ($i.is(":checked")) out[f] = $i.val(); return; }
				if ($i.is(":checkbox")) { (out[f] = out[f] || []); if ($i.is(":checked")) out[f].push($i.val()); return; }
				out[f] = ($i.val() || "").trim();
			});
			return out;
		}
		function checks(field, options, selected) {
			const sel = new Set(selected || Object.keys(options));
			return `<div class="ji-checks">
				<label><input type="checkbox" class="ji-check-all" data-for="${field}" ${sel.size === Object.keys(options).length ? "checked" : ""}> ${esc(__("All"))}</label>
				${Object.entries(options).map(([k, v]) => `<label><input type="checkbox" data-f="${field}" value="${esc(k)}" ${sel.has(k) ? "checked" : ""}> ${esc(v)}</label>`).join("")}
			</div>`;
		}
		function bind_checks($el) {
			$el.on("change", ".ji-check-all", function () {
				$el.find(`[data-f="${$(this).attr("data-for")}"]`).prop("checked", this.checked);
			});
		}
		function loading($host, cols) {
			$host.html(`<div class="ji-table-wrap"><table class="ji-table"><tbody><tr><td class="ji-empty" colspan="${cols || 1}">
				<span class="spinner-border spinner-border-sm"></span> ${esc(__("Loading from TANeSW..."))}</td></tr></tbody></table></div>`);
		}
		// cfg: {columns:[{label, cls, render(row,i)}], rows, meta, size, onPage, onSize, title, index, select, row_cls, bind, toolbar}
		function grid($host, cfg) {
			const meta = cfg.meta || { number: 0, totalPages: 1, totalElements: (cfg.rows || []).length };
			const rows = cfg.rows || [];
			const start = (meta.number || 0) * (cfg.size || 10);
			const sel = cfg.select;
			const head = (sel ? `<th><input type="checkbox" class="ji-sel-all"></th>` : "")
				+ (cfg.index !== false ? "<th></th>" : "")
				+ cfg.columns.map(c => `<th>${esc(__(c.label))}</th>`).join("");
			const ncol = cfg.columns.length + (cfg.index !== false ? 1 : 0) + (sel ? 1 : 0);
			const body = rows.length ? rows.map((r, i) => `<tr class="${cfg.row_cls ? cfg.row_cls(r) : ""}">
				${sel ? `<td>${(typeof sel === "function" ? sel(r) : true) ? `<input type="checkbox" class="ji-sel" data-i="${i}">` : ""}</td>` : ""}
				${cfg.index !== false ? `<td class="idx">${cfg.index === "desc" ? rows.length - i : start + i + 1}</td>` : ""}
				${cfg.columns.map(c => `<td class="${c.cls || ""}">${c.render(r, i) ?? ""}</td>`).join("")}
			</tr>`).join("") : `<tr><td class="ji-empty" colspan="${ncol}">${esc(__("No data found."))}</td></tr>`;
			let pager = "";
			if (cfg.onPage) {
				const total_pages = Math.max(1, meta.totalPages || 1);
				const cur = meta.number || 0;
				const first = Math.max(0, Math.min(cur - 4, total_pages - 10));
				const last = Math.min(total_pages, first + 10);
				const nums = [];
				for (let p = first; p < last; p++) nums.push(`<button class="btn btn-xs ${p === cur ? "btn-primary" : "btn-default"}" data-page="${p}">${p + 1}</button>`);
				pager = `<div class="ji-pager"><div class="left">
						<span>${esc(__("Page"))} : ${rows.length ? cur + 1 : 0} / ${rows.length ? total_pages : 0}</span>
						<select class="form-control ji-size">${SIZES.map(s => `<option ${s === cfg.size ? "selected" : ""}>${s}</option>`).join("")}</select>
						<span>${esc(__("Total"))} : ${meta.totalElements || 0}</span></div>
					<div class="pages">
						<button class="btn btn-xs btn-default" data-page="${Math.max(0, cur - 1)}" ${cur === 0 ? "disabled" : ""}>&lsaquo;</button>
						${nums.join("")}
						<button class="btn btn-xs btn-default" data-page="${Math.min(total_pages - 1, cur + 1)}" ${cur >= total_pages - 1 ? "disabled" : ""}>&rsaquo;</button>
					</div></div>`;
			}
			$host.html(`${cfg.title ? `<div class="ji-card-title">${esc(__(cfg.title))}</div>` : ""}${cfg.toolbar || ""}
				<div class="ji-table-wrap"><table class="ji-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${pager}`);
			if (cfg.onPage) {
				$host.find(".pages [data-page]").on("click", function () { cfg.onPage(Number($(this).attr("data-page"))); });
				$host.find(".ji-size").on("change", function () { cfg.onSize(Number($(this).val())); });
			}
			$host.find(".ji-sel-all").on("change", function () { $host.find(".ji-sel").prop("checked", this.checked); });
			$host.selected = () => $host.find(".ji-sel:checked").map(function () { return rows[Number($(this).attr("data-i"))]; }).get();
			if (cfg.bind) cfg.bind($host, rows);
			return $host;
		}
		function modal(title, html, size = "large") {
			const d = new frappe.ui.Dialog({ title: __(title), size });
			d.$body.html(`<div class="ji-modal">${html}</div>`);
			d.show();
			return d;
		}
		function form_grid(pairs) {
			// pairs: [[label, html, {wide, req}]...]
			return `<div class="ji-form">${pairs.filter(Boolean).map(([l, v, o = {}]) =>
				`<div class="ji-l">${String(l).startsWith("<") ? l : esc(__(l))}${o.req ? '<span class="req">*</span>' : ""}</div><div class="ji-v ${o.wide ? "wide" : ""}">${v ?? ""}</div>`).join("")}</div>`;
		}
		function b64_blob(res) {
			const bin = atob(res.content);
			const buf = new Uint8Array(bin.length);
			for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
			return new Blob([buf], res.mime ? { type: res.mime } : undefined);
		}
		function download_b64(res) {
			if (!res || !res.content) return;
			const a = document.createElement("a");
			a.href = URL.createObjectURL(b64_blob(res));
			a.download = res.filename || "download.xlsx";
			document.body.appendChild(a); a.click(); a.remove();
		}
		// PDF viewer like the portal's [CGMPDF] popup: preview, Print and Download.
		function show_pdf(res, title) {
			if (!res || !res.content) return;
			const url = URL.createObjectURL(b64_blob({ ...res, mime: "application/pdf" }));
			const d = new frappe.ui.Dialog({ title: title || res.filename || __("Document"), size: "extra-large" });
			d.$body.html(`<div class="ji-modal"><div class="ji-actions" style="margin:0 0 8px"><span class="ji-muted">${esc(res.filename || "")}</span>
				<div class="right"><button class="btn btn-sm btn-default ji-pdf-dl">${esc(__("Download"))}</button>
				<button class="btn btn-sm btn-primary ji-pdf-print">${esc(__("Print"))}</button></div></div>
				<iframe class="ji-pdf" src="${url}" style="width:100%;height:70vh;border:1px solid var(--border-color);background:#fff"></iframe></div>`);
			d.$body.find(".ji-pdf-dl").on("click", () => {
				const a = document.createElement("a"); a.href = url; a.download = res.filename || "document.pdf";
				document.body.appendChild(a); a.click(); a.remove();
			});
			d.$body.find(".ji-pdf-print").on("click", () => {
				const f = d.$body.find(".ji-pdf")[0];
				try { f.contentWindow.focus(); f.contentWindow.print(); } catch (e) { window.open(url, "_blank"); }
			});
			d.onhide = () => setTimeout(() => URL.revokeObjectURL(url), 60000);
			d.show();
			return d;
		}
		function export_csv(name, columns, rows) {
			const strip = h => $("<div>").html(h).text().replace(/\s+/g, " ").trim();
			const headers = columns.map(c => __(c.label));
			const data = rows.map((r, i) => columns.map(c => strip(c.render(r, i) ?? "")));
			// Real .xlsx like the portal's Excel Download; CSV only if the server export is unavailable.
			call("tanesw_integration.cargo.export_xlsx", { title: name, headers, rows: data }, __("Preparing Excel..."))
				.then(download_b64)
				.catch(() => {
					const lines = [headers.map(h => `"${h}"`).join(",")].concat(data.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")));
					const a = document.createElement("a");
					a.href = URL.createObjectURL(new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv" }));
					a.download = `${name}.csv`;
					document.body.appendChild(a); a.click(); a.remove();
				});
		}
		return { S, call, code, wh, pair, write_btn, date_range, bind_range, read_form, checks, bind_checks,
			loading, grid, modal, form_grid, download_b64, show_pdf, export_csv };
	}

	window.tanesw_ui = { make, esc, today, add_days, add_months, parse_dt, iso_date, fmt_date, fmt_dt, fmt_num, SIZES };
})();
