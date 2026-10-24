// Attractions page: live search / filter / sort on the cards the server already rendered,
// plus the details dialog. Without JavaScript the same form submits and the server filters.
(function () {
  "use strict";

  var form = document.getElementById("filter-form");
  var grid = document.getElementById("attraction-grid");
  if (!form || !grid) return;

  var cols = Array.prototype.slice.call(grid.querySelectorAll(".attraction-col"));
  var count = document.getElementById("result-count");
  var empty = document.getElementById("empty-state");
  var data = JSON.parse(document.getElementById("attraction-data").textContent);

  var sorters = {
    popular: function (a, b) { return b.dataset.popularity - a.dataset.popularity || a.dataset.id - b.dataset.id; },
    rating: function (a, b) { return b.dataset.rating - a.dataset.rating || a.dataset.id - b.dataset.id; },
    duration: function (a, b) { return a.dataset.duration - b.dataset.duration || a.dataset.id - b.dataset.id; },
    fee: function (a, b) { return a.dataset.fee - b.dataset.fee || a.dataset.id - b.dataset.id; },
    name: function (a, b) { return a.dataset.name.localeCompare(b.dataset.name); }
  };

  function apply() {
    var q = form.q.value.trim().toLowerCase();
    var day = form.open_on.value;
    var checked = form.querySelector("input[name=category]:checked");
    var category = checked ? checked.value : "";
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

    // Keep the URL shareable: it reproduces the same filtered view.
    var params = new URLSearchParams(new FormData(form));
    Array.from(params.keys()).forEach(function (key) { if (!params.get(key)) params.delete(key); });
    if (params.get("sort") === "popular") params.delete("sort");
    var qs = params.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  form.addEventListener("input", apply);
  form.addEventListener("change", apply);
  form.addEventListener("submit", function (e) { e.preventDefault(); apply(); });

  document.getElementById("clear-filters").addEventListener("click", function (e) {
    e.preventDefault();
    form.q.value = "";
    form.open_on.value = "";
    form.sort.value = "popular";
    document.getElementById("cat-all").checked = true;
    apply();
  });

  // Details dialog
  var modal = document.getElementById("attr-modal");
  modal.addEventListener("show.bs.modal", function (event) {
    var item = data[event.relatedTarget.dataset.id];
    if (!item) return;
    var img = document.getElementById("attr-modal-img");
    img.src = item.image || img.getAttribute("src");
    img.alt = item.name;
    document.getElementById("attr-modal-title").textContent = item.name;
    document.getElementById("attr-modal-city").textContent = item.city;
    document.getElementById("attr-modal-rating").innerHTML = '<i class="bi bi-star-fill" aria-hidden="true"></i>' + item.rating.toFixed(1);
    document.getElementById("attr-modal-desc").textContent = item.description;

    var chips = document.getElementById("attr-modal-chips");
    chips.innerHTML = "";
    item.categories.forEach(function (c) {
      var span = document.createElement("span");
      span.className = "chip chip-green";
      span.textContent = c;
      chips.appendChild(span);
    });
    if (item.catalog) {
      var tag = document.createElement("span");
      tag.className = "chip";
      tag.textContent = "From our catalog";
      chips.appendChild(tag);
    }

    var hours = document.getElementById("attr-modal-hours");
    hours.innerHTML = "";
    item.hours.forEach(function (row) {
      var tr = document.createElement("tr");
      var th = document.createElement("td");
      th.className = "fw-semibold";
      th.textContent = row[0];
      var td = document.createElement("td");
      td.textContent = row[1];
      if (row[1] === "Closed") td.className = "text-accent fw-semibold";
      tr.appendChild(th);
      tr.appendChild(td);
      hours.appendChild(tr);
    });

    var facts = document.getElementById("attr-modal-facts");
    facts.innerHTML = "";
    [["Visit duration", item.visit], ["Entry fee (Indian adult)", item.fee], ["Popularity", item.popularity + " / 100"]]
      .forEach(function (f) {
        var li = document.createElement("li");
        li.innerHTML = "<span></span><span></span>";
        li.children[0].textContent = f[0];
        li.children[1].textContent = f[1];
        facts.appendChild(li);
      });
    document.getElementById("attr-modal-status").textContent =
      "Data status: " + item.status + ". Hours, fee, rating and duration are estimates for this project.";
    var credit = document.getElementById("attr-modal-credit");
    credit.textContent = "";
    if (item.credit) {
      var a = document.createElement("a");
      a.href = item.credit_url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "Photo: " + item.credit;
      credit.appendChild(a);
    }
    var info = document.getElementById("attr-modal-info");
    info.hidden = !item.info_url;
    if (item.info_url) info.href = item.info_url;
    document.getElementById("attr-modal-plan").href = item.plan_url;
  });
})();
