// Attractions page: live search / filter / sort on the cards the server already rendered,
// plus the details dialog. Without JavaScript the same forms submit and the server filters.
(function () {
  "use strict";

  // Choosing a destination loads that city's page (the form also works with its "Show" button).
  document.querySelectorAll("select[data-autosubmit]").forEach(function (select) {
    select.addEventListener("change", function () { select.form.submit(); });
  });

  var form = document.getElementById("filter-form");
  var grid = document.getElementById("attraction-grid");
  if (!form || !grid) return;

  var cols = Array.prototype.slice.call(grid.querySelectorAll(".attraction-col"));
  var count = document.getElementById("result-count");
  var empty = document.getElementById("empty-state");
  var data = JSON.parse(document.getElementById("attraction-data").textContent);

  var sorters = {
    popular: function (a, b) { return b.dataset.popularity - a.dataset.popularity || a.dataset.id - b.dataset.id; },
    rating: function (a, b) { return b.dataset.rating - a.dataset.rating || b.dataset.popularity - a.dataset.popularity || a.dataset.id - b.dataset.id; },
    duration: function (a, b) { return a.dataset.duration - b.dataset.duration || a.dataset.id - b.dataset.id; },
    fee: function (a, b) { return a.dataset.fee - b.dataset.fee || a.dataset.id - b.dataset.id; },
    name: function (a, b) { return a.dataset.name.localeCompare(b.dataset.name); }
  };

  function apply() {
    var q = form.q.value.trim().toLowerCase();
    var day = form.open_on.value;
    var category = form.category.value;
    var shown = 0;

    cols.forEach(function (col) {
      var ok = (!q || col.dataset.text.indexOf(q) !== -1) &&
               (!category || (" " + col.dataset.categories + " ").indexOf(" " + category + " ") !== -1) &&
               (!day || col.dataset.days.indexOf(day) !== -1);
      col.hidden = !ok;
      if (ok) shown++;
    });
    cols.sort(sorters[form.sort.value] || sorters.popular).forEach(function (col) { grid.appendChild(col); });
    count.textContent = shown;
    empty.classList.toggle("d-none", shown > 0);
    if (pager) pager.reset();

    // Keep the URL shareable: it reproduces the same filtered view.
    var params = new URLSearchParams(new FormData(form));
    Array.from(params.keys()).forEach(function (key) { if (!params.get(key)) params.delete(key); });
    if (params.get("sort") === "popular") params.delete("sort");
    var qs = params.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  var pager = window.Pager ? window.Pager(grid, ".attraction-col", document.querySelector('[data-pager="attraction-grid"]'), 12) : null;
  form.addEventListener("input", apply);
  form.addEventListener("change", apply);
  form.addEventListener("submit", function (e) { e.preventDefault(); apply(); });

  document.getElementById("clear-filters").addEventListener("click", function (e) {
    e.preventDefault();
    form.q.value = "";
    form.open_on.value = "";
    form.sort.value = "popular";
    form.category.value = "";
    apply();
  });

  function row(list, label, value) {
    var li = document.createElement("li");
    li.innerHTML = "<span></span><span></span>";
    li.children[0].textContent = label;
    li.children[1].textContent = value;
    list.appendChild(li);
  }

  // Details dialog: visitor information only, in reading order. Empty sections are hidden and values
  // that are typical estimates (not checked for this place) say so.
  var t = window.I18N ? window.I18N.t : function (x) { return x; };
  var modal = document.getElementById("attr-modal");
  modal.addEventListener("show.bs.offcanvas", function (event) {
    if (!event.relatedTarget) return;
    var item = data[event.relatedTarget.dataset.id];
    if (!item) return;
    var img = document.getElementById("attr-modal-img");
    var fallback = document.querySelector(".attr-modal-fallback");
    function noPhoto() { img.hidden = true; img.removeAttribute("src"); fallback.hidden = false; }
    img.onerror = noPhoto;
    if (item.image) { fallback.hidden = true; img.hidden = false; img.src = item.image; img.alt = item.name; } else { noPhoto(); }
    document.getElementById("attr-modal-title").textContent = item.name;
    document.getElementById("attr-modal-city").textContent = item.city;
    document.getElementById("attr-modal-desc").textContent = item.description || "";

    var chips = document.getElementById("attr-modal-chips");
    chips.innerHTML = "";
    item.categories.forEach(function (c) {
      var span = document.createElement("span");
      span.className = "chip chip-green";
      span.textContent = c;
      chips.appendChild(span);
    });
    document.getElementById("attr-modal-highlights-box").hidden = item.categories.length === 0;

    var facts = document.getElementById("attr-modal-facts");
    facts.innerHTML = "";
    row(facts, t("Recommended visit"), item.visit + (item.visit_estimated ? " (" + t("estimate") + ")" : ""));
    row(facts, t("Entry (Indian adult)"), item.fee + (item.fee_estimated ? " (" + t("estimate, please confirm") + ")" : ""));

    var hours = document.getElementById("attr-modal-hours");
    hours.innerHTML = "";
    item.hours.forEach(function (h) {
      var tr = document.createElement("tr");
      var day = document.createElement("td");
      day.className = "fw-semibold";
      day.textContent = h[0];
      var when = document.createElement("td");
      when.textContent = h[1];
      if (h[1] === "Closed") when.className = "text-accent fw-semibold";
      tr.appendChild(day);
      tr.appendChild(when);
      hours.appendChild(tr);
    });
    document.getElementById("attr-modal-hours-box").hidden = item.hours.length === 0;
    document.getElementById("attr-modal-hours-note").hidden = !item.hours_estimated;

    // Getting there: shown for every place that is not simply "by road".
    var access = document.getElementById("attr-modal-access");
    var info = item.access || {};
    var special = info.type && info.type !== "road";
    access.classList.toggle("d-none", !special);
    access.querySelector("p").textContent = special
      ? info.label + ". " + (info.note || "") + (info.timed ? "" : " " + t("How long this takes is not known, so the planner does not schedule it; check locally."))
      : "";
    var alts = access.querySelector("ul");
    alts.innerHTML = "";
    (info.alternatives || []).forEach(function (x) {
      var li = document.createElement("li");
      li.textContent = x.label + (x.from ? " " + t("from") + " " + x.from : "") + (x.minutes ? ", " + t("about {n} min").replace("{n}", x.minutes) : "") + " — " + x.status + ".";
      alts.appendChild(li);
    });

    var credit = document.getElementById("attr-modal-credit");
    credit.textContent = "";
    if (item.credit && item.image) {
      var a = document.createElement("a");
      a.href = item.credit_url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = t("Photo") + ": " + item.credit;
      credit.appendChild(a);
    }
    var link = document.getElementById("attr-modal-info");
    link.hidden = !item.info_url;
    if (item.info_url) link.href = item.info_url;
    document.getElementById("attr-modal-plan").href = item.plan_url;
  });
})();
