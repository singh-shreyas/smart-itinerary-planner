// Small progressive enhancements shared by every page. Pages work without this file.
(function () {
  "use strict";

  // Transparent navigation over the home hero becomes solid once the page scrolls.
  var nav = document.getElementById("site-nav");
  if (nav && nav.classList.contains("is-transparent")) {
    var update = function () { nav.classList.toggle("scrolled", window.scrollY > 24); };
    update();
    window.addEventListener("scroll", update, { passive: true });
    var menu = document.getElementById("nav-links");
    if (menu) {
      menu.addEventListener("show.bs.collapse", function () { nav.classList.add("menu-open"); });
      menu.addEventListener("hidden.bs.collapse", function () { nav.classList.remove("menu-open"); });
    }
  }

  // Forms that generate a plan show a spinner while the server works.
  document.querySelectorAll("form[data-loading]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var button = form.querySelector("button[type=submit]");
      if (!button) return;
      button.disabled = true;
      button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>' +
        (form.dataset.loading || "Working…");
    });
  });
  // Re-enable buttons if the user navigates back to a cached page.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    document.querySelectorAll("form[data-loading] button[type=submit]").forEach(function (b) {
      b.disabled = false;
      if (b.dataset.label) b.innerHTML = b.dataset.label;
    });
  });
  document.querySelectorAll("form[data-loading] button[type=submit]").forEach(function (b) { b.dataset.label = b.innerHTML; });
})();
