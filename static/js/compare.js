// Charts and the route-shape map on the comparison page.
// Every value drawn here is also in a table on the page (charts enhance, never gate).
(function () {
  "use strict";

  var data = JSON.parse(document.getElementById("chart-data").textContent);

  // Categorical slots, validated together (all pairs, light surface) with the dataviz palette checker.
  // Slot 1 always marks the method the planner actually uses (DP, or NN + 2-opt).
  var SLOT = ["#2a7a52", "#e8894a", "#3f6fb6"];
  var INK = "#1B2A41", MUTED = "#6B6257", GRID = "#ECE5D8", SURFACE = "#FFFFFF";

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
      backgroundColor: "#15233A", titleColor: "#fff", bodyColor: "#F7F2E9", padding: 10, cornerRadius: 8,
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
  function bars(label, values, color) {
    return {
      label: label, data: values, backgroundColor: color, hoverBackgroundColor: color,
      maxBarThickness: 24, barPercentage: 0.82, categoryPercentage: 0.72,
      borderRadius: { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 }, borderSkipped: "start"
    };
  }
  function line(label, values, color) {
    return {
      label: label, data: values, borderColor: color, backgroundColor: color, borderWidth: 2,
      pointRadius: 4, pointHoverRadius: 6, pointBorderColor: SURFACE, pointBorderWidth: 2,
      pointHitRadius: 12, tension: 0, borderCapStyle: "round", borderJoinStyle: "round"
    };
  }
  function barChart(id, labels, datasets, unit, yTitle) {
    var el = document.getElementById(id);
    if (!el || !window.Chart) return;
    new Chart(el, {
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
    var el = document.getElementById(id);
    if (!el || !window.Chart) return;
    new Chart(el, {
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

  // 1. Value score per day, by strategy
  var byKey = data.by_key;
  if (byKey && byKey.dp) {
    var days = byKey.dp.per_day.map(function (d) { return "Day " + d.day; });
    barChart("chart-strategies", days, [
      bars("DP", byKey.dp.per_day.map(function (d) { return d.score; }), SLOT[0]),
      bars("Greedy", byKey.greedy.per_day.map(function (d) { return d.score; }), SLOT[1]),
      bars("Max visits", byKey.max_visits.per_day.map(function (d) { return d.score; }), SLOT[2])
    ], "", "score");
  }

  // 3. Travel minutes per day, by routing method
  var routing = data.routing || [];
  if (routing.length) {
    barChart("chart-routing", routing.map(function (r) { return "Day " + r.day; }), [
      bars("NN + 2-opt", routing.map(function (r) { return r.two_opt.travel; }), SLOT[0]),
      bars("Nearest Neighbour", routing.map(function (r) { return r.nn.travel; }), SLOT[1]),
      bars("Held–Karp (optimal)", routing.map(function (r) { return r.held_karp ? r.held_karp.travel : null; }), SLOT[2])
    ], " min", "minutes");
  }

  // 5. Scaling benchmarks from results/benchmarks.json
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

  // Route-shape map: NN order vs the 2-opt result for one day.
  var card = document.getElementById("compare-map-card");
  var mapEl = document.getElementById("compare-map");
  if (!card || !mapEl || !routing.length) return;
  if (!window.L) { card.classList.add("map-failed"); return; }
  var map, group;
  try {
    map = L.map(mapEl, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
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
