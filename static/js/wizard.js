// Trip planner wizard: shows one step of the (single) trip form at a time. Purely presentational:
// every field stays in the same <form>, so "Generate" works from any step and the server validates
// everything as before. Without JavaScript all steps are shown one after another.
(function () {
  "use strict";
  var form = document.getElementById("trip-form");
  if (!form) return;
  var steps = Array.prototype.slice.call(form.querySelectorAll(".wiz-step"));
  var items = Array.prototype.slice.call(form.querySelectorAll(".stepper li"));
  var bar = document.getElementById("wizard-progress");
  var prev = form.querySelector('[data-wiz="prev"]');
  var next = form.querySelector('[data-wiz="next"]');
  var finish = form.querySelector("[data-wiz-generate]");
  var early = form.querySelector("[data-wiz-generate-secondary]");
  if (!steps.length) return;
  var current = 0, seen = {};

  function show(i, focus) {
    current = Math.max(0, Math.min(steps.length - 1, i));
    seen[current] = true;
    steps.forEach(function (s, j) { s.classList.toggle("is-active", j === current); });
    items.forEach(function (li, j) {
      li.classList.toggle("is-current", j === current);
      li.classList.toggle("is-done", j !== current && !!seen[j] && j < current);
      var b = li.querySelector("button");
      if (j === current) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
    });
    if (bar) bar.style.width = ((current + 1) / steps.length * 100) + "%";
    prev.disabled = current === 0;
    var last = current === steps.length - 1;
    next.hidden = last;
    finish.hidden = !last;
    early.hidden = last;
    document.querySelectorAll("#trip-summary a").forEach(function (a) {
      a.classList.toggle("is-current", a.getAttribute("href") === "#" + steps[current].id);
    });
    if (focus) {
      var h = steps[current].querySelector("h2");
      if (h) h.focus({ preventScroll: true });
      var top = form.getBoundingClientRect().top;
      if (top < 0 || top > window.innerHeight * 0.6) form.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
  function indexOf(id) {
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].id === id || steps[i].querySelector("#" + CSS.escape(id))) return i;
    }
    return -1;
  }

  prev.addEventListener("click", function () { show(current - 1, true); });
  next.addEventListener("click", function () { show(current + 1, true); });
  items.forEach(function (li, j) { li.querySelector("button").addEventListener("click", function () { show(j, true); }); });
  // Rows of the trip brief jump to their step instead of scrolling a long page.
  document.querySelectorAll('#trip-summary a[href^="#"], a[href^="#step-"]').forEach(function (a) {
    a.addEventListener("click", function (e) {
      var i = indexOf(a.getAttribute("href").slice(1));
      if (i >= 0) { e.preventDefault(); show(i, true); }
    });
  });

  // Steps holding a server-side error are marked, and the first of them opens.
  var firstError = -1;
  steps.forEach(function (s, j) {
    if (s.querySelector(".is-invalid, .invalid-feedback")) {
      items[j] && items[j].classList.add("has-error");
      if (firstError < 0) firstError = j;
    }
  });
  var fromHash = location.hash ? indexOf(location.hash.slice(1)) : -1;
  show(firstError >= 0 ? firstError : (fromHash >= 0 ? fromHash : 0), false);

  // The brief follows the chosen city (photo + name) and the selection strategy.
  var images = {};
  try { images = JSON.parse(document.getElementById("city-images").textContent); } catch (e) { /* no photos */ }
  var img = document.getElementById("brief-img");
  var cityName = document.getElementById("brief-city");
  var citySelect = form.elements.city;
  function syncCity() {
    var opt = citySelect.options[citySelect.selectedIndex];
    if (cityName && opt) cityName.textContent = opt.textContent.split(",")[0];
    var src = images[citySelect.value];
    if (img) {
      if (src) { img.hidden = false; img.style.opacity = 0; img.onload = function () { img.style.opacity = 1; }; img.src = src; }
      else img.hidden = true;
    }
  }
  citySelect.addEventListener("change", syncCity);
  var strategyOut = document.querySelector("[data-summary-strategy]");
  form.addEventListener("change", function (e) {
    if (e.target.name === "strategy" && strategyOut) {
      strategyOut.textContent = e.target.nextElementSibling.querySelector("strong").textContent;
    }
  });
})();
