// Route map for the itinerary workspace (Leaflet + OpenStreetMap tiles, themed in CSS).
// The itinerary is complete without it: if Leaflet or the tiles fail, a short note is shown instead.
// Selecting a stop card focuses its marker, and selecting a marker highlights its card.
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

  var map, layer, markers = {}, current = 1;
  try {
    map = L.map(el, { scrollWheelZoom: true, zoomControl: true, zoomSnap: 0.5 }).setView(data.center, 12);
    var tiles = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, tiles &copy; <a href="https://www.esri.com/">Esri</a>'
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
      icon: L.divIcon({ className: "", html: '<div class="map-marker ' + cls + '">' + html + "</div>", iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -14] }),
      keyboard: true, riseOnHover: true
    });
  }

  function cardsOf(day) { return document.querySelectorAll('.timeline[data-day="' + day + '"] .stop-card'); }
  function highlight(n, scroll) {
    cardsOf(current).forEach(function (c) { c.classList.toggle("is-active", String(c.dataset.stop) === String(n)); });
    Object.keys(markers).forEach(function (k) {
      var node = markers[k].getElement();
      if (node && node.firstChild) node.firstChild.classList.toggle("is-active", String(k) === String(n));
    });
    if (scroll) {
      var target = document.querySelector('.timeline[data-day="' + current + '"] .stop-card[data-stop="' + n + '"]');
      if (target) target.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function draw(dayIndex) {
    var day = data.days.filter(function (d) { return d.index === dayIndex; })[0] || data.days[0];
    if (!day) return;
    layer.clearLayers();
    markers = {};
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
        var m = pin(s.lat, s.lng, s.n, "").bindPopup("<strong>" + s.n + ". " + esc(s.name) + "</strong><br>" + esc(s.time) +
          (data.cities && data.cities.length ? "<br><span class='text-muted'>" + esc(s.city) + "</span>" : "")).addTo(layer);
        m.on("click", function () { highlight(s.n, true); });
        markers[s.n] = m;
      }
    });
    if (day.stops.length || moves) {
      points.push([finish.lat, finish.lng]);
      // Straight dashed segments in visit order -- deliberately NOT drawn as if they were roads.
      var css = getComputedStyle(document.documentElement);
      var route = css.getPropertyValue("--route").trim() || "#2456D6";
      L.polyline(points, { color: css.getPropertyValue("--surface").trim() || "#fff", weight: 6, opacity: 0.75 }).addTo(layer);
      L.polyline(points, { color: route, weight: 2.5, opacity: 0.95, dashArray: "6 8", lineCap: "round" }).addTo(layer);
      map.fitBounds(L.latLngBounds(points).pad(0.2), { maxZoom: 14 });
    } else {
      map.setView([start.lat, start.lng], 13);
    }
    if (label) label.textContent = t("Day {n}").replace("{n}", day.index);
  }

  draw(current);
  var wanted = location.hash && document.querySelector('[data-bs-target="' + location.hash + '"]');
  if (wanted && window.bootstrap) bootstrap.Tab.getOrCreateInstance(wanted).show();
  document.querySelectorAll('[data-bs-toggle="tab"][data-day]').forEach(function (tab) {
    tab.addEventListener("shown.bs.tab", function () { current = parseInt(tab.dataset.day, 10); draw(current); });
  });

  // Stop cards -> marker. Links inside a card keep working normally.
  document.querySelectorAll(".stop-card[data-stop]").forEach(function (cardEl) {
    function focusStop(e) {
      if (e.target.closest("a, button")) return;
      var n = cardEl.dataset.stop, m = markers[n];
      highlight(n, false);
      if (m) { map.flyTo(m.getLatLng(), Math.max(map.getZoom(), 14), { duration: 0.6 }); m.openPopup(); }
    }
    cardEl.addEventListener("click", focusStop);
    cardEl.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); focusStop(e); } });
    cardEl.addEventListener("mouseenter", function () {
      var m = markers[cardEl.dataset.stop];
      if (m && m.getElement() && m.getElement().firstChild) m.getElement().firstChild.classList.add("is-active");
    });
    cardEl.addEventListener("mouseleave", function () {
      if (cardEl.classList.contains("is-active")) return;
      var m = markers[cardEl.dataset.stop];
      if (m && m.getElement() && m.getElement().firstChild) m.getElement().firstChild.classList.remove("is-active");
    });
  });

  // The map re-measures when its container changes size (sidebar collapse, tab bar layout, window).
  window.addEventListener("load", function () { map.invalidateSize(); });
  window.addEventListener("resize", function () { map.invalidateSize(); });
  document.addEventListener("themechange", function () { draw(current); });
})();
