// One navigation for every TANeSW screen (window.tanesw_nav).
// Used by the Cargo Management and Joint Inspection pages so both show the same menu, status bar
// and settings entry. Each item is one of:
//   { page, screen, label }  -> /app/<page>/<screen>
//   { route: [...], label }  -> any desk route (DocType lists, Settings, legacy pages)
//   { action, label }        -> a function in ACTIONS
(() => {
	if (window.tanesw_nav) return;
	const esc = v => frappe.utils.escape_html(v == null ? "" : String(v));
	const CARGO = "tanesw-cargo", JI = "tanesw-joint-inspection";
	const c = (screen, label) => ({ page: CARGO, screen, label });
	const j = (screen, label) => ({ page: JI, screen, label });
	const dt = (doctype, label) => ({ route: ["List", doctype], label });

	const NAV = [
		{ id: "cargo", label: "Cargo Management", groups: [
			{ label: "Manifest", items: [c("cgme0101025q", "Manifest Information")] },
			{ label: "ICD Transfer", items: [
				c("cgme0301001q", "Expected ICD Transfers"), c("cgme0301002q", "Declaration List"),
				c("cgme0301011q", "Amendment List"), c("cgme0301021q", "Cancellation List")] },
			{ label: "Simple Transfer", items: [
				c("cgme0302001q", "Declaration List"), c("cgme0302011q", "Amendment List"),
				c("cgme0302021q", "Cancellation List")] },
			{ label: "Warehouse In/Out", items: [c("cgme0401001q", "Expected Carry-In List"), c("cgme0401008q", "Carry-Out Approval List")] },
			{ label: "Stripping", items: [
				c("cgme0406001q", "Schedule List"), c("cgme0406002q", "Result Report List"),
				c("cgme0406008q", "Amendment List"), c("cgme0406012q", "Cancellation List")] },
			{ label: "Tracking", items: [c("cgme0910001q", "Cargo Tracking List")] },
		] },
		{ id: "ji", label: "Joint Inspection", groups: [
			{ label: null, items: [
				j("eswe0105005q", "Inspection Target List"), j("eswe0105002q", "Inspection Booking List"),
				j("eswe0105007q", "Inspection Result Search")] },
		] },
		{ id: "reports", label: "Reports", groups: [
			{ label: null, items: [
				{ route: ["query-report", "TANeSW Container Allocation"], label: "Container Allocation" },
				{ route: ["query-report", "TANeSW Container Dwell"], label: "Container Dwell" },
				dt("TANeSW Container", "Tracked Containers")] },
		] },
		{ id: "records", label: "Records in ERPNext", groups: [
			{ label: null, items: [
				dt("TANeSW Declaration", "Customs Declarations"), dt("TANeSW Transfer Allocation", "Transfer Allocations"),
				dt("TANeSW Vessel Allocation", "Vessel Allocations"),
				dt("TANeSW Carry In", "Carry-In Records"), dt("TANeSW Carry Out", "Carry-Out Records"),
				dt("TANeSW Stripping Report", "Stripping Reports"), dt("TANeSW Inspection Booking", "Inspection Bookings"),
				dt("TANeSW Inspection Agency", "Inspection Agencies")] },
		] },
		{ id: "settings", label: "Settings", groups: [
			{ label: null, items: [
				{ route: ["Form", "TANeSW Settings"], label: "TANeSW Settings" },
				{ ...dt("TANeSW User Account", "TANeSW User Accounts"), admin: true },
				{ action: "test", label: "Test Connection" }] },
		] },
		{ id: "tools", label: "Tools", groups: [
			{ label: null, items: [{ route: ["tanesw-operations"], label: "Operations Hub (legacy)", admin: true }] },
		] },
	];

	if (!(frappe.user && frappe.user.has_role && frappe.user.has_role("System Manager"))) {
		NAV.forEach(sec => sec.groups.forEach(g => { g.items = g.items.filter(it => !it.admin); }));
		for (let i = NAV.length - 1; i >= 0; i--) if (!NAV[i].groups.some(g => g.items.length)) NAV.splice(i, 1);
	}

	const LS_KEY = "tanesw_nav_v1";
	const load_state = () => { try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch (e) { return {}; } };
	const save_state = s => { try { localStorage.setItem(LS_KEY, JSON.stringify(s)); } catch (e) { /* private mode */ } };

	const ACTIONS = {
		test: () => frappe.call({ method: "tanesw_integration.api.test_connection", freeze: true, freeze_message: __("Connecting to TANeSW...") })
			.then(r => frappe.show_alert({ message: r.message && r.message.status === "ok" ? __("Connected to TANeSW") : __("TANeSW did not answer"), indicator: r.message && r.message.status === "ok" ? "green" : "red" })),
	};

	const key_of = it => it.page ? `${it.page}/${it.screen}` : it.route ? it.route.join("/") : `action/${it.action}`;
	const all_items = () => NAV.flatMap(s => s.groups.flatMap(g => g.items.map(it => ({ ...it, section: s.id, group: g.label }))));

	// Build the sidebar into $nav. Returns { set_active(page, screen) }.
	const render_item = (it, s, g) => `<a class="tn-item" href="${esc(href(it))}" data-key="${esc(key_of(it))}" data-find="${esc([__(s.label), g && g.label ? __(g.label) : "", __(it.label), it.screen || ""].join(" ").toLowerCase())}" title="${esc([g && g.label ? __(g.label) : __(s.label), __(it.label)].join(" › "))}">${esc(__(it.label))}</a>`;

	function mount($nav) {
		const state = load_state();
		const open_sec = id => state[id] !== undefined ? state[id] : (id === "cargo" || id === "ji");
		const grp_id = (sec_id, label) => `grp:${sec_id}:${label}`;
		const open_grp = (sec_id, label) => state[grp_id(sec_id, label)] !== undefined ? state[grp_id(sec_id, label)] : false;

		$nav.addClass("tn-nav").html(`
			<div class="tn-search"><input type="search" class="form-control" placeholder="${esc(__("Find a screen…"))}" aria-label="${esc(__("Find a screen"))}"></div>
			<div class="tn-sections">${NAV.map(s => `
				<section class="tn-sec ${open_sec(s.id) ? "open" : ""}" data-sec="${s.id}">
					<button type="button" class="tn-sec-head" aria-expanded="${open_sec(s.id)}">
						<span class="tn-sec-label">${esc(__(s.label))}</span><span class="tn-caret" aria-hidden="true">›</span></button>
					<div class="tn-sec-body">${s.groups.map(g => {
						if (!g.label) {
							return g.items.map(it => render_item(it, s, g)).join("");
						}
						const gid = grp_id(s.id, g.label);
						const g_is_open = open_grp(s.id, g.label);
						return `
						<div class="tn-sub-sec ${g_is_open ? "open" : ""}" data-grp="${esc(gid)}">
							<button type="button" class="tn-grp-head" aria-expanded="${g_is_open}">
								<span class="tn-grp-label">${esc(__(g.label))}</span>
								<span class="tn-caret" aria-hidden="true">›</span>
							</button>
							<div class="tn-grp-body">
								${g.items.map(it => render_item(it, s, g)).join("")}
							</div>
						</div>`;
					}).join("")}
					</div>
				</section>`).join("")}
				<div class="tn-empty ji-muted">${esc(__("No screen matches."))}</div>
			</div>`);
		// small screens: the menu becomes a drawer opened from a "Menu" button
		const $tog = $(`<button type="button" class="btn btn-default btn-sm tn-toggle">${esc(__("Menu"))}</button>`).insertBefore($nav);
		$tog.on("click", () => $nav.toggleClass("tn-drawer-open"));
		$nav.on("click", "a.tn-item", () => $nav.removeClass("tn-drawer-open"));
		const items = all_items();
		const by_key = Object.fromEntries(items.map(it => [key_of(it), it]));

		// Section accordion toggle
		$nav.on("click", ".tn-sec-head", function () {
			const $s = $(this).closest(".tn-sec").toggleClass("open");
			$(this).attr("aria-expanded", $s.hasClass("open"));
			state[$s.attr("data-sec")] = $s.hasClass("open"); save_state(state);
		});

		// Sub-group accordion toggle
		$nav.on("click", ".tn-grp-head", function (e) {
			e.stopPropagation();
			const $g = $(this).closest(".tn-sub-sec").toggleClass("open");
			$(this).attr("aria-expanded", $g.hasClass("open"));
			state[$g.attr("data-grp")] = $g.hasClass("open"); save_state(state);
		});

		$nav.on("click", "a.tn-item", function (e) {
			if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return;
			e.preventDefault();
			const it = by_key[$(this).attr("data-key")];
			if (!it) return;
			if (it.action) return ACTIONS[it.action] && ACTIONS[it.action]();
			it.page ? frappe.set_route(it.page, it.screen) : frappe.set_route(...it.route);
		});

		// Find a screen: filters across all sections & groups, opens matching ones; Enter opens the first hit.
		const $q = $nav.find(".tn-search input");
		$q.on("input", function () {
			const q = this.value.trim().toLowerCase();
			$nav.toggleClass("filtering", !!q);
			let hits = 0;
			$nav.find(".tn-sec").each(function () {
				let secHits = 0;
				$(this).find(".tn-sub-sec").each(function () {
					let grpHits = 0;
					$(this).find("a.tn-item").each(function () {
						const hay = $(this).attr("data-find") || "";
						const ok = !q || q.split(/\s+/).every(w => hay.includes(w));
						$(this).toggleClass("tn-hide", !ok);
						if (ok) grpHits++;
					});
					$(this).toggleClass("tn-hide", !!q && !grpHits).toggleClass("tn-force-open", !!q && grpHits > 0);
					secHits += grpHits;
				});
				$(this).find("> .tn-sec-body > a.tn-item").each(function () {
					const hay = $(this).attr("data-find") || "";
					const ok = !q || q.split(/\s+/).every(w => hay.includes(w));
					$(this).toggleClass("tn-hide", !ok);
					if (ok) secHits++;
				});
				$(this).toggleClass("tn-hide", !!q && !secHits).toggleClass("tn-force-open", !!q && secHits > 0);
				hits += secHits;
			});
			$nav.find(".tn-empty").toggle(!!q && !hits);
		}).on("keydown", function (e) {
			if (e.key === "Enter") { const $f = $nav.find("a.tn-item:not(.tn-hide)").first(); if ($f.length) { $f.trigger("click"); this.value = ""; $(this).trigger("input"); } }
			if (e.key === "Escape") { this.value = ""; $(this).trigger("input"); }
		});

		return {
			set_active(page, screen) {
				const k = `${page}/${screen}`;
				$nav.find("a.tn-item").removeClass("active").removeAttr("aria-current");
				const $a = $nav.find(`a.tn-item[data-key="${k}"]`).addClass("active").attr("aria-current", "page");
				const $sec = $a.closest(".tn-sec");
				if ($a.length && !$sec.hasClass("open")) { $sec.addClass("open"); state[$sec.attr("data-sec")] = true; save_state(state); }
				const $sub = $a.closest(".tn-sub-sec");
				if ($sub.length && !$sub.hasClass("open")) {
					$sub.addClass("open");
					$sub.find(".tn-grp-head").attr("aria-expanded", "true");
					state[$sub.attr("data-grp")] = true;
					save_state(state);
				}
			},
		};
	}




	function href(it) {
		if (it.page) return `/app/${it.page}/${it.screen}`;
		if (it.route) {
			const [kind, name] = it.route;
			if (kind === "List") return `/app/${frappe.router.slug(name)}`;
			if (kind === "Form") return `/app/${frappe.router.slug(name)}`;
			return `/app/${it.route.map(encodeURIComponent).join("/")}`;
		}
		return "#";
	}

	// Status strip above the screen: who/where we are on TANeSW, whether writes are on, quick settings.
	function status_bar(ctx) {
		ctx = ctx || {};
		const who = [ctx.warehouse_code, ctx.company_name].filter(Boolean).map(esc).join(" · ");
		return `<div class="tn-status">
			<span class="tn-dot ${who ? "ok" : "bad"}"></span>
			<span>${who ? `${esc(__("TANeSW"))}: ${who}` : esc(__("TANeSW login not set up"))}</span>
			${ctx.test_mode ? `<span class="tn-pill" style="background:#f59e0b;color:#fff;font-weight:700" title="${esc(__("Nothing is sent to TANeSW. Carry-In Submit only creates the ERP records; other writes are refused."))}">${esc(__("TEST MODE: nothing sent to TANeSW"))}</span>`
			: `<span class="tn-pill ${ctx.write_enabled ? "on" : "off"}" title="${esc(__("Save / Submit / Delete buttons send changes to TRA only when this is ON"))}">
				${ctx.write_enabled ? esc(__("Write ON")) : esc(__("Read-only"))}</span>`}
			<span class="tn-spacer"></span>
			<a class="tn-link" href="/app/tanesw-settings">${esc(__("Settings"))}</a>
		</div>`;
	}

	window.tanesw_nav = { NAV, mount, status_bar, all_items };
})();
