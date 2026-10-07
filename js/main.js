(function () {
  var navbar = document.getElementById("navbar");
  var toggle = navbar.querySelector(".navbar__toggle");
  var links = navbar.querySelector(".navbar__links");

  function onScroll() {
    navbar.classList.toggle("is-scrolled", window.scrollY > 10);
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  toggle.addEventListener("click", function () {
    var open = links.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });

  links.querySelectorAll("a").forEach(function (link) {
    link.addEventListener("click", function () {
      links.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
    });
  });

  var banner = document.querySelector(".demo-banner");
  if (banner) {
    try {
      if (sessionStorage.getItem("demo-banner-hidden-v2") === "1") banner.hidden = true;
    } catch (err) {}
    banner.querySelector(".demo-banner__close").addEventListener("click", function () {
      banner.hidden = true;
      try {
        sessionStorage.setItem("demo-banner-hidden-v2", "1");
      } catch (err) {}
    });
  }
})();
