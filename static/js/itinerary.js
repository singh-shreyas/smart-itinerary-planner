// Route map for the itinerary page (Leaflet + OpenStreetMap tiles).
// The itinerary is complete without it: if Leaflet or the tiles fail, a short note is shown instead.
(function () {
  "use strict";
  var t = window.I18N ? window.I18N.t : function (x) { return x; };

  var card = document.getElementById("map-card");
  var el = document.getElementById("route-map");
  var label = document.getElementById("map-day-label");
  if (!card || !el) return;

  function fail() { card.classList.add("map-failed"); }
  function esc(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var data;
  try { data = JSON.parse(document.getElementById("map-data").textContent); } catch (e) { fail(); return; }
  if (!window.L) { fail(); return; }

  var map, layer;
  try {
    map = L.map(el, { scrollWheelZoom: false, zoomControl: true }).setView(data.center, 12);
    var tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    var loaded = 0, errors = 0;
    tiles.on("tileload", function () { loaded++; });
    tiles.on("tileerror", function () {
      errors++;
      if (errors === 6 && loaded === 0) {
        var note = L.control({ position: "bottomleft" });
        note.onAdd = function () {
          var div = L.DomUtil.create("div", "chip chip-light");
          div.textContent = "Map tiles unavailable offline; markers still show the stops.";
          return div;
        };
        note.addTo(map);
      }
    });
    layer = L.layerGroup().addTo(map);
    (data.cities || []).forEach(function (c) {
      L.marker([c.lat, c.lng], {
        icon: L.divIcon({ className: "", html: '<div class="map-city-label">' + esc(c.name) + "</div>", iconSize: [0, 0] }),
        interactive: false, keyboard: false
      }).addTo(map);
    });
  } catch (e) { fail(); return; }

  function pin(lat, lng, html, cls) {
    return L.marker([lat, lng], {
      icon: L.divIcon({ className: "", html: '<div class="map-marker ' + cls + '">' + html + "</div>", iconSize: [30, 30], iconAnchor: [15, 15], popupAnchor: [0, -14] }),
      keyboard: true
    });
  }

  function draw(dayIndex) {
    var day = data.days.filter(function (d) { return d.index === dayIndex; })[0] || data.days[0];
    if (!day) return;
    layer.clearLayers();
    // Each day starts at last night's stay and ends at tonight's (a different one on a travel day).
    var start = day.from || data.start, finish = day.to || data.start;
    var moves = start.lat !== finish.lat || start.lng !== finish.lng;
    var points = [[start.lat, start.lng]];
    pin(start.lat, start.lng, '<i class="bi bi-house-door"></i>', "is-home")
      .bindPopup("<strong>" + esc(start.name) + "</strong><br>" + esc(t(moves ? "Start of the day" : "Start and end of the day"))).addTo(layer);
    if (moves) {
      pin(finish.lat, finish.lng, '<i class="bi bi-moon-stars"></i>', "is-home")
        .bindPopup("<strong>" + esc(finish.name) + "</strong><br>" + esc(t("Tonight's stay"))).addTo(layer);
    }
    day.stops.forEach(function (s) {
      points.push([s.lat, s.lng]);
      if (s.kind === "meal") {
        pin(s.lat, s.lng, '<i class="bi bi-egg-fried"></i>', "is-meal")
          .bindPopup("<strong>" + esc(s.name) + "</strong><br>" + esc(s.time)).addTo(layer);
      } else {
        pin(s.lat, s.lng, s.n, "").bindPopup("<strong>" + s.n + ". " + esc(s.name) + "</strong><br>" + esc(s.time) +
          (data.cities && data.cities.length ? "<br><span class='text-muted'>" + esc(s.city) + "</span>" : "")).addTo(layer);
      }
    });
    if (day.stops.length || moves) {
      points.push([finish.lat, finish.lng]);
      // Straight dashed segments in visit order -- deliberately NOT drawn as if they were roads.
      var route = getComputedStyle(document.documentElement).getPropertyValue("--route").trim() || "#1B4D43";
      L.polyline(points, { color: route, weight: 3, opacity: 0.9, dashArray: "6 9", lineCap: "round" }).addTo(layer);
      map.fitBounds(L.latLngBounds(points).pad(0.18), { maxZoom: 14 });
    } else {
      map.setView([start.lat, start.lng], 13);
    }
    if (label) label.textContent = t("Day {n}").replace("{n}", day.index);
  }

  var current = 1;
  draw(current);
  document.querySelectorAll('[data-bs-toggle="tab"][data-day]').forEach(function (tab) {
    tab.addEventListener("shown.bs.tab", function () { current = parseInt(tab.dataset.day, 10); draw(current); });
  });
  document.addEventListener("themechange", function () { draw(current); });     // route colour follows the theme
  window.addEventListener("load", function () { map.invalidateSize(); });
})();
