// Trip form enhancements: per-city stay areas, nearby cities (pairwise distance rule),
// the "pick your places" list, the exclusion list and a live summary. The server validates everything again; this script
// only makes the form nicer to use. Without JavaScript the form still works.
(function () {
  "use strict";

  var form = document.getElementById("trip-form");
  if (!form) return;
  var options = JSON.parse(document.getElementById("city-options").textContent);
  var t = window.I18N ? window.I18N.t : function (x) { return x; };
  var citySelect = form.elements.city;
  var startSelect = form.elements.start;
  var excludeList = document.getElementById("exclude-list");
  var pickList = document.getElementById("pick-list");
  var pickBox = document.getElementById("pick-box");
  var pickCount = document.getElementById("pick-count");
  var stayNote = document.getElementById("stay-note");
  var endSelect = document.getElementById("end");
  var overnightBox = document.getElementById("overnight-box");
  var MAX_PICKED = 150;
  var pickAll = document.getElementById("pick-all");
  var pickFilter = document.getElementById("pick-filter");
  var STAY_HINT = t("Five neighbourhoods, one in each part of the city, from OpenStreetMap.");
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
      if (input.disabled && other) notes.push(t("{name} is more than 100 km from {other}.").replace("{name}", options[input.value].name).replace("{other}", other));
    });
    if (chosen.length >= MAX_EXTRA) notes.push(t("You can add at most {n} nearby cities.").replace("{n}", MAX_EXTRA));
    var limited = chosen.filter(function (s) { return options[s].readiness.status !== "ready"; })
      .map(function (s) { return t("{name} has limited data").replace("{name}", options[s].name); });
    nearbyNote.textContent = notes.concat(limited).join(" ");
    if (base) { rebuildExclusions(); rebuildPicks(); rebuildEnds(); }
  }

  // The last night can be in any of the trip's cities. Options of a city that left the trip disappear,
  // so a stay that is no longer part of the trip cannot stay selected.
  function rebuildEnds() {
    if (!endSelect) return;
    var keep = endSelect.value || endSelect.dataset.selected || "";
    var slugs = [citySelect.value].concat(selectedExtras());
    endSelect.innerHTML = "";
    endSelect.appendChild(option("", endSelect.dataset.same || "Same as the starting stay"));
    slugs.forEach(function (slug) {
      var city = options[slug];
      if (!city) return;
      var group = el("optgroup");
      group.label = city.name;
      city.stays.forEach(function (p) { group.appendChild(option(p.slug, p.label)); });
      endSelect.appendChild(group);
    });
    endSelect.value = Array.prototype.some.call(endSelect.options, function (o) { return o.value === keep; }) ? keep : "";
    endSelect.dataset.selected = endSelect.value;
    var multi = slugs.length > 1;
    overnightBox.classList.toggle("d-none", !multi);
    var base = multi && (form.querySelector("input[name=overnight]:checked") || {}).value === "base";
    endSelect.disabled = base;
    if (base) endSelect.value = "";
  }

  function rebuildNearby() {
    var city = options[citySelect.value];
    nearbyList.innerHTML = "";
    if (!city || !city.nearby.length) {
      nearbyList.appendChild(el("p", "small text-muted mb-0", t("No other destination is within 100 km of {city}.").replace("{city}", city ? city.name : "")));
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
      text.appendChild(el("small", "", Math.round(n.km) + " " + t("km straight line") + (n.road_km ? " · " + Math.round(n.road_km) + " " + t("km by road") : "")));
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
    // Keep the ticks of places that are still in the trip; places of a removed city are dropped.
    var checked = {};
    pickList.querySelectorAll("input[name=places]:checked").forEach(function (i) { checked[i.value] = true; });
    pickList.innerHTML = "";
    if (pickFilter) pickFilter.value = "";
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

  // The places "Select all" acts on: every timed place of the trip's cities that matches the filter.
  function eligible() {
    return Array.prototype.filter.call(pickList.querySelectorAll("input[name=places]"), function (i) {
      return options_timed(i.value) && !i.closest(".form-check").hidden;
    });
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
    document.getElementById("pick-count-label").textContent = n === 1 ? t("place selected") : t("places selected");
    pickList.querySelectorAll("input[name=places]:not(:checked)").forEach(function (i) {
      if (n >= MAX_PICKED) i.disabled = true;
    });
    if (pickAll) {
      var pool = eligible();
      var all = pool.length > 0 && pool.every(function (i) { return i.checked; });
      pickAll.dataset.state = all ? "clear" : "select";
      pickAll.querySelector("span").textContent = all
        ? t("Deselect all")
        : t("Select all ({n})").replace("{n}", pool.length);
      pickAll.disabled = !picking || pool.length === 0;
      pickAll.setAttribute("aria-pressed", all ? "true" : "false");
    }
  }

  if (pickAll) {
    pickAll.addEventListener("click", function () {
      var on = pickAll.dataset.state !== "clear";
      eligible().forEach(function (i) { i.checked = on; });
      refreshPicks();
      updateSummary();
    });
  }
  if (pickFilter) {
    pickFilter.addEventListener("input", function () {
      var q = pickFilter.value.trim().toLowerCase();
      pickList.querySelectorAll(".form-check").forEach(function (row) {
        row.hidden = q !== "" && row.textContent.toLowerCase().indexOf(q) === -1;
      });
      pickList.querySelectorAll(".exclude-heading").forEach(function (h) {
        var next = h.nextElementSibling, visible = false;
        while (next && !next.classList.contains("exclude-heading")) { if (!next.hidden) visible = true; next = next.nextElementSibling; }
        h.hidden = !visible;
      });
      refreshPicks();
    });
    // Enter in the filter must not submit the trip form.
    pickFilter.addEventListener("keydown", function (e) { if (e.key === "Enter") e.preventDefault(); });
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
      readinessNote.textContent = t("{n} of {total} attractions can be planned from here.").replace("{n}", city.readiness.reachable)
        .replace("{total}", city.readiness.total) + (city.readiness.status === "ready" ? "" : " " + t("Data for this city is limited."));
    }
    if (endSelect) endSelect.dataset.selected = "";
    rebuildNearby();
    rebuildExclusions();
    rebuildPicks();
    rebuildEnds();
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

  function fmtDate(d) { return t(WEEKDAYS[d.getDay()]) + " " + d.getDate() + " " + t(MONTHS[d.getMonth()]); }

  function updateSummary() {
    var set = function (key, text) {
      var node = document.querySelector('[data-summary="' + key + '"]');
      if (node) node.textContent = text;
    };
    var city = options[citySelect.value];
    var names = [city ? city.name : "—"].concat(selectedExtras().map(function (s) { return options[s].name; }));
    var start = startSelect.options[startSelect.selectedIndex];
    var endOpt = endSelect && endSelect.value ? endSelect.options[endSelect.selectedIndex] : null;
    set("city", names.join(" + ") + (start ? " · " + t("from") + " " + start.textContent : "") + (endOpt ? " · " + t("to") + " " + endOpt.textContent : ""));

    var first = form.elements.start_date.value ? new Date(form.elements.start_date.value + "T00:00:00") : null;
    var last = form.elements.end_date.value ? new Date(form.elements.end_date.value + "T00:00:00") : null;
    if (first && last && !isNaN(first) && !isNaN(last) && last >= first) {
      var days = Math.round((last - first) / 86400000) + 1;
      set("dates", (days > 1 ? t("{n} days").replace("{n}", days) + " · " + fmtDate(first) + " – " + fmtDate(last)
                             : t("{n} day").replace("{n}", days) + " · " + fmtDate(first)));
    }
    set("hours", (form.elements.day_start.value || "--:--") + " – " + (form.elements.day_end.value || "--:--"));
    var meals = ["lunch", "dinner"].filter(function (k) { return document.getElementById(k).checked; });
    var mealText = meals.length === 2 ? t("Lunch and dinner breaks") : meals.length ? t(meals[0] === "lunch" ? "Lunch break" : "Dinner break") : t("No meal breaks");
    set("meals", mealText + (meals.length && form.elements.veg.checked ? " · " + t("vegetarian places") : ""));
    var mode = form.querySelector("input[name=mode]:checked");
    var picking = (form.querySelector("input[name=choose]:checked") || {}).value === "pick";
    var picked = pickList ? pickList.querySelectorAll("input[name=places]:checked").length : 0;
    set("mode", (mode ? mode.nextElementSibling.querySelector("strong").textContent : "Suggested") +
        " · " + (picking ? t(picked === 1 ? "{n} place picked" : "{n} places picked").replace("{n}", picked) : t("planner chooses places")));
    var pace = form.querySelector("input[name=pace]:checked");
    var interests = Array.prototype.map.call(form.querySelectorAll("input[name=interests]:checked"), function (i) {
      return i.nextElementSibling.textContent.trim();
    });
    var only = (form.querySelector("input[name=interest_mode]:checked") || {}).value === "only";
    set("style", (pace ? pace.nextElementSibling.querySelector("strong").textContent : "Balanced") + " " + t("pace") +
        (interests.length ? " · " + (only ? t("only") + " " : "") + interests.slice(0, 4).join(", ") +
        (interests.length > 4 ? " +" + (interests.length - 4) : "") : ""));
  }

  citySelect.addEventListener("change", function () { rebuildForCity(); updateSummary(); });
  nearbyList.addEventListener("change", function (e) {
    if (e.target.name === "also") { refreshNearby(); updateSummary(); }
  });
  startSelect.addEventListener("change", showStayNote);
  if (endSelect) {
    endSelect.dataset.same = endSelect.options[0].textContent;
    endSelect.addEventListener("change", function () { endSelect.dataset.selected = endSelect.value; });
  }
  form.addEventListener("change", function (e) { if (e.target.name === "overnight") rebuildEnds(); });
  form.addEventListener("change", function (e) {
    if (e.target.name === "choose" || e.target.name === "places") refreshPicks();
  });
  form.addEventListener("input", updateSummary);
  form.addEventListener("change", updateSummary);
  refreshNearby();
  refreshPicks();
  updateSummary();
})();
