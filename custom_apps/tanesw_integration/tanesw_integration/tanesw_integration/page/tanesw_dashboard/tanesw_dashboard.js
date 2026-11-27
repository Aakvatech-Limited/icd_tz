// TANeSW Dashboard: every figure for a chosen date range, Local vs Transit, against the KPI Target.
frappe.pages["tanesw-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("TANeSW Dashboard"), single_column: true });
	const today = frappe.datetime.get_today();
	const from = page.add_field({ fieldname: "from_date", label: __("From"), fieldtype: "Date",
		default: frappe.datetime.month_start(), change: () => refresh() });
	const to = page.add_field({ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: today,
		change: () => refresh() });
	const company = page.add_field({ fieldname: "company", label: __("Company (targets)"), fieldtype: "Link",
		options: "Company", default: frappe.defaults.get_user_default("Company"), change: () => refresh() });
	const presets = [
		[__("Today"), () => [today, today]],
		[__("This Week"), () => [frappe.datetime.week_start(), today]],
		[__("This Month"), () => [frappe.datetime.month_start(), today]],
		[__("Last Month"), () => {
			const s = frappe.datetime.add_months(frappe.datetime.month_start(), -1);
			return [s, frappe.datetime.month_end(s)];
		}],
	];
	presets.forEach(([label, fn]) => page.add_inner_button(label, () => {
		const [s, e] = fn();
		from.set_value(s);
		to.set_value(e);
	}, __("Period")));
	page.set_primary_action(__("Refresh"), () => refresh(), "refresh");

	const $body = $(`<div class="tanesw-dash"></div>`).appendTo(page.body);
	let busy = false;

	function refresh() {
		if (busy) return;
		busy = true;
		frappe.call({
			method: "tanesw_integration.dashboard.get_dashboard",
			args: { from_date: from.get_value(), to_date: to.get_value(), company: company.get_value() },
			freeze: true, freeze_message: __("Loading..."),
		}).then((r) => render(r.message)).always(() => { busy = false; });
	}

	function open(item) {
		if (item.report) frappe.set_route("query-report", item.report, item.filters || {});
		else if (item.list) frappe.set_route("List", item.list, item.list_filters || {});
	}

	function split_line(s) {
		if (!s) return "";
		let t = `${__("Local")} <b>${s.Local || 0}</b> · ${__("Transit")} <b>${s.Transit || 0}</b>`;
		if (s.Unknown) t += ` · ${__("Unknown")} <b>${s.Unknown}</b>`;
		return t;
	}

	function card(item) {
		let main, sub = "";
		if (item.value_only) {
			main = Object.entries(item.values).map(([k, v]) => `<span class="mr-3">${__(k)} <b>${v}</b></span>`).join("");
		} else if (item.split) {
			main = item.split.total;
			sub = split_line(item.split);
		} else {
			main = item.value;
		}
		const n = item.split ? item.split.total : item.value;
		const tone = (item.bad && n) ? "red" : (item.warn && n) ? "orange" : "";
		let target = "";
		if (item.target) {
			const pct = item.pct || 0;
			const bar = pct >= 100 ? "green" : pct >= 80 ? "orange" : "red";
			target = `<div class="tanesw-dash-target">${__("Target")} ${item.target} · <b>${pct}%</b>
				<div class="tanesw-dash-bar"><div class="${bar}" style="width:${Math.min(pct, 100)}%"></div></div></div>`;
		} else if (["allocated", "received"].includes(item.key)) {
			target = `<div class="tanesw-dash-target text-muted">${__("No KPI Target for this period")}</div>`;
		}
		const $c = $(`<div class="tanesw-dash-card ${tone} ${item.report || item.list ? "clickable" : ""}">
			<div class="tanesw-dash-label">${__(item.label)}</div>
			<div class="tanesw-dash-value">${main}</div>
			<div class="tanesw-dash-split">${sub}</div>${target}</div>`);
		$c.on("click", () => open(item));
		return $c;
	}

	function section(title, items, note) {
		const $s = $(`<div class="tanesw-dash-section"><div class="tanesw-dash-title">${title}
			${note ? `<span class="text-muted small ml-2">${note}</span>` : ""}</div><div class="tanesw-dash-grid"></div></div>`);
		items.forEach((i) => $s.find(".tanesw-dash-grid").append(card(i)));
		return $s;
	}

	function render(d) {
		$body.empty();
		if (d.tanesw_paused) {
			const until = frappe.datetime.str_to_user(d.tanesw_paused.until);
			$body.append(`<div class="alert alert-warning small">${__("TANeSW is not responding. Background sync is paused until {0} and restarts on its own; figures may be behind.", [until])}</div>`);
		}
		const period = `${frappe.datetime.str_to_user(d.from_date)} – ${frappe.datetime.str_to_user(d.to_date)}`;
		$body.append(section(__("Container movement"), d.movement, period));
		$body.append(section(__("At the port now"), d.port_now,
			__("Free days: Local 5, Transit 15, from the discharge day")));
		$body.append(section(__("Left the port in the period"), d.port_range, period));
		$body.append(section(__("Needs attention"), d.attention));
		const $chart = $(`<div class="tanesw-dash-section"><div class="tanesw-dash-title">${__("Received per day")}</div>
			<div class="tanesw-dash-chart"></div></div>`).appendTo($body);
		if (d.chart_received.datasets.length) {
			new frappe.Chart($chart.find(".tanesw-dash-chart")[0], {
				data: d.chart_received, type: "bar", height: 260, barOptions: { stacked: 1 },
				colors: ["#2490ef", "#7c3aed", "#9ca3af"],
			});
		} else {
			$chart.find(".tanesw-dash-chart").html(`<div class="text-muted small">${__("Nothing received in this period")}</div>`);
		}
	}

	refresh();
};
