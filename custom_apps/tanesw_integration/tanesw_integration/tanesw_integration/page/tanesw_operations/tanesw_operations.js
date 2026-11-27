// TANeSW Operations Desk Page
frappe.pages["tanesw-operations"].on_page_load = function (wrapper) {
	$(wrapper).empty();
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("TANeSW Operations"),
		single_column: true,
	});
	wrapper.tanesw_page = page;

	page.set_secondary_action(__("Test Connection"), () => test_connection(), "refresh");
	// Legacy hub: the same screens now live in Cargo Management / Joint Inspection (one shared menu).
	page.set_primary_action(__("Go to Cargo Management"), () => frappe.set_route("tanesw-cargo"));
	$(`<div class="alert alert-warning small mb-3">${__("Operations Hub is the older version of these screens. Use <b>Cargo Management</b> and <b>Joint Inspection</b> for day-to-day work — they match the TANeSW portal.")}</div>`).appendTo(page.body);

	const template = `
		<div class="tanesw-operations-page">
			<div class="tanesw-top-bar d-flex justify-content-between align-items-center mb-3">
				<div class="tanesw-conn-status text-muted small d-flex align-items-center">
					<span class="indicator-pill gray" id="tanesw-conn-pill">Checking Connection</span>
					<span id="tanesw-conn-text" class="ml-2">TANeSW Single Window Gateway</span>
				</div>
				<div>
					<button class="btn btn-default btn-xs" id="btn-tanesw-test-conn">Test Connection</button>
				</div>
			</div>
			<div class="tanesw-tabs-wrapper mb-3">
				<ul class="nav nav-tabs tanesw-nav-tabs" role="tablist">
					<li class="nav-item"><a class="nav-link active" data-tab="manifest" role="tab">Manifest Management</a></li>
					<li class="nav-item"><a class="nav-link" data-tab="transfers" role="tab">ICD Transfers &rarr;</a></li>
					<li class="nav-item"><a class="nav-link" data-tab="tracking" role="tab">Cargo Tracking</a></li>
					<li class="nav-item"><a class="nav-link" data-tab="carry_in" role="tab">Carry-In</a></li>
					<li class="nav-item"><a class="nav-link" data-tab="carry_out" role="tab">Carry-Out</a></li>
					<li class="nav-item"><a class="nav-link" data-tab="bookings" role="tab">Bookings</a></li>
					<li class="nav-item"><a class="nav-link" data-tab="inspections" role="tab">Inspections</a></li>
				</ul>
			</div>
			<div class="tanesw-tab-content" id="tanesw-tab-content"></div>
		</div>
	`;

	$(template).appendTo(page.body);

	const $content = page.body.find("#tanesw-tab-content");
	const $tabs = page.body.find(".tanesw-nav-tabs");

	$tabs.on("click", ".nav-link", function (e) {
		e.preventDefault();
		$tabs.find(".nav-link").removeClass("active");
		$(this).addClass("active");
		const tab_name = $(this).attr("data-tab");
		render_tab(tab_name, $content);
	});

	page.body.find("#btn-tanesw-test-conn").on("click", function () {
		test_connection();
	});

	test_connection();
	render_tab("manifest", $content);
};

// --- Gateway Connection Check ---
function test_connection() {
	const $pill = $("#tanesw-conn-pill");
	const $text = $("#tanesw-conn-text");
	$pill.attr("class", "indicator-pill orange").text(__("Connecting..."));

	frappe.call({
		method: "tanesw_integration.api.test_connection",
		callback(r) {
			if (r.message && r.message.status === "ok") {
				$pill.attr("class", "indicator-pill green").text(__("Connected"));
				$text.text(__("TANeSW Single Window Gateway (Token verified)"));
			} else {
				$pill.attr("class", "indicator-pill red").text(__("Error"));
				$text.text(__("Failed to authenticate with TANeSW"));
			}
		},
		error() {
			$pill.attr("class", "indicator-pill red").text(__("Offline"));
			$text.text(__("Connection check failed"));
		}
	});
}

// --- Tab Router ---
function render_tab(name, $c) {
	$c.empty();
	const handlers = {
		manifest: tab_manifest,
		transfers: tab_transfers,
		tracking: tab_tracking,
		carry_in: tab_carry_in,
		carry_out: tab_carry_out,
		bookings: tab_bookings,
		inspections: tab_inspections,
	};
	if (handlers[name]) {
		handlers[name]($c);
	}
}

// --- Helper Functions ---
function today() {
	return frappe.datetime.get_today();
}

function days_ago(n) {
	return frappe.datetime.add_days(today(), -n);
}

function status_indicator(code) {
	if (!code) return "";
	const s = String(code).trim().toUpperCase();
	const map = {
		"A": ["Approved", "green"],
		"B": ["Booked", "blue"],
		"C": ["Completed", "green"],
		"D": ["Draft", "gray"],
		"I": ["In Progress", "orange"],
		"P": ["Pending", "orange"],
		"R": ["Rejected", "red"],
		"X": ["Cancelled", "red"],
		"Y": ["Passed", "green"],
		"N": ["Failed", "red"],
		"SUCCESS": ["Success", "green"],
		"APPROVED": ["Approved", "green"],
		"REJECTED": ["Rejected", "red"],
		"PENDING": ["Pending", "orange"],
		"IN PROGRESS": ["In Progress", "orange"],
		"COMPLETED": ["Completed", "green"],
		"NOT REPORT": ["Not Reported", "orange"],
		"REPORT": ["Reported", "green"],
	};
	const item = map[s] || [code, "gray"];
	return `<span class="indicator-pill ${item[1]}">${frappe.utils.escape_html(item[0])}</span>`;
}

function extract_list(r) {
	if (!r) return [];
	const msg = r.message !== undefined ? r.message : r;
	if (Array.isArray(msg)) return msg;
	if (!msg || typeof msg !== "object") return [];
	if (Array.isArray(msg.content)) return msg.content;
	if (msg.icdTrsfDclrLstData && Array.isArray(msg.icdTrsfDclrLstData.content)) return msg.icdTrsfDclrLstData.content;
	if (msg.wrhsCriList && Array.isArray(msg.wrhsCriList.content)) return msg.wrhsCriList.content;
	if (msg.wrhsCroList && Array.isArray(msg.wrhsCroList.content)) return msg.wrhsCroList.content;
	if (msg.jntInscBkngList && Array.isArray(msg.jntInscBkngList.content)) return msg.jntInscBkngList.content;
	if (msg.jntInscRsltList && Array.isArray(msg.jntInscRsltList.content)) return msg.jntInscRsltList.content;
	if (msg.impMnfsBlLst && Array.isArray(msg.impMnfsBlLst.content)) return msg.impMnfsBlLst.content;
	return [];
}

function make_filter_bar(fields) {
	const $card = $(`<div class="tanesw-filter-card"><div class="tanesw-filter-bar"></div></div>`);
	const $bar = $card.find(".tanesw-filter-bar");
	const controls = {};
	fields.forEach(f => {
		const $wrap = $(`<div class="tanesw-field-wrap"></div>`);
		const ctrl = frappe.ui.form.make_control({
			df: {
				fieldtype: f.fieldtype || "Data",
				label: f.label,
				fieldname: f.fieldname,
				placeholder: f.placeholder || "",
				options: f.options || "",
				default: f.default || "",
			},
			parent: $wrap,
			render_input: true,
		});
		if (f.default !== undefined) ctrl.set_value(f.default);
		controls[f.fieldname] = ctrl;
		$bar.append($wrap);
	});
	return { $el: $card, $bar, controls };
}

