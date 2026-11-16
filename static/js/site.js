// Small progressive enhancements shared by every page. Pages work without this file.
(function () {
  "use strict";
  var root = document.documentElement;
  var t = window.I18N ? window.I18N.t : function (s) { return s; };
  function store(key, value) {                                   // storage may be blocked: never fail because of it
    try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (e) { return null; }
    return null;
  }

  // ── Theme: light by default; the choice is remembered in this browser. Pages that draw with theme
  // colours (maps, charts) listen for "themechange". ───────────────────────────────────────────────
  var themeButton = document.getElementById("theme-toggle");
  function labelTheme() {
    if (!themeButton) return;
    var text = t(root.getAttribute("data-theme") === "dark" ? "Switch to light mode" : "Switch to dark mode");
    themeButton.setAttribute("aria-label", text);
    themeButton.title = text;
  }
  if (themeButton) {
    labelTheme();
    themeButton.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.classList.add("theme-fade");
      root.setAttribute("data-theme", next);
      root.setAttribute("data-bs-theme", next);
      store("si.theme", next);
      labelTheme();
      document.dispatchEvent(new Event("themechange"));
      setTimeout(function () { root.classList.remove("theme-fade"); }, 300);
    });
  }

  // ── Navigation: a drop-down panel on small screens ───────────────────────────────────────────────
  var navButton = document.getElementById("nav-toggle");
  function setNav(open) {
    root.classList.toggle("nav-open", open);
    if (navButton) navButton.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (navButton) navButton.addEventListener("click", function () { setNav(!root.classList.contains("nav-open")); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setNav(false); });
  document.addEventListener("click", function (e) {
    if (root.classList.contains("nav-open") && !e.target.closest(".site-header")) setNav(false);
  });

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
    // While a date is being typed the value is incomplete, so the end date is only corrected once the
    // field is committed ("change"); "input" just refreshes the trip length.
    function refresh() {
      var a = parse(start.value), b = parse(end.value);
      if (a && b && b >= a) sync();
    }
    start.addEventListener("change", sync); end.addEventListener("change", sync);
    start.addEventListener("input", refresh); end.addEventListener("input", refresh);
    sync();
    if (box.hasAttribute("data-calendar")) buildCalendar(box, start, end, max);
  });

  // ── Range calendar (trip planner): pick the first and the last day by clicking. The two date fields
  // stay in the form (hidden) and carry the values, so everything else works as before; without
  // JavaScript the plain date fields are shown instead. ─────────────────────────────────────────────
  function buildCalendar(box, start, end, max) {
    var DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    var SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    function parse(v) { var d = v ? new Date(v + "T00:00:00") : null; return d && !isNaN(d) ? d : null; }
    function iso(d) { return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); }
    function addDays(d, n) { var x = new Date(d); x.setDate(x.getDate() + n); return x; }
    function nice(d) { return t(DAYS[(d.getDay() + 6) % 7]) + ", " + d.getDate() + " " + t(SHORT[d.getMonth()]) + " " + d.getFullYear(); }

    var today = new Date(); today.setHours(0, 0, 0, 0);
    var first = parse(start.value) || today;
    var view = new Date(first.getFullYear(), first.getMonth(), 1);
    var awaitingEnd = false;                      // true after the first click of a new range

    start.type = "hidden"; end.type = "hidden";
    box.classList.add("has-calendar");
    var cal = el("div", "cal col-12");
    var pills = el("div", "cal-pills");
    var pillStart = el("button", "cal-pill"); pillStart.type = "button";
    var pillEnd = el("button", "cal-pill"); pillEnd.type = "button";
    pills.appendChild(pillStart); pills.appendChild(el("i", "bi bi-arrow-right")); pills.appendChild(pillEnd);
    var hint = el("p", "cal-hint");
    var head = el("div", "cal-nav");
    var prev = el("button", "icon-btn"); prev.type = "button"; prev.setAttribute("aria-label", t("Previous month")); prev.appendChild(el("i", "bi bi-chevron-left"));
    var next = el("button", "icon-btn"); next.type = "button"; next.setAttribute("aria-label", t("Next month")); next.appendChild(el("i", "bi bi-chevron-right"));
    var todayBtn = el("button", "btn btn-sm btn-ghost", t("Today")); todayBtn.type = "button";
    head.appendChild(prev); head.appendChild(todayBtn); head.appendChild(next);
    var months = el("div", "cal-months");
    cal.appendChild(pills); cal.appendChild(hint); cal.appendChild(head); cal.appendChild(months);
    box.insertBefore(cal, box.firstChild);

    function commit() {                            // tell the rest of the form (trip length, brief)
      start.dispatchEvent(new Event("change", { bubbles: true }));
      end.dispatchEvent(new Event("change", { bubbles: true }));
    }
    function paint(hover) {
      var a = parse(start.value), b = awaitingEnd ? (hover && a && hover >= a ? hover : a) : parse(end.value);
      var limit = a && awaitingEnd ? addDays(a, max - 1) : null;
      months.querySelectorAll("button[data-date]").forEach(function (btn) {
        var d = parse(btn.dataset.date);
        btn.classList.toggle("is-start", !!a && +d === +a);
        btn.classList.toggle("is-end", !!b && +d === +b);
        btn.classList.toggle("in-range", !!a && !!b && d > a && d < b);
        btn.classList.toggle("is-preview", awaitingEnd);
        btn.disabled = !!limit && d > limit;
        btn.setAttribute("aria-pressed", (a && +d === +a) || (b && +d === +b) ? "true" : "false");
      });
      pillStart.innerHTML = ""; pillEnd.innerHTML = "";
      pillStart.appendChild(el("small", "", t("Start date"))); pillStart.appendChild(el("strong", "", a ? nice(a) : "—"));
      pillEnd.appendChild(el("small", "", t("End date")));
      pillEnd.appendChild(el("strong", "", awaitingEnd ? t("Pick the last day") : (parse(end.value) ? nice(parse(end.value)) : "—")));
      pillStart.classList.toggle("is-active", !awaitingEnd);
      pillEnd.classList.toggle("is-active", awaitingEnd);
      hint.textContent = awaitingEnd ? t("Now click the last day of your trip (the same day again for a one-day trip).")
                                     : t("Click a day to choose a new first day, then click the last day.");
    }
    function month(base) {
      var box = el("div", "cal-month");
      box.appendChild(el("div", "cal-title", t(MONTHS[base.getMonth()]) + " " + base.getFullYear()));
      var grid = el("div", "cal-grid");
      DAYS.forEach(function (d, i) { grid.appendChild(el("span", "cal-dow" + (i > 4 ? " is-weekend" : ""), t(d))); });
      var offset = (base.getDay() + 6) % 7;        // weeks start on Monday
      for (var i = 0; i < offset; i++) grid.appendChild(el("span", "cal-blank"));
      var count = new Date(base.getFullYear(), base.getMonth() + 1, 0).getDate();
      for (var n = 1; n <= count; n++) {
        var d = new Date(base.getFullYear(), base.getMonth(), n);
        var btn = el("button", "cal-day" + (+d === +today ? " is-today" : "") + (d < today ? " is-past" : ""), String(n));
        btn.type = "button";
        btn.dataset.date = iso(d);
        btn.setAttribute("aria-label", nice(d));
        grid.appendChild(btn);
      }
      box.appendChild(grid);
      return box;
    }
    function render() {
      months.innerHTML = "";
      months.appendChild(month(view));
      months.appendChild(month(new Date(view.getFullYear(), view.getMonth() + 1, 1)));
      paint(null);
    }
    months.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-date]");
      if (!btn || btn.disabled) return;
      var d = parse(btn.dataset.date), a = parse(start.value);
      if (awaitingEnd && a && d >= a) { end.value = btn.dataset.date; awaitingEnd = false; }
      else { start.value = btn.dataset.date; end.value = btn.dataset.date; awaitingEnd = true; }   // always a valid range
      commit();
      paint(null);
    });
    months.addEventListener("mouseover", function (e) {
      var btn = e.target.closest("button[data-date]");
      if (awaitingEnd && btn && !btn.disabled) paint(parse(btn.dataset.date));
    });
    months.addEventListener("mouseleave", function () { if (awaitingEnd) paint(null); });
    prev.addEventListener("click", function () { view = new Date(view.getFullYear(), view.getMonth() - 1, 1); render(); });
    next.addEventListener("click", function () { view = new Date(view.getFullYear(), view.getMonth() + 1, 1); render(); });
    todayBtn.addEventListener("click", function () { view = new Date(today.getFullYear(), today.getMonth(), 1); render(); });
    pillStart.addEventListener("click", function () { awaitingEnd = false; paint(null); });
    pillEnd.addEventListener("click", function () { if (parse(start.value)) { awaitingEnd = true; paint(null); } });
    render();
  }

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
})();
