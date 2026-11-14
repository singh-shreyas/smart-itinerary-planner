// Small progressive enhancements shared by every page. Pages work without this file.
(function () {
  "use strict";

  // The sticky navigation gains a hairline and soft shadow once the page scrolls. A transparent variant
  // (over a full-bleed photo) becomes solid at the same point.
  var nav = document.getElementById("site-nav");
  if (nav) {
    var update = function () { nav.classList.toggle("scrolled", window.scrollY > 8); };
    update();
    window.addEventListener("scroll", update, { passive: true });
    var menu = document.getElementById("nav-links");
    if (menu) {
      menu.addEventListener("show.bs.collapse", function () { nav.classList.add("menu-open"); });
      menu.addEventListener("hidden.bs.collapse", function () { nav.classList.remove("menu-open"); });
    }
  }

  // Forms that generate a plan show a spinner on the button that was pressed (a form can have several,
  // e.g. "Generate" and "Compare") and a thin progress bar at the top of the page while the server works.
  document.querySelectorAll("form[data-loading]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var button = event.submitter && event.submitter.matches("button") ? event.submitter : form.querySelector("button[type=submit]");
      document.body.classList.add("is-loading");
      if (!button) return;
      button.disabled = true;
      button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>' +
        (button.dataset.loading || form.dataset.loading || "Working…");
    });
  });
  // Re-enable buttons if the user navigates back to a cached page.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    document.body.classList.remove("is-loading");
    document.querySelectorAll("form[data-loading] button[type=submit]").forEach(function (b) {
      b.disabled = false;
      if (b.dataset.label) b.innerHTML = b.dataset.label;
    });
  });
  document.querySelectorAll("form[data-loading] button[type=submit]").forEach(function (b) { b.dataset.label = b.innerHTML; });

  // Start / end date pairs: keep the end on or after the start and show the trip length
  // (both dates included: 1 Oct - 5 Oct = 5 days). The server checks the same rules again.
  document.querySelectorAll("[data-date-range]").forEach(function (box) {
    var start = box.querySelector("[data-range-start]");
    var end = box.querySelector("[data-range-end]");
    var out = box.querySelector("[data-range-output]");
    var max = parseInt(box.dataset.maxDays || "30", 10);
    var t = window.I18N ? window.I18N.t : function (s) { return s; };
    function parse(v) { var d = v ? new Date(v + "T00:00:00") : null; return d && !isNaN(d) ? d : null; }
    function sync() {
      var a = parse(start.value), b = parse(end.value);
      if (a) end.min = start.value;
      if (a && b && b < a) end.value = start.value;
      b = parse(end.value);
      if (!a || !b) { out.textContent = ""; return; }
      var days = Math.round((b - a) / 86400000) + 1;
      out.classList.toggle("is-invalid-range", days > max);
      out.textContent = days > max
        ? t("Trips can be up to {max} days long; this one is {n} days.").replace("{max}", max).replace("{n}", days)
        : (days === 1 ? t("1 day (start and end dates included)") : t("{n} days (start and end dates included)").replace("{n}", days));
    }
    start.addEventListener("change", sync);
    end.addEventListener("change", sync);
    start.addEventListener("input", sync);
    end.addEventListener("input", sync);
    sync();
  });

  // "Load more" listings (Destinations, Attractions). The server renders every card in ranking order,
  // so the page is complete without JavaScript; here only the first PAGE matching cards are shown and
  // each click reveals PAGE more. A filter or sort change calls reset() and starts again from 12.
  window.Pager = function (grid, itemSelector, box, size) {
    size = size || 12;
    var button = box.querySelector("button");
    var status = box.querySelector("[data-pager-status]");
    var t = window.I18N ? window.I18N.t : function (x) { return x; };
    var limit = size;
    function matching() {
      return Array.prototype.filter.call(grid.querySelectorAll(itemSelector), function (el) { return !el.hidden; });
    }
    function render() {
      var items = matching();
      grid.querySelectorAll(itemSelector).forEach(function (el) { el.classList.remove("is-paged-out"); });
      items.forEach(function (el, i) { el.classList.toggle("is-paged-out", i >= limit); });
      var shown = Math.min(limit, items.length), left = items.length - shown;
      box.hidden = items.length === 0;
      button.hidden = left <= 0;
      button.querySelector("span").textContent = t("Load more") + (left > 0 ? " (" + Math.min(size, left) + ")" : "");
      status.textContent = t("Showing {shown} of {total}").replace("{shown}", shown).replace("{total}", items.length);
    }
    button.addEventListener("click", function () {
      var first = matching()[limit];
      limit += size;
      render();
      if (first) {                                           // move focus to the first newly shown card
        var target = first.querySelector("a, button, [tabindex]");
        if (target) target.focus({ preventScroll: false });
      }
    });
    render();
    return { reset: function () { limit = size; render(); }, render: render };
  };

  // Section tracking for in-page navigation (the planner's trip summary, the About page contents):
  // the link of the section currently in view gets "is-current". Purely visual; links work without it.
  document.querySelectorAll("[data-scrollspy]").forEach(function (box) {
    var links = Array.prototype.filter.call(box.querySelectorAll('a[href^="#"]'), function (a) {
      return a.getAttribute("href").length > 1 && document.getElementById(a.getAttribute("href").slice(1));
    });
    if (!links.length) return;
    var pending = false;
    function mark() {
      pending = false;
      var line = (nav ? nav.offsetHeight : 0) + 40, current = links[0];
      links.forEach(function (a) {                       // the last section whose top has passed the line
        if (document.getElementById(a.getAttribute("href").slice(1)).getBoundingClientRect().top <= line) current = a;
      });
      var href = current.getAttribute("href");          // several rows may point at one section
      links.forEach(function (a) { a.classList.toggle("is-current", a.getAttribute("href") === href); });
    }
    window.addEventListener("scroll", function () { if (!pending) { pending = true; requestAnimationFrame(mark); } }, { passive: true });
    mark();
  });

  // Light / dark theme: switches instantly, remembered in this browser. If storage is blocked the
  // switch still works for this page (the site simply opens in light mode next time).
  var toggle = document.getElementById("theme-toggle");
  function applyTheme(theme) {
    var root = document.documentElement;
    root.setAttribute("data-theme", theme);
    root.setAttribute("data-bs-theme", theme);
    if (toggle) {
      var dark = theme === "dark";
      var label = dark ? toggle.dataset.labelLight : toggle.dataset.labelDark;
      toggle.setAttribute("aria-pressed", dark ? "true" : "false");
      toggle.setAttribute("aria-label", label);
      toggle.title = label;
    }
    document.dispatchEvent(new CustomEvent("themechange", { detail: { theme: theme } }));
  }
  if (toggle) {
    applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");
    toggle.addEventListener("click", function () {
      var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      try { localStorage.setItem("theme", next); } catch (e) {}
      applyTheme(next);
    });
  }

  // Language: the server renders every page in the chosen language (cookie), so switching reloads the
  // same page. On the trip planner the current form values travel along, so nothing typed is lost.
  var langSelect = document.querySelector("[data-lang-switch]");
  if (langSelect) {
    langSelect.addEventListener("change", function () {
      var next = location.pathname + location.search;
      var form = document.getElementById("trip-form");
      if (form) {
        var params = new URLSearchParams();
        new FormData(form).forEach(function (value, key) { if (value !== "") params.append(key, value); });
        next = location.pathname + "?" + params.toString();
      }
      location.href = "/lang/" + encodeURIComponent(langSelect.value) + "?next=" + encodeURIComponent(next + location.hash);
    });
  }
})();
