// Trip form enhancements: per-city start points and exclusion list, plus a live summary.
// The server validates everything again; this script only makes the form nicer to use.
(function () {
  "use strict";

  var form = document.getElementById("trip-form");
  if (!form) return;
  var options = JSON.parse(document.getElementById("city-options").textContent);
  var citySelect = form.elements.city;
  var startSelect = form.elements.start;
  var excludeList = document.getElementById("exclude-list");
  var WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function option(value, label) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = label;
    return o;
  }

  function rebuildForCity() {
    var city = options[citySelect.value];
    if (!city) return;
    startSelect.innerHTML = "";
    var starts = document.createElement("optgroup");
    starts.label = "Hotels and stations";
    city.starts.forEach(function (p) { starts.appendChild(option(p.slug, p.name)); });
    var sights = document.createElement("optgroup");
    sights.label = "Or an attraction";
    city.attractions.forEach(function (a) { sights.appendChild(option(a.slug, a.name)); });
    startSelect.appendChild(starts);
    startSelect.appendChild(sights);

    excludeList.innerHTML = "";
    city.attractions.forEach(function (a) {
      var wrap = document.createElement("div");
      wrap.className = "form-check";
      var input = document.createElement("input");
      input.className = "form-check-input";
      input.type = "checkbox";
      input.name = "exclude";
      input.value = a.slug;
      input.id = "ex-" + a.slug;
      var label = document.createElement("label");
      label.className = "form-check-label d-flex justify-content-between gap-2";
      label.htmlFor = input.id;
      var name = document.createElement("span");
      name.textContent = a.name;
      var meta = document.createElement("span");
      meta.className = "text-muted small";
      meta.textContent = (a.visit >= 60 ? Math.floor(a.visit / 60) + " h " + (a.visit % 60 ? a.visit % 60 + " min" : "") : a.visit + " min").trim() +
        " · " + (a.fee === 0 ? "Free" : "₹" + a.fee);
      label.appendChild(name);
      label.appendChild(meta);
      wrap.appendChild(input);
      wrap.appendChild(label);
      excludeList.appendChild(wrap);
    });
  }

  function fmtDate(d) { return WEEKDAYS[d.getDay()] + " " + d.getDate() + " " + MONTHS[d.getMonth()]; }

  function updateSummary() {
    var set = function (key, text) {
      var el = document.querySelector('[data-summary="' + key + '"]');
      if (el) el.textContent = text;
    };
    var city = options[citySelect.value];
    var start = startSelect.options[startSelect.selectedIndex];
    set("city", (city ? city.name : "—") + (start ? " · from " + start.textContent : ""));

    var days = parseInt((form.querySelector("input[name=days]:checked") || {}).value || "1", 10);
    var first = form.elements.start_date.value ? new Date(form.elements.start_date.value + "T00:00:00") : null;
    if (first && !isNaN(first)) {
      var last = new Date(first);
      last.setDate(first.getDate() + days - 1);
      set("dates", days + (days > 1 ? " days · " + fmtDate(first) + " – " + fmtDate(last) : " day · " + fmtDate(first)));
    }
    set("hours", (form.elements.day_start.value || "--:--") + " – " + (form.elements.day_end.value || "--:--"));
    var budget = form.elements.budget.value;
    set("budget", budget ? "₹" + Number(budget).toLocaleString("en-IN") + " per day" +
        (form.elements.transport.checked ? " incl. transport" : " (entry fees)") : "No limit");
    var pace = form.querySelector("input[name=pace]:checked");
    var interests = Array.prototype.map.call(form.querySelectorAll("input[name=interests]:checked"), function (i) {
      return i.nextElementSibling.textContent.trim();
    });
    set("style", (pace ? pace.nextElementSibling.querySelector("strong").textContent : "Balanced") + " pace" +
        (interests.length ? " · " + interests.join(", ") : ""));
  }

  citySelect.addEventListener("change", function () { rebuildForCity(); updateSummary(); });
  form.addEventListener("input", updateSummary);
  form.addEventListener("change", updateSummary);
  updateSummary();
})();
