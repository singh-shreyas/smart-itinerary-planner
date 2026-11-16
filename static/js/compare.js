// Charts and the route-shape map on the comparison page.
// Every value drawn here is also in a table on the page (charts enhance, never gate).
(function () {
  "use strict";

  var data = JSON.parse(document.getElementById("chart-data").textContent);

  // Series colours follow the strategy everywhere on the page and come from the theme tokens
  // (--c-dp, --c-greedy, --c-exact in tokens.css), so charts, tables and bars always agree.
  var t = window.I18N ? window.I18N.t : function (x) { return x; };
  var STRATEGY, SLOT, SEGMENT, INK, MUTED, GRID, SURFACE, TIP;
  function usePalette() {
    var css = getComputedStyle(document.documentElement);
    function v(name, fallback) { return css.getPropertyValue(name).trim() || fallback; }
    STRATEGY = { dp: v("--c-dp", "#2456D6"), greedy: v("--c-greedy", "#DB7A2B") };
    SLOT = [STRATEGY.dp, STRATEGY.greedy, v("--c-exact", "#137A68")];
    SEGMENT = { sight: SLOT[0], travel: SLOT[1], meal: SLOT[2], wait: v("--c-wait", "#C79A2B"), free: v("--c-free", "#D9D5CB") };
    INK = v("--text", "#14213D");
    MUTED = v("--muted", "#667085");
    GRID = v("--line", "#EAE5DA");
    SURFACE = v("--surface", "#FFFFFF");
    TIP = { bg: v("--surface", "#fff"), border: v("--line-3", "#C4BCAC"), body: v("--text-2", "#3B4763") };
    if (window.Chart) Chart.defaults.color = MUTED;
  }
  usePalette();

  if (window.Chart) {
    Chart.defaults.font.family = "Inter, -apple-system, 'Segoe UI', system-ui, sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = MUTED;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.animation = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 400 };
  }

  function legend() {
    return {
      position: "top", align: "start",
      labels: { color: INK, usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10, boxHeight: 10, padding: 14 }
    };
  }
  function tooltip(unit) {
    return {
      backgroundColor: TIP.bg, titleColor: INK, bodyColor: TIP.body, borderColor: TIP.border, borderWidth: 1, padding: 10, cornerRadius: 8,
      boxPadding: 4, usePointStyle: true,
      callbacks: { label: function (ctx) { return " " + ctx.dataset.label + ": " + ctx.formattedValue + (unit || ""); } }
    };
  }
  function axis(title, extra) {
    var a = {
      grid: { color: GRID, lineWidth: 1, drawTicks: false },
      border: { display: false },
      ticks: { color: MUTED, padding: 6 },
      title: title ? { display: true, text: title, color: MUTED, font: { size: 11 } } : undefined
    };
    for (var k in extra || {}) a[k] = extra[k];
    return a;
  }
  function bars(label, values, color, horizontal) {
    return {
      label: label, data: values, backgroundColor: color, hoverBackgroundColor: color,
      maxBarThickness: 26, barPercentage: 0.82, categoryPercentage: 0.72,
      borderColor: SURFACE, borderWidth: { top: 0, right: horizontal ? 2 : 0, bottom: 0, left: 0 },
      borderRadius: horizontal ? { topRight: 4, bottomRight: 4, topLeft: 0, bottomLeft: 0 }
                               : { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
      borderSkipped: "start"
    };
  }
  function line(label, values, color) {
    return {
      label: label, data: values, borderColor: color, backgroundColor: color, borderWidth: 2,
      pointRadius: 4, pointHoverRadius: 6, pointBorderColor: SURFACE, pointBorderWidth: 2,
      pointHitRadius: 12, tension: 0, borderCapStyle: "round", borderJoinStyle: "round"
    };
  }
  var charts = [];
  function chart(id, config) {
    var el = document.getElementById(id);
    if (!el || !window.Chart) return;
    charts.push(new Chart(el, config));
  }
  function barChart(id, labels, datasets, unit, yTitle) {
    chart(id, {
      type: "bar",
      data: { labels: labels, datasets: datasets },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: legend(), tooltip: tooltip(unit) },
        scales: { x: axis(null, { grid: { display: false } }), y: axis(yTitle, { beginAtZero: true }) }
      }
    });
  }
  function lineChart(id, labels, datasets, unit, yTitle, xTitle, logY) {
    chart(id, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: legend(), tooltip: tooltip(unit) },
        scales: {
          x: axis(xTitle, { grid: { display: false } }),
          y: logY ? axis(yTitle, {
            type: "logarithmic",
            ticks: { color: MUTED, padding: 6, callback: function (v) {
              var s = Number(v).toString();
              return /^(1|2|5)/.test(s) ? (v >= 1 ? v : v.toPrecision(1)) : "";
            } }
          }) : axis(yTitle, { beginAtZero: true })
        }
      }
    });
  }

  var rows = data.strategies || [];
  var routing = data.routing || [];

  function drawCharts() {

  // 1a. The subscores are drawn in HTML (the head-to-head bars), so only the time and per-day charts follow.
  if (rows.length) {
    // 1b. Where the time goes (stacked horizontal bars, one per strategy)
    var segs = [
      ["Sightseeing", SEGMENT.sight, function (m) { return m.sight_min; }],
      ["Travel", SEGMENT.travel, function (m) { return m.travel_min; }],
      ["Meals", SEGMENT.meal, function (m) { return m.meal_min; }],
      ["Waiting + buffer", SEGMENT.wait, function (m) { return m.wait_min + m.buffer_min; }],
      ["Unused", SEGMENT.free, function (m) { return m.free_min; }]
    ];
    chart("chart-timeuse", {
      type: "bar",
      data: {
        labels: rows.map(function (r) { return r.short; }),
        datasets: segs.map(function (s) {
          var d = bars(s[0], rows.map(function (r) { return s[2](r.metrics); }), s[1], true);
          d.borderRadius = 0;
          d.borderWidth = { top: 0, right: 2, bottom: 0, left: 0 };   // 2px surface gap between segments
          return d;
        })
      },
      options: {
        indexAxis: "y",
        interaction: { mode: "index", intersect: false },
        plugins: { legend: legend(), tooltip: tooltip(" min") },
        scales: { x: axis("minutes", { stacked: true, beginAtZero: true }), y: axis(null, { stacked: true, grid: { display: false } }) }
      }
    });

    // 1c. Value score per day, by strategy
    var days = rows[0].per_day.map(function (d) { return "Day " + d.day; });
    barChart("chart-strategies", days, rows.map(function (r) {
      return bars(r.short, r.per_day.map(function (d) { return d.score; }), STRATEGY[r.key]);
    }), "", "score");
  }

  // 4. Travel minutes per day, by routing method
  if (routing.length) {
    barChart("chart-routing", routing.map(function (r) { return "Day " + r.day; }), [
      bars("NN + 2-opt", routing.map(function (r) { return r.two_opt.travel; }), SLOT[0]),
      bars("Nearest Neighbour", routing.map(function (r) { return r.nn.travel; }), SLOT[1]),
      bars("Held–Karp (optimal)", routing.map(function (r) { return r.held_karp ? r.held_karp.travel : null; }), SLOT[2])
    ], " min", "minutes");
  }

  // 6. Scaling benchmarks from results/benchmarks.json
  var bm = data.benchmarks;
  if (bm) {
    lineChart("chart-bm-selection", bm.selection.map(function (r) { return r.n; }), [
      line("DP", bm.selection.map(function (r) { return r.dp_ms; }), SLOT[0]),
      line("Greedy", bm.selection.map(function (r) { return r.greedy_ms; }), SLOT[1])
    ], " ms", "ms (log)", "attractions n", true);
    lineChart("chart-bm-routing", bm.routing.map(function (r) { return r.k; }), [
      line("2-opt", bm.routing.map(function (r) { return r.two_opt_ms; }), SLOT[0]),
      line("Nearest Neighbour", bm.routing.map(function (r) { return r.nn_ms; }), SLOT[1]),
      line("Held–Karp", bm.routing.map(function (r) { return r.held_karp_ms; }), SLOT[2])
    ], " ms", "ms (log)", "stops k", true);
    lineChart("chart-bm-gap", bm.routing.map(function (r) { return r.k; }), [
      line("NN + 2-opt", bm.routing.map(function (r) { return r.two_opt_gap_pct; }), SLOT[0]),
      line("Nearest Neighbour", bm.routing.map(function (r) { return r.nn_gap_pct; }), SLOT[1])
    ], "%", "% above optimum", "stops k", false);
  }

  }
  drawCharts();
  // The theme toggle re-draws every chart in the new colours (no page reload).
  document.addEventListener("themechange", function () {
    charts.forEach(function (c) { c.destroy(); });
    charts = [];
    usePalette();
    drawCharts();
  });

  // Route-shape map: NN order vs the 2-opt result for one day.
  var card = document.getElementById("compare-map-card");
  var mapEl = document.getElementById("compare-map");
  if (!card || !mapEl || !routing.length) return;
  if (!window.L) { card.classList.add("map-failed"); return; }
  var map, group;
  try {
    map = L.map(mapEl, { scrollWheelZoom: false });
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, tiles &copy; <a href="https://www.esri.com/">Esri</a>'
    }).addTo(map);
    group = L.layerGroup().addTo(map);
  } catch (e) { card.classList.add("map-failed"); return; }

  function draw(i) {
    var r = routing[i];
    group.clearLayers();
    L.polyline(r.routes.nn, { color: SLOT[1], weight: 3, opacity: 0.9, dashArray: "6 8" }).addTo(group);
    L.polyline(r.routes.two_opt, { color: SLOT[0], weight: 3, opacity: 0.95 }).addTo(group);
    r.routes.two_opt.slice(1, -1).forEach(function (p) {
      L.circleMarker(p, { radius: 5, color: SURFACE, weight: 2, fillColor: INK, fillOpacity: 1 }).addTo(group);
    });
    var home = r.routes.two_opt[0];
    L.circleMarker(home, { radius: 7, color: SURFACE, weight: 2, fillColor: SLOT[0], fillOpacity: 1 })
      .bindTooltip("Start point").addTo(group);
    map.fitBounds(L.latLngBounds(r.routes.two_opt).pad(0.2), { maxZoom: 14 });
  }
  var select = document.getElementById("route-day");
  select.addEventListener("change", function () { draw(parseInt(select.value, 10)); });
  draw(0);
})();
