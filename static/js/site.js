// Small progressive enhancements shared by every page. Pages work without this file.
(function () {
  "use strict";
  var root = document.documentElement;
  var t = window.I18N ? window.I18N.t : function (s) { return s; };
  function store(key, value) {                                   // storage may be blocked: never fail because of it
    try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (e) { return null; }
    return null;
  }

  // ── Sidebar: collapsible rail on desktop, slide-in drawer on small screens ──────────────────────────
  var collapse = document.getElementById("sb-collapse");
  if (collapse) {
    collapse.addEventListener("click", function () {
      var collapsed = root.classList.toggle("sb-collapsed");
      store("si.sidebar", collapsed ? "collapsed" : "open");
      collapse.setAttribute("aria-pressed", collapsed ? "true" : "false");
      window.dispatchEvent(new Event("resize"));                 // maps re-measure their container
    });
  }
  var opener = document.querySelector("[data-sb-open]");
  function setDrawer(open) {
    root.classList.toggle("sb-open", open);
    if (opener) opener.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (opener) opener.addEventListener("click", function () { setDrawer(true); });
  document.querySelectorAll("[data-sb-close]").forEach(function (el) { el.addEventListener("click", function () { setDrawer(false); }); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && root.classList.contains("sb-open")) setDrawer(false); });

  // ── Recent itineraries (this browser only). An itinerary URL fully reproduces its plan, so storing the
  // URL with a short description is enough; nothing is sent anywhere. ────────────────────────────────────
  var RECENT_KEY = "si.recentTrips";
  function recentTrips() {
    try { var list = JSON.parse(store(RECENT_KEY) || "[]"); return Array.isArray(list) ? list : []; } catch (e) { return []; }
  }
  var record = document.getElementById("trip-record");
  if (record) {
    try {
      var trip = JSON.parse(record.textContent);
      var list = recentTrips().filter(function (x) { return x.url !== trip.url; });
      list.unshift(trip);
      store(RECENT_KEY, JSON.stringify(list.slice(0, 8)));
    } catch (e) { /* ignore a malformed record */ }
  }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  document.querySelectorAll("[data-recent-list]").forEach(function (box) {
    var trips = recentTrips().slice(0, parseInt(box.dataset.limit || "6", 10));
    if (!trips.length) return;                                   // keep the server-rendered empty state
    box.innerHTML = "";
    var current = location.pathname + location.search;
    trips.forEach(function (x) {
      var sub = [x.dates, x.mode].filter(Boolean).join(" · ");
      if (box.dataset.recentList === "sidebar") {
        var a = el("a", "sb-link" + (x.url === current ? " active" : ""));
        a.href = x.url;
        a.title = x.title;
        a.appendChild(el("i", "bi bi-signpost-2"));
        var span = el("span", "", x.title);
        span.appendChild(el("small", "", sub));
        a.appendChild(span);
        box.appendChild(a);
      } else {
        var li = el("li");
        var link = el("a", "recent-item");
        link.href = x.url;
        var thumb = el("span", "recent-thumb");
        if (x.image) { var img = el("img"); img.src = x.image; img.alt = ""; img.loading = "lazy"; img.onerror = function () { img.remove(); }; thumb.appendChild(img); }
        else thumb.appendChild(el("i", "bi bi-signpost-2"));
        var text = el("div");
        text.appendChild(el("strong", "", x.title));
        text.appendChild(el("small", "", [sub, x.stops ? x.stops + " " + t("stops") : ""].filter(Boolean).join(" · ")));
        link.appendChild(thumb);
        link.appendChild(text);
        link.appendChild(el("i", "bi bi-chevron-right"));
        li.appendChild(link);
        box.appendChild(li);
      }
    });
    var empty = document.querySelector('[data-recent-empty="' + box.dataset.recentList + '"]');
    if (empty) empty.hidden = true;
  });

  // ── Forms that generate a plan: spinner on the pressed button and a thin progress bar ───────────────
  document.querySelectorAll("form[data-loading]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var button = event.submitter && event.submitter.matches("button") ? event.submitter : form.querySelector("button[type=submit]");
      document.body.classList.add("is-loading");
      if (!button) return;
      button.disabled = true;
      button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>' +
        (button.dataset.loading || form.dataset.loading || "Working…");
    });
  });
  // Links that start a computation (mode / strategy switches, quick starts) show the progress bar too.
  document.querySelectorAll("a[data-loading-link]").forEach(function (a) {
    a.addEventListener("click", function (e) { if (!e.metaKey && !e.ctrlKey && !e.shiftKey) document.body.classList.add("is-loading"); });
  });
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    document.body.classList.remove("is-loading");
    document.querySelectorAll("form[data-loading] button[type=submit]").forEach(function (b) {
      b.disabled = false;
      if (b.dataset.label) b.innerHTML = b.dataset.label;
    });
  });
  document.querySelectorAll("form[data-loading] button[type=submit]").forEach(function (b) { b.dataset.label = b.innerHTML; });

  // ── Start / end date pairs: keep the end on or after the start and show the trip length
  // (both dates included: 1 Oct - 5 Oct = 5 days). The server checks the same rules again. ───────────────
  document.querySelectorAll("[data-date-range]").forEach(function (box) {
    var start = box.querySelector("[data-range-start]");
    var end = box.querySelector("[data-range-end]");
    var out = box.querySelector("[data-range-output]");
    var max = parseInt(box.dataset.maxDays || "30", 10);
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
    ["change", "input"].forEach(function (ev) { start.addEventListener(ev, sync); end.addEventListener(ev, sync); });
    sync();
  });

  // ── "Load more" listings (Destinations, Attractions). The server renders every card in ranking order,
  // so the page is complete without JavaScript; only the first PAGE matching cards are shown here. ──────
  window.Pager = function (grid, itemSelector, box, size) {
    size = size || 12;
    var button = box.querySelector("button");
    var status = box.querySelector("[data-pager-status]");
    var limit = size;
    function matching() {
      return Array.prototype.filter.call(grid.querySelectorAll(itemSelector), function (node) { return !node.hidden; });
    }
    function render() {
      var items = matching();
      grid.querySelectorAll(itemSelector).forEach(function (node) { node.classList.remove("is-paged-out"); });
      items.forEach(function (node, i) { node.classList.toggle("is-paged-out", i >= limit); });
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
      if (first) {
        var target = first.querySelector("a, button, [tabindex]");
        if (target) target.focus({ preventScroll: false });
      }
    });
    render();
    return { reset: function () { limit = size; render(); }, render: render };
  };

  // ── Section tabs: a long page of sections becomes one section at a time, with a tab bar built from the
  // sections' own titles. Without JavaScript every section stays visible. The URL hash selects a tab. ──
  document.querySelectorAll("[data-section-tabs]").forEach(function (wrap) {
    var sections = Array.prototype.slice.call(wrap.querySelectorAll(":scope > [data-tab-label]"));
    if (sections.length < 2) return;
    var bar = el("div", "tabs");
    bar.setAttribute("role", "tablist");
    var holder = document.querySelector('[data-section-tabbar="' + wrap.id + '"]') || wrap.parentNode.insertBefore(el("div", "section-tabbar"), wrap);
    holder.appendChild(bar);
    var buttons = sections.map(function (section, i) {
      var b = el("button", "tab");
      b.type = "button";
      b.setAttribute("role", "tab");
      b.id = "tab-" + section.id;
      b.setAttribute("aria-controls", section.id);
      if (section.dataset.tabIcon) b.appendChild(el("i", "bi " + section.dataset.tabIcon));
      b.appendChild(el("span", "", section.dataset.tabLabel));
      section.setAttribute("role", "tabpanel");
      section.setAttribute("aria-labelledby", b.id);
      b.addEventListener("click", function () { show(i, true); });
      bar.appendChild(b);
      return b;
    });
    function show(i, push) {
      sections.forEach(function (s, j) { s.classList.toggle("is-active", i === j); });
      buttons.forEach(function (b, j) { b.classList.toggle("active", i === j); b.setAttribute("aria-selected", i === j ? "true" : "false"); b.tabIndex = i === j ? 0 : -1; });
      if (push) history.replaceState(null, "", "#" + sections[i].id);
      window.dispatchEvent(new Event("resize"));                 // charts and maps size themselves to the new tab
    }
    bar.addEventListener("keydown", function (e) {
      var i = buttons.indexOf(document.activeElement);
      if (i < 0) return;
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        var next = (i + (e.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
        buttons[next].focus(); show(next, true); e.preventDefault();
      }
    });
    var start = sections.findIndex(function (s) { return "#" + s.id === location.hash; });
    show(start >= 0 ? start : 0, false);
  });

  // ── Section tracking for in-page navigation (planner brief, Methodology contents) ────────────────────
  document.querySelectorAll("[data-scrollspy]").forEach(function (box) {
    var links = Array.prototype.filter.call(box.querySelectorAll('a[href^="#"]'), function (a) {
      return a.getAttribute("href").length > 1 && document.getElementById(a.getAttribute("href").slice(1));
    });
    if (!links.length) return;
    var pending = false;
    function mark() {
      pending = false;
      var line = 110, current = links[0];
      links.forEach(function (a) {
        if (document.getElementById(a.getAttribute("href").slice(1)).getBoundingClientRect().top <= line) current = a;
      });
      var href = current.getAttribute("href");
      links.forEach(function (a) { a.classList.toggle("is-current", a.getAttribute("href") === href); });
    }
    window.addEventListener("scroll", function () { if (!pending) { pending = true; requestAnimationFrame(mark); } }, { passive: true });
    mark();
  });

  // ── Language: the server renders every page in the chosen language (cookie), so switching reloads the
  // same page. On the trip planner the current form values travel along, so nothing typed is lost. ────
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
