// Overview: the destination network map (Leaflet + OpenStreetMap tiles, themed in CSS).
// Every marker is a destination from the database, coloured by how much of it can be planned.
(function () {
  "use strict";
  var el = document.getElementById("net-map");
  if (!el || !window.L) return;
  var points, texts;
  try {
    points = JSON.parse(document.getElementById("city-points").textContent);
    texts = JSON.parse(document.getElementById("overview-texts").textContent);
  } catch (e) { return; }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }

  var map = L.map(el, { scrollWheelZoom: false, zoomControl: true, attributionControl: true, minZoom: 3, maxZoom: 12, zoomSnap: 0.25 });
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, tiles &copy; <a href="https://www.esri.com/">Esri</a>'
  }).addTo(map);

  var bounds = [];
  points.forEach(function (c) {
    bounds.push([c.lat, c.lng]);
    var marker = L.marker([c.lat, c.lng], {
      icon: L.divIcon({ className: "", html: '<div class="city-dot is-' + esc(c.status) + '"></div>', iconSize: [12, 12], iconAnchor: [6, 6] }),
      title: c.name, keyboard: true, riseOnHover: true
    }).addTo(map);
    var html = "<strong>" + esc(c.name) + "</strong><br><span style='color:var(--muted)'>" + esc(c.state) + " · " + c.n + " " + esc(texts.attractions) +
      "</span><br><span style='font-size:.76rem;color:" + (c.status === "ready" ? "var(--accent-2)" : c.status === "limited" ? "var(--amber)" : "var(--faint)") + "'>" +
      esc(texts[c.status] || "") + "</span><div style='margin-top:8px;display:flex;gap:10px'>" +
      (c.status !== "not_ready" ? "<a href='" + esc(c.plan) + "'>" + esc(texts.plan) + " →</a>" : "") +
      "<a href='" + esc(c.explore) + "'>" + esc(texts.explore) + "</a></div>";
    marker.bindPopup(html, { closeButton: false, offset: [0, -2] });
    marker.on("mouseover", function () { marker.openPopup(); });
  });
  function fit() { if (bounds.length) map.fitBounds(L.latLngBounds(bounds).pad(0.06)); }
  fit();
  window.addEventListener("load", function () { map.invalidateSize(); fit(); });
})();