function add_bar_button($bar, label, btn_class, callback) {
	const $btn = $(`<button class="btn ${btn_class || 'btn-primary'} btn-sm ml-2" style="height: 36px; align-self: flex-end;">${label}</button>`);
	$btn.on("click", callback);
	$bar.append($(`<div style="flex: 0 0 auto; align-self: flex-end;"></div>`).append($btn));
	return $btn;
}

function make_table_panel(title, columns) {
	const $wrap = $(`<div class="tanesw-card"></div>`);
	const $header = $(`<div class="tanesw-card-header">
		<h5 class="tanesw-card-title">${title}</h5>
		<span class="count text-muted small"></span>
	</div>`);
	const ths = columns.map(c => `<th>${c.label || c}</th>`).join("");
	const $table = $(`<div style="overflow-x: auto;">
		<table class="tanesw-table">
			<thead><tr>${ths}</tr></thead>
			<tbody></tbody>
		</table>
	</div>`);
	$wrap.append($header).append($table);

	return {
		$el: $wrap,
		$tbody: $wrap.find("tbody"),
		fill(rows, keys, render_cell) {
			const $tbody = $wrap.find("tbody").empty();
			$header.find(".count").text(rows && rows.length ? `${rows.length} ${rows.length === 1 ? 'record' : 'records'}` : "");
			if (!rows || !rows.length) {
				$tbody.append(`<tr><td colspan="${columns.length}">
					<div class="tanesw-empty">
						<div class="message">No records found</div>
						<div class="hint">Try adjusting your search criteria or date filters.</div>
					</div>
				</td></tr>`);
				return;
			}
			rows.forEach((r, idx) => {
				const tds = keys.map((k, col_idx) => {
					if (render_cell) {
						const custom = render_cell(r, k, col_idx, idx);
						if (custom !== undefined) return `<td>${custom}</td>`;
					}
					let val = r[k] != null ? r[k] : "";
					if (k === "stsCd" || k === "stsNm" || k === "rsltNm" || k === "rptStatNm") {
						val = status_indicator(val);
					} else {
						val = frappe.utils.escape_html(String(val));
					}
					return `<td>${val}</td>`;
				}).join("");
				$tbody.append(`<tr>${tds}</tr>`);
			});
		},
		loading() {
			$wrap.find("tbody").html(`<tr><td colspan="${columns.length}" style="text-align: center; padding: 30px;">
				<div class="spinner-border spinner-border-sm text-secondary" role="status"></div>
				<span class="text-muted ml-2 small">Loading from TANeSW...</span>
			</td></tr>`);
			$header.find(".count").text("");
		}
	};
}

