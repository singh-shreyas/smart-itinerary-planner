// Trip form enhancements: per-city stay areas, nearby cities (pairwise distance rule),
// the "pick your places" list, the exclusion list and a live summary. The server validates everything again; this script
// only makes the form nicer to use. Without JavaScript the form still works.
(function () {
  "use strict";

  var form = document.getElementById("trip-form");
  if (!form) return;
  var options = JSON.parse(document.getElementById("city-options").textContent);
  var citySelect = form.elements.city;
  var startSelect = form.elements.start;
  var excludeList = document.getElementById("exclude-list");
  var pickList = document.getElementById("pick-list");
  var pickBox = document.getElementById("pick-box");
  var pickCount = document.getElementById("pick-count");
  var stayNote = document.getElementById("stay-note");
  var MAX_PICKED = 25;
  var STAY_HINT = "Five neighbourhoods, one in each part of the city, from OpenStreetMap.";
  var nearbyList = document.getElementById("nearby-list");
  var nearbyNote = document.getElementById("nearby-note");
  var readinessNote = document.querySelector("[data-readiness]");
  var MAX_EXTRA = 3;
  var WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function option(value, label) {
    var o = el("option", "", label);
    o.value = value;
    return o;
  }
  function duration(min) {
    var h = Math.floor(min / 60), m = min % 60;
    return h ? (h + " hr" + (m ? " " + m + " min" : "")) : m + " min";
  }
  function selectedExtras() {
    return Array.prototype.map.call(nearbyList.querySelectorAll("input[name=also]:checked"), function (i) { return i.value; });
  }

  // Can `slug` join the group? Every pair must be within the limit: it must appear in the
  // nearby list of every city already chosen (and of the base city).
  function conflict(slug, chosen) {
    for (var i = 0; i < chosen.length; i++) {
      if (chosen[i] === slug) continue;
      var near = options[chosen[i]] ? options[chosen[i]].nearby : [];
      if (!near.some(function (n) { return n.slug === slug; })) return options[chosen[i]].name;
    }
    return null;
  }

  function refreshNearby() {
    var base = citySelect.value;
    var chosen = selectedExtras();
    var notes = [];
    nearbyList.querySelectorAll("input[name=also]").forEach(function (input) {
      var other = conflict(input.value, chosen);
      var full = !input.checked && chosen.length >= MAX_EXTRA;
      input.disabled = !input.checked && (other !== null || full);
      var item = input.closest(".nearby-item");
      item.classList.toggle("is-disabled", input.disabled);
      if (input.disabled && other) notes.push(options[input.value].name + " is more than 100 km from " + other + ".");
    });
    if (chosen.length >= MAX_EXTRA) notes.push("You can add at most " + MAX_EXTRA + " nearby cities.");
    var limited = chosen.filter(function (s) { return options[s].readiness.status !== "ready"; })
      .map(function (s) { return options[s].name + " has limited data"; });
    nearbyNote.textContent = notes.concat(limited).join(" ");
    if (base) { rebuildExclusions(); rebuildPicks(); }
  }

  function rebuildNearby() {
    var city = options[citySelect.value];
    nearbyList.innerHTML = "";
    if (!city || !city.nearby.length) {
      nearbyList.appendChild(el("p", "small text-muted mb-0", "No other destination is within 100 km of " + (city ? city.name : "this city") + "."));
      nearbyNote.textContent = "";
      return;
    }
    city.nearby.forEach(function (n) {
      var label = el("label", "nearby-item");
      var input = el("input", "form-check-input");
      input.type = "checkbox";
      input.name = "also";
      input.value = n.slug;
      var text = el("span");
      text.appendChild(el("strong", "", n.name));
      text.appendChild(el("small", "", Math.round(n.km) + " km straight line" + (n.road_km ? " · " + Math.round(n.road_km) + " km by road" : "")));
      label.appendChild(input);
      label.appendChild(text);
      nearbyList.appendChild(label);
    });
    refreshNearby();
  }

  function rebuildExclusions() {
    var slugs = [citySelect.value].concat(selectedExtras());
    var checked = {};
    excludeList.querySelectorAll("input[name=exclude]:checked").forEach(function (i) { checked[i.value] = true; });
    excludeList.innerHTML = "";
    slugs.forEach(function (slug) {
      var city = options[slug];
      if (!city) return;
      if (slugs.length > 1) excludeList.appendChild(el("div", "exclude-heading", city.name));
      city.attractions.forEach(function (a) {
        var wrap = el("div", "form-check");
        var input = el("input", "form-check-input");
        input.type = "checkbox";
        input.name = "exclude";
        input.value = a.slug;
        input.id = "ex-" + a.slug;
        input.checked = !!checked[a.slug];
        var label = el("label", "form-check-label d-flex justify-content-between gap-2");
        label.htmlFor = input.id;
        label.appendChild(el("span", "", a.name + (a.access ? " (" + a.access.toLowerCase() + ")" : "")));
        label.appendChild(el("span", "text-muted small", duration(a.visit)));
        wrap.appendChild(input);
        wrap.appendChild(label);
        excludeList.appendChild(wrap);
      });
    });
  }

  // The places you pick: base city and any nearby cities. Places whose access cannot be timed are shown,
  // disabled, so you can see they exist but are not planned with guessed times.
  function rebuildPicks() {
    if (!pickList) return;
    var slugs = [citySelect.value].concat(selectedExtras());
    var checked = {};
    pickList.querySelectorAll("input[name=places]:checked").forEach(function (i) { checked[i.value] = true; });
    pickList.innerHTML = "";
    slugs.forEach(function (slug) {
      var city = options[slug];
      if (!city) return;
      if (slugs.length > 1) pickList.appendChild(el("div", "exclude-heading", city.name));
      city.attractions.forEach(function (a) {
        var wrap = el("div", "form-check");
        var input = el("input", "form-check-input");
        input.type = "checkbox";
        input.name = "places";
        input.value = a.slug;
        input.id = "pk-" + a.slug;
        input.checked = !!checked[a.slug] && a.timed;
        input.disabled = !a.timed;
        var label = el("label", "form-check-label d-flex justify-content-between gap-2");
        label.htmlFor = input.id;
        var name = el("span", "", a.name + " ");
        if (a.access) name.appendChild(el("span", "chip chip-xs" + (a.timed ? "" : " chip-warning"), a.access + (a.timed ? "" : " · not timed")));
        label.appendChild(name);
        label.appendChild(el("span", "text-muted small", duration(a.visit)));
        wrap.appendChild(input);
        wrap.appendChild(label);
        pickList.appendChild(wrap);
      });
    });
    refreshPicks();
  }

  function refreshPicks() {
    if (!pickList) return;
    var picking = (form.querySelector("input[name=choose]:checked") || {}).value === "pick";
    pickBox.classList.toggle("d-none", !picking);
    var help = document.getElementById("choose-help");
    help.textContent = picking ? help.dataset.pick : help.dataset.auto;
    pickList.querySelectorAll("input[name=places]").forEach(function (i) { i.disabled = !picking || !options_timed(i.value); });
    var n = pickList.querySelectorAll("input[name=places]:checked").length;
    pickCount.textContent = n;
    pickList.querySelectorAll("input[name=places]:not(:checked)").forEach(function (i) {
      if (n >= MAX_PICKED) i.disabled = true;
    });
  }

  function options_timed(slug) {
    for (var c in options) {
      var hit = options[c].attractions.find(function (a) { return a.slug === slug; });
      if (hit) return hit.timed;
    }
    return false;
  }

  // Stay areas belong to one city: a new city replaces them all, so another city's area can never stay selected.
  function rebuildStays() {
    var city = options[citySelect.value];
    startSelect.innerHTML = "";
    city.stays.forEach(function (p) {
      var o = option(p.slug, p.label);
      o.dataset.note = p.note || "";
      startSelect.appendChild(o);
    });
    showStayNote();
  }

  function showStayNote() {
    var o = startSelect.options[startSelect.selectedIndex];
    stayNote.textContent = o && o.dataset.note ? "* " + o.dataset.note : STAY_HINT;
  }

  function rebuildForCity() {
    var city = options[citySelect.value];
    if (!city) return;
    rebuildStays();
    if (readinessNote) {
      readinessNote.textContent = city.readiness.reachable + " of " + city.readiness.total +
        " attractions can be planned from here." + (city.readiness.status === "ready" ? "" : " Data for this city is limited.");
    }
    rebuildNearby();
    rebuildExclusions();
    rebuildPicks();
  }

  // Meal fields are only relevant when the meal is switched on.
  form.querySelectorAll("[data-toggles]").forEach(function (box) {
    var fields = document.getElementById(box.dataset.toggles);
    function sync() {
      fields.classList.toggle("is-off", !box.checked);
      fields.querySelectorAll("input, select").forEach(function (f) { f.disabled = !box.checked; });
    }
    box.addEventListener("change", sync);
    sync();
  });

  function fmtDate(d) { return WEEKDAYS[d.getDay()] + " " + d.getDate() + " " + MONTHS[d.getMonth()]; }

  function updateSummary() {
    var set = function (key, text) {
      var node = document.querySelector('[data-summary="' + key + '"]');
      if (node) node.textContent = text;
    };
    var city = options[citySelect.value];
    var names = [city ? city.name : "—"].concat(selectedExtras().map(function (s) { return options[s].name; }));
    var start = startSelect.options[startSelect.selectedIndex];
    set("city", names.join(" + ") + (start ? " · from " + start.textContent : ""));

    var days = parseInt((form.querySelector("input[name=days]:checked") || {}).value || "1", 10);
    var first = form.elements.start_date.value ? new Date(form.elements.start_date.value + "T00:00:00") : null;
    if (first && !isNaN(first)) {
      var last = new Date(first);
      last.setDate(first.getDate() + days - 1);
      set("dates", days + (days > 1 ? " days · " + fmtDate(first) + " – " + fmtDate(last) : " day · " + fmtDate(first)));
    }
    set("hours", (form.elements.day_start.value || "--:--") + " – " + (form.elements.day_end.value || "--:--"));
    var meals = ["lunch", "dinner"].filter(function (k) { return document.getElementById(k).checked; });
    set("meals", meals.length ? meals.map(function (k) { return k.charAt(0).toUpperCase() + k.slice(1); }).join(" and ") +
        " break" + (meals.length > 1 ? "s" : "") + (form.elements.veg.checked ? " · vegetarian places" : "") : "No meal breaks");
    var mode = form.querySelector("input[name=mode]:checked");
    var picking = (form.querySelector("input[name=choose]:checked") || {}).value === "pick";
    var picked = pickList ? pickList.querySelectorAll("input[name=places]:checked").length : 0;
    set("mode", (mode ? mode.nextElementSibling.querySelector("strong").textContent : "Suggested") +
        (picking ? " · " + picked + " place" + (picked === 1 ? "" : "s") + " picked" : " · planner chooses places"));
    var pace = form.querySelector("input[name=pace]:checked");
    var interests = Array.prototype.map.call(form.querySelectorAll("input[name=interests]:checked"), function (i) {
      return i.nextElementSibling.textContent.trim();
    });
    var only = (form.querySelector("input[name=interest_mode]:checked") || {}).value === "only";
    set("style", (pace ? pace.nextElementSibling.querySelector("strong").textContent : "Balanced") + " pace" +
        (interests.length ? " · " + (only ? "only " : "") + interests.slice(0, 4).join(", ") +
        (interests.length > 4 ? " +" + (interests.length - 4) : "") : ""));
  }

  citySelect.addEventListener("change", function () { rebuildForCity(); updateSummary(); });
  nearbyList.addEventListener("change", function (e) {
    if (e.target.name === "also") { refreshNearby(); updateSummary(); }
  });
  startSelect.addEventListener("change", showStayNote);
  form.addEventListener("change", function (e) {
    if (e.target.name === "choose" || e.target.name === "places") refreshPicks();
  });
  form.addEventListener("input", updateSummary);
  form.addEventListener("change", updateSummary);
  refreshNearby();
  refreshPicks();
  updateSummary();
})();