// ==========================================
// 1. Tab: Manifest Lookup
// ==========================================
// ==========================================
// 1. Tab: Manifest Management & Detail (UI-CGM-0101-002S)
// ==========================================
// ==========================================
// 1. Tab: Manifest Management & Detail (UI-CGME-0101-025Q)
// ==========================================
function tab_manifest($c) {
	const defaultFrom = today();
	const defaultTo = frappe.datetime.add_days(today(), 7);
	const { $el: $filter, $bar, controls } = make_filter_bar([
		{ label: "Date of Arrival From", fieldname: "dt_from", fieldtype: "Date", default: defaultFrom },
		{ label: "Date of Arrival To", fieldname: "dt_to", fieldtype: "Date", default: defaultTo },
		{ label: "MRN (optional)", fieldname: "mrn", placeholder: "Manifest Reference Number" },
		{ label: "Our-cargo source", fieldname: "source", fieldtype: "Select",
			options: "all\ndeclared\nscan", default: "all" },
	]);

	let ourOnly = true;
	let facilityCode = "";

	const $quick = $('<div class="d-flex align-items-end" style="gap:4px"></div>');
	[
		["-1M", () => controls.dt_from.set_value(frappe.datetime.add_days(controls.dt_to.get_value() || defaultTo, -30))],
		["-1W", () => controls.dt_from.set_value(frappe.datetime.add_days(controls.dt_to.get_value() || defaultTo, -7))],
		["Today", () => { controls.dt_from.set_value(defaultFrom); controls.dt_to.set_value(defaultFrom); }],
		["+1W", () => { controls.dt_from.set_value(defaultFrom); controls.dt_to.set_value(defaultTo); }],
	].forEach(([label, action]) => $('<button class="btn btn-default btn-sm">').text(label).on('click', action).appendTo($quick));
	$bar.append($quick);

	const $ourOnlyBtn = add_bar_button($bar, __("Our Cargo Only"), "btn-primary", () => {
		ourOnly = !ourOnly;
		paint_our_only();
		load_manifest_list(0);
	});
	function paint_our_only() {
		$ourOnlyBtn
			.toggleClass("btn-primary", ourOnly)
			.toggleClass("btn-default", !ourOnly)
			.text(ourOnly ? __("Our Cargo Only: ON") : __("Our Cargo Only: OFF"));
	}

	add_bar_button($bar, __("Reset"), "btn-warning", () => {
		controls.dt_from.set_value(defaultFrom);
		controls.dt_to.set_value(defaultTo);
		controls.mrn.set_value("");
		load_manifest_list(0);
	});
	add_bar_button($bar, __("Search"), "btn-primary", () => load_manifest_list(0));

	const $manifestContainer = $('<div id="tanesw-manifest-display" class="mt-3"></div>');
	let manifestListPage = 0;
	let listPage = 0;
	let scanPage = 0;
	let scannedMatches = [];
	let scannedUpto = 0;
	let totalManifests = 0;
	let hasMoreScan = false;
	$c.append('<div class="tanesw-breadcrumb mb-2">Home &gt; Cargo Mgmt. &gt; Manifest Management &gt; Sea Import Manifest &gt; Manifest Information</div>')
		.append('<h5 class="mb-3">Manifest Information (UI-CGME-0101-025Q)</h5>')
		.append($filter).append($manifestContainer);

	paint_our_only();

	function current_source() {
		if (!ourOnly) return "plain";
		return controls.source.get_value() || "all";
	}

	function load_manifest_list(page, options) {
		const reset = !options || options.reset !== false;
		if (reset) { scanPage = 0; scannedMatches = []; scannedUpto = 0; }
		listPage = Number(page || 0);
		manifestListPage = listPage;
		const mode = current_source();

		const loadingText = mode === "scan"
			? __("Scanning 25 manifests' B/Ls for place of delivery {0} — ~30s per chunk...", [facilityCode])
			: mode === "declared"
				? __("Loading manifests from our transfer declarations ({0})...", [facilityCode])
				: mode === "all"
					? __("Walking B/Ls of every manifest arriving in this window for place of delivery {0} — a few seconds...", [facilityCode])
					: __("Loading manifests from TANeSW...");
		$manifestContainer.html(`<div class="text-center p-5 tanesw-card"><div class="spinner-border spinner-border-sm text-secondary"></div><span class="text-muted ml-2 small">${frappe.utils.escape_html(loadingText)}</span></div>`);

		frappe.call({
			method: "tanesw_integration.api.manifest_list",
			args: {
				dt_from: controls.dt_from.get_value() || defaultFrom,
				dt_to: controls.dt_to.get_value() || defaultTo,
				mrn: controls.mrn.get_value(),
				page: mode === "scan" ? 0 : listPage,
				size: 10,
				only_our_facility: ourOnly ? 1 : 0,
				scan_page: mode === "scan" ? scanPage : 0,
				source: mode,
			},
			callback(r) {
				const data = r.message || {};
				if (data.facility_code) facilityCode = data.facility_code;
				if (mode === "scan") {
					scannedMatches = scannedMatches.concat(data.content || []);
					scannedUpto += Number(data.scanned || 0);
					totalManifests = Number(data.total_manifests || scannedUpto);
					hasMoreScan = !!data.has_more;
					render_manifest_list({ mode: "scan" });
				} else {
					render_manifest_list({ mode, content: data.content || [], page: data.page || {} });
				}
			},
			error() { $manifestContainer.html('<div class="text-danger p-4 text-center">Failed to query manifests from TANeSW</div>'); },
		});
	}

	function render_manifest_list(result) {
		const mode = result.mode || "plain";
		const pageSize = 10;
		const rows = mode === "scan"
			? scannedMatches.slice(listPage * pageSize, listPage * pageSize + pageSize)
			: (result.content || []);
		const number = listPage;
		const totalPages = mode === "scan"
			? Math.ceil(scannedMatches.length / pageSize)
			: Number((result.page || {}).totalPages || 0);
		const total = mode === "scan"
			? scannedMatches.length
			: Number((result.page || {}).totalElements || 0);

		const ourHeaders = mode === "declared"
			? '<th>Declarations</th><th>Containers</th><th>Last Status</th>'
			: mode === "all"
				? '<th>B/Ls</th><th>Containers</th><th>Declarations</th><th>Source</th>'
				: '<th>B/Ls</th><th>Containers</th>';
		const ourColspan = mode === "declared" ? 3 : (mode === "all" ? 4 : 2);

		const ourCells = row => {
			if (mode === "all") {
				const badge = row.allocated && row.declared
					? '<span class="indicator-pill green">Allocated + Declared</span>'
					: row.allocated
						? '<span class="indicator-pill blue">Allocated</span>'
						: '<span class="indicator-pill orange">Declared only</span>';
				return `<td><strong>${row.our_bl_count != null ? row.our_bl_count : "-"}</strong></td>
					<td><strong>${row.our_cntr_count != null ? row.our_cntr_count : "-"}</strong></td>
					<td><strong>${row.decl_count != null ? row.decl_count : "-"}</strong></td>
					<td>${badge}</td>`;
			}
			if (mode === "declared") {
				return `<td><strong>${row.decl_count != null ? row.decl_count : "-"}</strong></td>
					<td><strong>${row.our_cntr_count != null ? row.our_cntr_count : "-"}</strong></td>
					<td>${status_indicator(row.last_status)}</td>`;
			}
			return `<td><strong>${row.our_bl_count != null ? row.our_bl_count : "-"}</strong></td>
				<td><strong>${row.our_cntr_count != null ? row.our_cntr_count : "-"}</strong></td>`;
		};

		const body = rows.map((row, i) => `<tr class="manifest-list-row" data-index="${i}" style="cursor:pointer">
			<td>${number * pageSize + i + 1}</td>
			<td><strong>${frappe.utils.escape_html(row.vsslNm || "-")}</strong></td>
			<td>${frappe.utils.escape_html(row.tpaUid || "-")}</td>
			<td>[${frappe.utils.escape_html(row.carrCd || "-")}] ${frappe.utils.escape_html(row.carrNm || "-")}</td>
			<td>${frappe.utils.escape_html((row.actlArvlDt || row.arvlXptdDt || row.last_prcss_dtm || "-").split(" ")[0])}</td>
			<td>${row.mblSCnt || 0}</td><td>${row.mblCCnt || 0}</td><td>${row.hblCnt || 0}</td><td>${row.cntrCnt || 0}</td>
			${ourCells(row)}
		</tr>`).join('');

		let pages = '';
		const first = Math.max(0, Math.min(number - 4, totalPages - 10));
		const last = Math.min(totalPages, first + 10);
		for (let p = first; p < last; p++) pages += `<button class="btn btn-xs ${p === number ? 'btn-primary' : 'btn-default'} manifest-page-btn" data-page="${p}">${p + 1}</button>`;

		let scope;
		if (mode === "scan") {
			const remaining = Math.max(0, totalManifests - scannedUpto);
			scope = `Scanned <strong>${scannedUpto}</strong> of <strong>${totalManifests}</strong> manifests &nbsp;·&nbsp; Matching: <strong>${total}</strong> &nbsp;·&nbsp; Facility ${frappe.utils.escape_html(facilityCode)}`
				+ (hasMoreScan ? ` &nbsp;·&nbsp; <span class="text-warning">${remaining} not scanned yet</span>` : ` &nbsp;·&nbsp; <span class="text-success">window fully scanned</span>`);
		} else if (mode === "all") {
			scope = `Manifests <strong>arriving in this window</strong> that are ours by B/L allocation or declaration: <strong>${total}</strong> of <strong>${result.scanned != null ? result.scanned : total}</strong> arriving &nbsp;·&nbsp; facility ${frappe.utils.escape_html(facilityCode)}`;
		} else if (mode === "declared") {
			scope = `Manifests <strong>arriving in this window</strong> with declared transfers to <strong>${frappe.utils.escape_html(facilityCode)}</strong>: <strong>${total}</strong> &nbsp;·&nbsp; matched on vessel arrival date`;
		} else {
			scope = `Page: ${totalPages ? number + 1 : 0} / ${totalPages} &nbsp; Total: ${total}`;
		}

		const scanMoreBtn = (mode === "scan" && hasMoreScan)
			? `<button class="btn btn-primary btn-sm manifest-scan-more">Scan Next 25</button>`
			: '';

		$manifestContainer.html(`<div class="tanesw-card">
			<div class="table-responsive"><table class="tanesw-table">
				<thead><tr>
					<th rowspan="2">No.</th><th rowspan="2">Vessel Name</th><th rowspan="2">TPA/ZPC UID</th><th rowspan="2">Carrier</th><th rowspan="2">Date of Arrival</th>
					<th colspan="2">Submitted</th><th colspan="2">B/L (M)</th><th rowspan="2">Containers</th>
					<th colspan="${ourColspan}">Our Cargo</th>
				</tr>
				<tr><th>S/A</th><th>F/F</th><th>S</th><th>C</th>${ourHeaders}</tr></thead>
				<tbody>${body || `<tr><td colspan="${9 + ourColspan}" class="tanesw-empty">${mode === "scan" ? "No manifests with our cargo in the scanned chunk" : "No manifests found"}</td></tr>`}</tbody>
			</table></div>
			<div class="d-flex justify-content-between align-items-center p-3 border-top"><span>${scope}</span><div class="d-flex align-items-center" style="gap:8px">${scanMoreBtn}<div class="btn-group btn-group-sm">${pages}</div></div></div>
		</div>`);

		$manifestContainer.find('.manifest-list-row').on('click', function() { open_manifest_detail(rows[Number($(this).data('index'))]); });
		$manifestContainer.find('.manifest-scan-more').on('click', function() {
			$(this).prop('disabled', true).text(__("Scanning..."));
			scanPage += 1;
			load_manifest_list(listPage, { reset: false });
		});
		$manifestContainer.find('.manifest-page-btn').on('click', function() {
			listPage = Number($(this).data('page'));
			manifestListPage = listPage;
			if (mode === "scan") { render_manifest_list({ mode: "scan" }); } else { load_manifest_list(listPage, { reset: false }); }
		});
	}

	function open_manifest_detail(selected) {
		const mrn = selected && selected.mrn;
		if (!mrn) return;
		$manifestContainer.html('<div class="text-center p-5 tanesw-card"><div class="spinner-border spinner-border-sm text-secondary"></div><span class="text-muted ml-2 small">Loading manifest details from TANeSW...</span></div>');
		frappe.call({
			method: "tanesw_integration.api.manifest_detail",
			args: { mrn, page: 0, size: 10, only_our_facility: ourOnly ? 1 : 0 },
			callback(r) { render_manifest_detail(r.message || {}, selected); },
			error() { $manifestContainer.html('<div class="text-danger p-4 text-center">Failed to query manifest from TANeSW</div>'); },
		});
	}

	function render_manifest_detail(data, selected) {
		const info = Object.assign({}, selected || {}, data.manifest || {});
		let detailOurOnly = ourOnly;
		const esc = value => frappe.utils.escape_html(String(value == null || value === "" ? "-" : value));
		const date = value => esc(value ? String(value).split(" ")[0] : "-");
		const country = info.natCd === "KY" ? "[KY] Cayman Islands" : info.natCd;
		const portName = code => code === "INSIK" ? "[INSIK] Sika" : code === "TZDAR" ? "[TZDAR] Dar es Salaam" : code;
		const terminal = info.trmnlCd === "WTTZDL004" ? "[WTTZDL004] KURASINI OIL JETTY 1" : info.trmnlCd;
		const operator = info.trmnlOptrCd === "OTZDL001" ? "[OTZDL001] TPA OPERATOR" : info.trmnlOptrCd;
		if (data.facility_code) facilityCode = data.facility_code;
		const ourBlCount = data.our_bl_count != null ? data.our_bl_count : "-";
		const ourCntrCount = data.our_cntr_count != null ? data.our_cntr_count : "-";

		$manifestContainer.html(`
			<div class="tanesw-breadcrumb mb-2">Home &gt; Cargo Mgmt. &gt; Manifest Management &gt; Sea Import Manifest &gt; Manifest Information</div>
			<div class="d-flex justify-content-between align-items-center mb-3">
				<h5 class="mb-0">Sea Import MRN Details (UI-CGME-0101-026Q)</h5>
				<button class="btn btn-default btn-sm" id="btn-close-manifest">Back to Manifest List</button>
			</div>
			<div class="tanesw-panel mb-3">
				<div class="tanesw-panel-header">Summary</div>
				<div class="tanesw-summary-grid">
					<div class="label">MRN</div><div>${esc(info.mrn)}</div><div class="label">Voyage</div><div>${esc(info.vygNo)}</div>
					<div class="label">Call Sign</div><div>${esc(info.csgn)}</div><div class="label">Nationality of Vessel</div><div>${esc(country)}</div>
					<div class="label">Carrier</div><div>${esc(info.carrNm)}</div><div class="label">Vessel Name</div><div>${esc(info.vsslNm)}</div>
					<div class="label">Port of Departure</div><div>${esc(portName(info.dptrPortCd))}</div><div class="label">Port of Discharge</div><div>${esc(portName(info.dscgPortCd))}</div>
					<div class="label">Date of Submission</div><div>${date(info.sbmtDt)}</div><div class="label">Arrival Date</div><div>${date(info.actlArvlDt || info.arvlXptdDt)}</div>
					<div class="label">Date of Departure</div><div>${date(info.dptrDt)}</div><div class="label">Arrival in ballast</div><div>${esc(info.inblYn)}</div>
					<div class="label">Terminal No.</div><div>${esc(terminal)}</div><div class="label">Terminal Operator</div><div>${esc(operator)}</div>
					<div class="label">Our B/Ls (${esc(facilityCode)})</div><div><strong>${esc(ourBlCount)}</strong></div>
					<div class="label">Our Containers</div><div><strong>${esc(ourCntrCount)}</strong></div>
				</div>
			</div>
			<div class="tanesw-card">
				<div class="tanesw-card-header">
					<h5 class="tanesw-card-title" id="manifest-bl-title">Master B/L List</h5>
					<div class="d-flex align-items-center" style="gap:8px">
						<button class="btn btn-default btn-sm" id="btn-toggle-our-bl"></button>
						<button class="btn btn-default btn-sm" id="manifest-excel-download">Excel Download</button>
					</div>
				</div>
				<div class="table-responsive"><table class="tanesw-table"><thead><tr>
					<th>MSN</th><th>M B/L No</th><th>Consignee</th><th>B/L Type</th><th>Port of Loading</th><th>Delivery Place</th><th>Package</th><th>Weight</th><th>Containers</th><th>Audit Status</th>
				</tr></thead><tbody id="manifest-bl-body"></tbody></table></div>
				<div class="d-flex justify-content-between align-items-center p-3 border-top"><span id="manifest-bl-page-info"></span><div class="btn-group btn-group-sm" id="manifest-bl-pages"></div></div>
			</div>`);

		function paint_toggle() {
			$manifestContainer.find('#btn-toggle-our-bl').text(detailOurOnly ? __("Show All B/Ls") : __("Show Our B/Ls Only"));
			$manifestContainer.find('#manifest-bl-title').text(detailOurOnly ? __("Master B/L List — Our Cargo") : __("Master B/L List — All"));
		}

		function show_page(result) {
			const rows = result.content || [];
			const page = result.page || {};
			const number = Number(page.number || 0);
			const totalPages = Number(page.totalPages || 0);
			const total = Number(page.totalElements || 0);
			const rowHtml = rows.map(row => `<tr>
				<td>${esc(row.msn)}</td><td><a class="tanesw-clickable">${esc(row.mblNo)}</a></td>
				<td>${esc(row.cnsiNm)}</td><td>${esc(row.blTpCd === "S" ? "[S] Simple" : row.blTpCd)}</td>
				<td>${esc(portName(row.loadPortCd))}</td><td>${esc(row.dlvrPlcCd)}</td>
				<td>${esc(`${row.blPckgNo || 0} ${row.pckgUtCd || ""}`)}</td><td>${esc(`${Number(row.blGwght || 0).toLocaleString()} ${row.gwghtUtCd || ""}`)}</td>
				<td>${esc(row.cntrCnt)}</td><td>${row.blAudtStatCd === "AP" ? '<span class="indicator-pill green">Approved</span>' : esc(row.blAudtStatCd)}</td>
			</tr>`).join('');
			$manifestContainer.find('#manifest-bl-body').html(rowHtml || '<tr><td colspan="10" class="tanesw-empty">No Master B/L records found</td></tr>');
			$manifestContainer.find('#manifest-bl-page-info').text(`Page: ${totalPages ? number + 1 : 0} / ${totalPages}   Total: ${total}`);
			let buttons = '';
			const first = Math.max(0, Math.min(number - 4, totalPages - 10));
			const last = Math.min(totalPages, first + 10);
			for (let p = first; p < last; p++) buttons += `<button class="btn btn-xs ${p === number ? 'btn-primary' : 'btn-default'} manifest-bl-page" data-page="${p}">${p + 1}</button>`;
			$manifestContainer.find('#manifest-bl-pages').html(buttons);
			$manifestContainer.find('.manifest-bl-page').on('click', function() { load_detail_page(Number($(this).data('page'))); });
		}

		function load_detail_page(page) {
			$manifestContainer.find('#manifest-bl-body').html('<tr><td colspan="10" class="text-center p-3"><div class="spinner-border spinner-border-sm text-secondary"></div></td></tr>');
			frappe.call({
				method: "tanesw_integration.api.manifest_detail",
				args: { mrn: info.mrn, page, size: 10, only_our_facility: detailOurOnly ? 1 : 0 },
				callback(r) { const m = r.message || {}; if (m.page) m.page.number = Number(m.page.number || 0); show_page(m); },
			});
		}

		paint_toggle();
		show_page(data);
		$manifestContainer.find('#btn-close-manifest').on('click', () => load_manifest_list(manifestListPage));
		$manifestContainer.find('#btn-toggle-our-bl').on('click', () => {
			detailOurOnly = !detailOurOnly;
			paint_toggle();
			load_detail_page(0);
		});
		$manifestContainer.find('#manifest-excel-download').on('click', () => {
			frappe.show_alert({ message: __("Generating Excel from TANeSW..."), indicator: "blue" });
			frappe.call({
				method: "tanesw_integration.api.download_manifest_excel",
				args: { mrn: info.mrn },
				callback(r) {
					const m = r.message || {};
					if (!m.content_base64) return;
					const byteChars = atob(m.content_base64);
					const byteNumbers = new Array(byteChars.length);
					for (let i = 0; i < byteChars.length; i++) byteNumbers[i] = byteChars.charCodeAt(i);
					const blob = new Blob([new Uint8Array(byteNumbers)], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
					const link = document.createElement("a");
					link.href = window.URL.createObjectURL(blob);
					link.download = m.filename || `Manifest_${info.mrn}.xlsx`;
					link.click();
					frappe.show_alert({ message: __("Excel downloaded successfully"), indicator: "green" });
				},
			});
		});
	}

	load_manifest_list(0);
}

// ==========================================
// 2. Tab: ICD Transfers
// ==========================================
// The old "ICD Transfers" tab and its declaration builder were removed: the builder filled in
// made-up values (departure WTTZDL008, seal "NIL", package unit PK) when TANeSW data was missing.
// ICD Transfer now lives on the Cargo Management page, which mirrors the TANeSW screens.
function tab_transfers($c) {
	frappe.set_route("tanesw-cargo", "cgme0301002q");
}

function tab_tracking($c) {
	const { $el: $filter, $bar, controls } = make_filter_bar([
		{ label: "Search Type", fieldname: "search_type", fieldtype: "Select", options: "Container\nBill of Lading", default: "Container" },
		{ label: "Tracking Number", fieldname: "search_no", placeholder: "e.g. MRSU1022192", default: "MRSU1022192" },
	]);

	add_bar_button($bar, __("Track Cargo"), "btn-primary", () => track_cargo());

	const $detailContainer = $(`<div id="tracking-detail-container" style="display: none;"></div>`);

	function track_cargo() {
		const sno = controls.search_no.get_value();
		if (!sno) {
			return frappe.show_alert({ message: __("Enter a container or B/L number"), indicator: "orange" });
		}
		const stype = controls.search_type.get_value() === "Container" ? "cntr" : "bl";
		$detailContainer.show().html(`<div class="text-center p-5 tanesw-card"><div class="spinner-border spinner-border-sm text-secondary"></div><span class="text-muted ml-2 small">Fetching complete cargo particulars and timeline from TANeSW...</span></div>`);

		frappe.call({
			method: "tanesw_integration.api.tracking_search",
			args: { search_type: stype, search_no: sno },
			callback(r) {
				const list = extract_list(r);
				if (!list || !list.length || !list[0]) {
					$detailContainer.html(`<div class="tanesw-empty">No tracking records found for ${frappe.utils.escape_html(sno)}</div>`);
					return;
				}
				const item = list[0];

				// Sibling containers table rows
				const cntrs = item.cntrLst || item.blCntrLst || [];
				let cntrRows = "";
				if (cntrs.length) {
					cntrRows = cntrs.map(c => `
						<tr class="${c.cntrNo === sno ? "table-primary font-weight-bold" : ""}">
							<td>${c.cntrNo || "-"}</td>
							<td>${c.cntrSizeCd || c.cntrSizeCdNm || "-"}</td>
							<td>${c.sealNo1 || "-"}</td>
							<td>${c.sealNo2 || c.sealNo3 || "-"}</td>
							<td>${c.cntrPckgNo || "0"} ${c.pckgUtCd || "PK"}</td>
							<td>${c.cntrWght || "0"} ${c.wghtUtCd || "KG"}</td>
							<td><span class="badge badge-info">${c.cagTrkngPrcssCdNm || item.cagTrkngPrcssCdNm || "Active"}</span></td>
							<td>${c.lastGodsLoctCdNm || item.lastGodsLoctCdNm || "-"}</td>
						</tr>
					`).join("");
				} else {
					cntrRows = `<tr><td colspan="8" class="text-center text-muted small py-2">Single container tracked (${frappe.utils.escape_html(item.cntrNo || sno)})</td></tr>`;
				}

				// Milestones history rows from blPrcssLst or tracking_history
				const processes = item.blPrcssLst || [];
				let processRows = "";
				if (processes.length) {
					processRows = processes.map(p => `
						<tr>
							<td><span class="badge badge-light border">${p.prcssDt || p.crioDt || "-"}</span></td>
							<td><strong>${p.cagTrkngPrcssCdNm || p.crioTpCdNm || "-"}</strong></td>
							<td>${p.wrhsCdNm || p.wrhsCd || "-"}</td>
							<td>${p.dclrNo || p.reffNo || "-"}</td>
							<td>${p.prcssPckgNo ? (p.prcssPckgNo + " " + (p.prcssPckgUtCd || "PK")) : "-"}</td>
							<td>${p.prcssWght ? (p.prcssWght + " KG") : "-"}</td>
						</tr>
					`).join("");
				} else {
					processRows = `<tr><td colspan="6" class="text-center text-muted small py-2">No lifecycle events recorded</td></tr>`;
				}

				const html = `
					<div class="tanesw-card mb-3">
						<div class="tanesw-card-header" style="background: var(--bg-light-gray);">
							<div>
								<h5 class="tanesw-card-title mb-0">Container / Consignment: ${frappe.utils.escape_html(item.cntrNo || sno)}</h5>
								<span class="text-muted small">CRN: <strong>${item.crn || "-"}</strong> | MRN: <strong>${item.mrn || "-"}</strong> | B/L: <strong>${item.mblNo || item.blNo || "-"}</strong></span>
							</div>
							<div>
								<span class="badge badge-primary px-3 py-2" style="font-size: 0.85rem;">${item.cagTrkngPrcssCdNm || item.stsCd || "Active"}</span>
							</div>
						</div>
						<div class="tanesw-card-body">
							<h6 class="font-weight-bold text-muted small text-uppercase mb-2">1. Routing, Vessel & Customs Clearance</h6>
							<div class="tanesw-stat-grid mb-3">
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Vessel / Voyage</div><div class="tanesw-stat-value">${item.vsslNm || "-"} / ${item.vygNo || "-"}</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">IMO No / Call Sign</div><div class="tanesw-stat-value">${item.imoNo || "-"} / ${item.csgn || "-"}</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Shipping Line / Carrier</div><div class="tanesw-stat-value">${item.carrNm || "-"}</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Customs Office</div><div class="tanesw-stat-value">${item.cstmOfceCdNm || item.cstmOfceCd || "TZDL"}</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Loading / Discharge Port</div><div class="tanesw-stat-value">${item.loadPortCdNm || item.loadPortCd || "-"} &rarr; ${item.dscgPortCdNm || item.dscgPortCd || "-"}</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Arrival Date (ETA/ATA)</div><div class="tanesw-stat-value">${item.actlArvlDt || item.xptdArvlDt || "-"}</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Delivery Shed / Terminal</div><div class="tanesw-stat-value">${item.dlvrPlcCdNm || item.dlvrPlcCd || "-"}</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Current Warehouse Location</div><div class="tanesw-stat-value">${item.lastGodsLoctCdNm || item.lctnNm || "-"}</div></div>
							</div>

							<h6 class="font-weight-bold text-muted small text-uppercase mb-2">2. Consignee, Parties & Cargo Specification</h6>
							<div class="tanesw-stat-grid mb-3">
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Consignee</div><div class="tanesw-stat-value">${item.cnsiNm || "-"} (${item.cnsiTin || "-"})</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Exporter / Shipper</div><div class="tanesw-stat-value">${item.exppnNm || "-"}</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Notify Party</div><div class="tanesw-stat-value">${item.ntprNm || "-"}</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Total Packages & Unit</div><div class="tanesw-stat-value">${item.blPckgNo || "0"} ${item.blPckgUtCd || "PK"}</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Gross / Net Weight</div><div class="tanesw-stat-value">${item.blGwght || 0} / ${item.blNwght || 0} KG</div></div>
								<div class="tanesw-stat-item"><div class="tanesw-stat-label">Volume / Measurement</div><div class="tanesw-stat-value">${item.blGvlm || 0} CBM</div></div>
								<div class="tanesw-stat-item" style="grid-column: span 2;"><div class="tanesw-stat-label">Goods Description</div><div class="tanesw-stat-value">${item.godsDesc || "-"}</div></div>
							</div>

							<h6 class="font-weight-bold text-muted small text-uppercase mb-2">3. Containers in Consignment (${cntrs.length || 1})</h6>
							<div class="table-responsive mb-4">
								<table class="table table-bordered table-sm mb-0">
									<thead><tr class="table-active"><th>Container No</th><th>Size/Type</th><th>Seal 1</th><th>Seal 2/3</th><th>Packages</th><th>Gross Weight</th><th>Status</th><th>Location</th></tr></thead>
									<tbody>${cntrRows}</tbody>
								</table>
							</div>

							<h6 class="font-weight-bold text-muted small text-uppercase mb-2">4. Lifecycle Milestones & Event Timeline (${processes.length})</h6>
							<div class="table-responsive mb-3">
								<table class="table table-bordered table-sm mb-0">
									<thead><tr class="table-active"><th>Date & Time</th><th>Milestone / Event Name</th><th>Warehouse / Facility</th><th>Document / Ref No</th><th>Packages</th><th>Weight (KG)</th></tr></thead>
									<tbody>${processRows}</tbody>
								</table>
							</div>

							<div style="display: flex; gap: 10px; margin-top: 15px; border-top: 1px solid var(--border-color); padding-top: 15px;">
								<a href="/app/tanesw-declaration" target="_blank" class="btn btn-primary btn-sm">Browse Declarations in Desk &rarr;</a>
								<a href="/app/tanesw-carry-in" target="_blank" class="btn btn-default btn-sm">Open Carry-In Desk &rarr;</a>
								<a href="/app/tanesw-inspection-booking" target="_blank" class="btn btn-default btn-sm">Open Joint Bookings &rarr;</a>
							</div>
						</div>
					</div>
				`;
				$detailContainer.html(html);
			},
			error() {
				$detailContainer.html(`<div class="tanesw-empty text-danger">Failed to fetch tracking data from TANeSW</div>`);
			}
		});
	}

	$c.append($filter).append($detailContainer);
	track_cargo();
}

// ==========================================
// 4. Tab: Carry-In
// ==========================================
const CARRY_IN_UNITS = { C: "Container", V: "Vehicle", L: "Loose", O: "Other", E: "Empty Container", B: "Bulk" };
const CARRY_IN_PROCESS_STATUS = { A01: "Registered", A04: "Submitted", D06: "Approved" };
const CARRY_IN_REPORT_STATUS = { "NOT REPORT": "Not Reported", "REPORTED PARTIALLY": "Partially Reported", REPORTED: "Reported" };

function carry_in_value(value) {
	return frappe.utils.escape_html(String(value == null || value === "" ? "-" : value));
}

function carry_in_badge(code, labels) {
	const label = labels[code] || code || "-";
	const color = code === "D06" || code === "REPORTED" ? "green" : code === "A01" || code === "A04" || code === "REPORTED PARTIALLY" ? "orange" : "gray";
	return `<span class="indicator-pill ${color}">${carry_in_value(label)}</span>`;
}

function tab_carry_in($c) {
	const { $el: $filter, $bar, controls } = make_filter_bar([
		{ label: "Approval Date From", fieldname: "dt_from", fieldtype: "Date", default: days_ago(14) },
		{ label: "Approval Date To", fieldname: "dt_to", fieldtype: "Date", default: today() },
		{ label: "Report Status", fieldname: "report_status", fieldtype: "Select", options: "All\nNot Report\nPartially Reported\nReported", default: "All" },
		{ label: "Container No", fieldname: "container_no", placeholder: "e.g. CAIU7935954" },
		{ label: "CRN", fieldname: "crn", placeholder: "Cargo Reference Number" },
	]);

	const table = make_table_panel(__("Carry-In"), [
		{ label: "No" }, { label: "CRN" }, { label: "Carry-In Type" }, { label: "Carry-In Base No" },
		{ label: "Approval Date" }, { label: "Processing Unit" }, { label: "Report Status" },
		{ label: "Target" }, { label: "Registered" }, { label: "Submitted" }, { label: "Approved" },
	]);
	const $paging = $(`<div class="tanesw-pagination"><span class="text-muted small"></span><div><button class="btn btn-default btn-xs prev">Previous</button><button class="btn btn-default btn-xs next">Next</button></div></div>`);
	let currentList = [];
	let pageNo = 0;
	let totalPages = 1;

	function report_status_code() {
		return { All: "N,P,Y", "Not Report": "N", "Partially Reported": "P", Reported: "Y" }[controls.report_status.get_value()] || "N,P,Y";
	}

	function load_carry_in(requestedPage) {
		pageNo = Math.max(0, requestedPage || 0);
		table.loading();
		frappe.call({
			method: "tanesw_integration.api.carry_in_list",
			args: {
				dt_from: controls.dt_from.get_value() || days_ago(14), dt_to: controls.dt_to.get_value() || today(),
				report_status: report_status_code(), container_no: controls.container_no.get_value(),
				crn: controls.crn.get_value(), page: pageNo, size: 10,
			},
			callback(r) {
				const message = r.message || {};
				currentList = message.content || [];
				const paging = message.page || {};
				totalPages = paging.totalPages || 1;
				table.fill(currentList, ["no", "crn", "criTpCd", "criBaseNo", "aprvDt", "crioPrcssUtCd", "rptStatNm", "trgtCnt", "rgsrCnt", "sbmtCnt", "aprvCnt"], (row, key, col, idx) => {
					if (key === "no") return pageNo * 10 + idx + 1;
					if (key === "crn") return `<a class="tanesw-carry-in-link" data-index="${idx}">${carry_in_value(row.crn)}</a>`;
					if (key === "crioPrcssUtCd") return carry_in_value(CARRY_IN_UNITS[row.crioPrcssUtCd] || row.crioPrcssUtCd);
					if (key === "rptStatNm") return carry_in_badge(row.rptStatNm, CARRY_IN_REPORT_STATUS);
				});
				$paging.find("span").text(`${paging.totalElements || currentList.length} result(s) · Page ${pageNo + 1} of ${totalPages}`);
				$paging.find(".prev").prop("disabled", pageNo === 0);
				$paging.find(".next").prop("disabled", pageNo + 1 >= totalPages);
			},
			error() { currentList = []; table.fill([], []); }
		});
	}

	add_bar_button($bar, __("Search"), "btn-primary", () => load_carry_in(0));
	add_bar_button($bar, __("Reset"), "btn-default", () => {
		controls.dt_from.set_value(days_ago(14)); controls.dt_to.set_value(today());
		controls.report_status.set_value("All"); controls.container_no.set_value(""); controls.crn.set_value("");
		load_carry_in(0);
	});
	table.$el.on("click", ".tanesw-carry-in-link", function () {
		const row = currentList[Number($(this).attr("data-index"))];
		if (row) show_carry_in_detail(row);
	});
	$paging.find(".prev").on("click", () => load_carry_in(pageNo - 1));
	$paging.find(".next").on("click", () => load_carry_in(pageNo + 1));
	$c.append($filter).append(table.$el).append($paging);
	load_carry_in(0);
}

function show_carry_in_detail(row) {
	const d = new frappe.ui.Dialog({ title: __("Carry-In Declaration Registration"), size: "extra-large" });
	d.$body.html(`<div class="text-center p-4"><div class="spinner-border spinner-border-sm text-secondary"></div><span class="text-muted ml-2 small">Loading Carry-In declaration...</span></div>`);
	d.show();
	frappe.call({
		method: "tanesw_integration.api.carry_in_detail",
		args: { crn: row.crn, wrhs_cd: row.wrhsCd, cri_base_no: row.criBaseNo },
		callback(r) {
			const info = r.message || {};
			const vehicles = info.wrhsCriVhclList || [], containers = info.wrhsCriCntrList || [], bills = info.wrhsCriBlList || [], items = info.wrhsCriItmList || [];
			const latest = vehicles[0] || containers[0] || bills[0] || items[0] || {};
			const vehicleRows = vehicles.length ? vehicles.map(v => `<tr>
				<td>${carry_in_value(v.dclrNo)}</td><td>${carry_in_badge(v.prcssStatCd, CARRY_IN_PROCESS_STATUS)}</td>
				<td>${carry_in_value(v.vhclNo)}</td><td>${carry_in_value(v.trlrNo)}</td><td>${carry_in_value(v.trpNo)}</td>
				<td>${carry_in_value(v.drvrNm)}</td><td>${carry_in_value(v.drvrLcneNo)}</td><td>${carry_in_value(v.bcodeNo)}</td>
				<td>${carry_in_value(v.cntrInfo)}</td><td>${carry_in_value(v.gateExitCfrmYn)}</td><td>${carry_in_value(v.entryCfrmYn)}</td>
			</tr>`).join("") : `<tr><td colspan="11" class="text-center text-muted">No vehicle records</td></tr>`;
			const genericRows = (rows, keys) => rows.length ? rows.map(x => `<tr>${keys.map(k => `<td>${carry_in_value(x[k])}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${keys.length}" class="text-center text-muted">No records</td></tr>`;

			d.$body.html(`
				<div class="tanesw-carry-detail">
					<div class="tanesw-breadcrumb">Cargo Mgmt. / Warehouse / Warehouse In/Out / Carry-In</div>
					<div class="tanesw-card-body">
						<div class="tanesw-detail-heading"><div><strong>${carry_in_value(info.criBaseNo)}</strong><div class="text-muted small">${carry_in_value(info.wrhsNm || info.wrhsCd)}</div></div><div class="carry-in-status-badge">${carry_in_badge(latest.prcssStatCd || info.rptStatNm, latest.prcssStatCd ? CARRY_IN_PROCESS_STATUS : CARRY_IN_REPORT_STATUS)}</div></div>
						<h6 class="tanesw-section-title">Carry-In Declaration</h6>
						<div class="tanesw-stat-grid mb-3">
							<div class="tanesw-stat-item"><div class="tanesw-stat-label">CRN</div><div class="tanesw-stat-value">${carry_in_value(info.crn)}</div></div>
							<div class="tanesw-stat-item"><div class="tanesw-stat-label">MRN</div><div class="tanesw-stat-value">${carry_in_value(info.mrn)}</div></div>
							<div class="tanesw-stat-item"><div class="tanesw-stat-label">Carry-In Type</div><div class="tanesw-stat-value">${carry_in_value(info.criTpCd)}</div></div>
							<div class="tanesw-stat-item"><div class="tanesw-stat-label">Processing Unit</div><div class="tanesw-stat-value">${carry_in_value(CARRY_IN_UNITS[info.crioPrcssUtCd] || info.crioPrcssUtCd)}</div></div>
							<div class="tanesw-stat-item"><div class="tanesw-stat-label">Approval Date</div><div class="tanesw-stat-value">${carry_in_value(info.aprvDt)}</div></div>
							<div class="tanesw-stat-item"><div class="tanesw-stat-label">Transfer Completion Date</div><div class="tanesw-stat-value">${carry_in_value(info.trsfEndDt)}</div></div>
							<div class="tanesw-stat-item"><div class="tanesw-stat-label">Expected Packages</div><div class="tanesw-stat-value">${carry_in_value(info.criXptdPckgNo)} ${carry_in_value(info.pckgUtCd)}</div></div>
							<div class="tanesw-stat-item"><div class="tanesw-stat-label">Expected Weight</div><div class="tanesw-stat-value">${carry_in_value(info.criXptdWght)} ${carry_in_value(info.wghtUtCd)}</div></div>
						</div>
						<h6 class="tanesw-section-title">Vehicle (${vehicles.length})</h6>
						<div class="table-responsive mb-3"><table class="tanesw-table"><thead><tr><th>Declaration No</th><th>Process Status</th><th>Vehicle</th><th>Trailer</th><th>Trip</th><th>Driver</th><th>Licence</th><th>Barcode</th><th>Container Information</th><th>Gate Exit</th><th>Entry Confirmed</th></tr></thead><tbody>${vehicleRows}</tbody></table></div>
						<h6 class="tanesw-section-title">Container (${containers.length})</h6>
						<div class="table-responsive mb-3"><table class="tanesw-table"><thead><tr><th>Container No</th><th>Size/Type</th><th>Seal</th><th>Packages</th><th>Weight</th><th>Status</th></tr></thead><tbody>${genericRows(containers, ["cntrNo", "cntrSizeCd", "sealNo1", "criPckgNo", "criWght", "prcssStatCd"])}</tbody></table></div>
						<h6 class="tanesw-section-title">Bill of Lading (${bills.length})</h6>
						<div class="table-responsive mb-3"><table class="tanesw-table"><thead><tr><th>Master B/L</th><th>House B/L</th><th>Packages</th><th>Weight</th><th>Status</th></tr></thead><tbody>${genericRows(bills, ["mblNo", "hblNo", "criPckgNo", "criWght", "prcssStatCd"])}</tbody></table></div>
						<h6 class="tanesw-section-title">Loose / Bulk / Other Items (${items.length})</h6>
						<div class="table-responsive mb-3"><table class="tanesw-table"><thead><tr><th>Item</th><th>HS Code</th><th>Description</th><th>Packages</th><th>Weight</th></tr></thead><tbody>${genericRows(items, ["itmNo", "hsCd", "godsDesc", "criPckgNo", "criWght"])}</tbody></table></div>
						<div class="tanesw-action-row">
							<button class="btn btn-primary btn-sm save-local">${__("Save to ERPNext")}</button>
							<button class="btn btn-default btn-sm register-remote">${__("Register in TANeSW")}</button>
							<button class="btn btn-danger btn-sm submit-remote">${__("Submit to TANeSW")}</button>
						</div>
					</div>
				</div>`);
			d.$body.find(".save-local").on("click", function () {
				const $button = $(this);
				frappe.call({
					method: "tanesw_integration.api.import_carry_in_record",
					args: { cri_base_no: info.criBaseNo || row.criBaseNo, data: info },
					freeze: true,
					freeze_message: __("Saving Carry-In into ERPNext..."),
					callback(res) {
						if (res.message && res.message.status === "ok") {
							frappe.show_alert({ message: __("Carry-In saved to ERPNext"), indicator: "green" });
							$button.prop("disabled", true).text(__("Saved to ERPNext"));
						}
					}
				});
			});
			d.$body.find(".register-remote").on("click", function () {
				const $button = $(this);
				frappe.confirm(__("Are you sure you want to register this Carry-In declaration with TANeSW?"), function () {
					frappe.call({
						method: "tanesw_integration.api.register_carry_in",
						args: { data: info },
						freeze: true,
						freeze_message: __("Registering Carry-In with TANeSW..."),
						callback(res) {
							const responseData = res.message || {};
							frappe.show_alert({ message: __("Carry-In registered with TANeSW"), indicator: "green" });
							$button.prop("disabled", true).text(__("Registered"));
							d.$body.find(".carry-in-status-badge").html(carry_in_badge("A01", CARRY_IN_PROCESS_STATUS));
							info.prcssStatCd = "A01";
							if (latest) {
								latest.prcssStatCd = "A01";
								if (responseData.dclrNo) { latest.dclrNo = responseData.dclrNo; }
							}
							frappe.call({
								method: "tanesw_integration.api.import_carry_in_record",
								args: { cri_base_no: info.criBaseNo || row.criBaseNo, data: Object.assign({}, info, responseData, { prcssStatCd: "A01" }) }
							});
						}
					});
				});
			});
			d.$body.find(".submit-remote").on("click", function () {
				const $button = $(this);
				frappe.confirm(__("Are you sure you want to submit this Carry-In declaration to TANeSW?"), function () {
					frappe.call({
						method: "tanesw_integration.api.submit_carry_in",
						args: { data: info },
						freeze: true,
						freeze_message: __("Submitting Carry-In to TANeSW..."),
						callback(res) {
							const responseData = res.message || {};
							frappe.show_alert({ message: __("Carry-In submitted to TANeSW"), indicator: "green" });
							$button.prop("disabled", true).text(__("Submitted"));
							d.$body.find(".carry-in-status-badge").html(carry_in_badge("D06", CARRY_IN_PROCESS_STATUS));
							info.prcssStatCd = "D06";
							info.rptStatNm = "REPORTED";
							if (latest) { latest.prcssStatCd = "D06"; }
							frappe.call({
								method: "tanesw_integration.api.import_carry_in_record",
								args: { cri_base_no: info.criBaseNo || row.criBaseNo, data: Object.assign({}, info, responseData, { prcssStatCd: "D06", rptStatNm: "REPORTED" }) }
							});
						}
					});
				});
			});
		},
		error() { d.$body.html(`<div class="text-danger p-3 text-center">Failed to load Carry-In declaration</div>`); }
	});
}

// ==========================================
// 5. Tab: Carry-Out
// ==========================================
function tab_carry_out($c) {
	const { $el: $filter, $bar, controls } = make_filter_bar([
		{ label: "From Date", fieldname: "dt_from", fieldtype: "Date", default: days_ago(7) },
		{ label: "To Date", fieldname: "dt_to", fieldtype: "Date", default: today() },
	]);

	add_bar_button($bar, __("Search Carry-Out"), "btn-primary", () => load_carry_out());

	const table = make_table_panel(__("Warehouse Carry-Out Records"), [
		{ label: "CRO Reference No" },
		{ label: "CRN" },
		{ label: "MRN" },
		{ label: "Warehouse" },
		{ label: "Containers" },
		{ label: "Customs Value" },
		{ label: "Date" },
		{ label: "Status" },
		{ label: "Actions" },
	]);

	function load_carry_out() {
		table.loading();
		frappe.call({
			method: "tanesw_integration.api.carry_out_list",
			args: {
				dt_from: controls.dt_from.get_value(),
				dt_to: controls.dt_to.get_value(),
				page: 0,
				size: 50,
			},
			callback(r) {
				const list = extract_list(r);
				table.fill(list, ["croBaseNo", "crn", "mrn", "wrhsNm", "cntrCnt", "cstmVal", "aprvDt", "stsCd", "actions"], (row, key) => {
					if (key === "croBaseNo") {
						return `<a class="tanesw-clickable" data-cro="${frappe.utils.escape_html(row.croBaseNo)}">${frappe.utils.escape_html(row.croBaseNo)}</a>`;
					}
					if (key === "actions") {
						return `<button class="btn btn-default btn-xs btn-view-cro" data-cro="${frappe.utils.escape_html(row.croBaseNo)}">View Detail</button>`;
					}
				});
			},
			error() {
				table.fill([], []);
			}
		});
	}

	table.$el.on("click", ".btn-view-cro, .tanesw-clickable", function () {
		const cro_no = $(this).attr("data-cro");
		if (cro_no) show_carry_out_detail(cro_no);
	});

	$c.append($filter).append(table.$el);
	load_carry_out();
}

function show_carry_out_detail(cro_base_no) {
	const d = new frappe.ui.Dialog({
		title: __("Carry-Out Detail: {0}", [cro_base_no]),
		size: "large",
	});
	d.$body.html(`<div class="text-center p-4"><div class="spinner-border spinner-border-sm text-secondary"></div><span class="text-muted ml-2 small">Loading details...</span></div>`);
	d.show();

	frappe.call({
		method: "tanesw_integration.api.carry_out_detail",
		args: { cro_base_no },
		callback(r) {
			const data = r.message || {};
			const info = data.wrhsCro || (Array.isArray(data) ? (data[0] || {}) : data);
			let html = `
				<div class="tanesw-stat-grid mb-3">
					<div class="tanesw-stat-item"><div class="tanesw-stat-label">CRO Reference</div><div class="tanesw-stat-value">${info.croBaseNo || cro_base_no}</div></div>
					<div class="tanesw-stat-item"><div class="tanesw-stat-label">CRN</div><div class="tanesw-stat-value">${info.crn || "-"}</div></div>
					<div class="tanesw-stat-item"><div class="tanesw-stat-label">MRN</div><div class="tanesw-stat-value">${info.mrn || "-"}</div></div>
					<div class="tanesw-stat-item"><div class="tanesw-stat-label">Release Date</div><div class="tanesw-stat-value">${info.aprvDt || info.croDt || "-"}</div></div>
					<div class="tanesw-stat-item"><div class="tanesw-stat-label">Containers</div><div class="tanesw-stat-value">${info.cntrCnt != null ? info.cntrCnt : "-"}</div></div>
					<div class="tanesw-stat-item"><div class="tanesw-stat-label">Status</div><div class="tanesw-stat-value">${status_indicator(info.rptStatNm || info.stsCd)}</div></div>
				</div>
			`;
			d.$body.html(html);
		},
		error() {
			d.$body.html(`<div class="text-danger p-3 text-center">Failed to load carry-out details</div>`);
		}
	});
}

// ==========================================
// 6/7. Bookings & Inspections -> Joint Inspection page
// ==========================================
// The full LPCO > Joint Inspection module (Target List, Booking List/Details,
// Registration, Modify, Result Registration, Result Search, Objection) lives
// on its own page so its navigation matches the TANeSW portal.
function joint_inspection_link($c, screen, label) {
	$c.append(`
		<div class="tanesw-card p-4 text-center">
			<p class="text-muted mb-3">${__("This screen now lives on the Joint Inspection page, which mirrors LPCO > Joint Inspection on TANeSW.")}</p>
			<button class="btn btn-primary btn-sm">${__(label)}</button>
		</div>`);
	$c.find("button").on("click", () => frappe.set_route("tanesw-joint-inspection", screen));
}

function tab_bookings($c) {
	joint_inspection_link($c, "eswe0105002q", "Open Inspection Booking List");
}

function tab_inspections($c) {
	joint_inspection_link($c, "eswe0105007q", "Open Inspection Result Search");
}
