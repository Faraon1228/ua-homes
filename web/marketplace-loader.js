(function () {
  if (document.documentElement.classList.contains("seller-page")) return;
  let loaded = false;
  const sentinel = document.getElementById("marketplace-extensions-sentinel");
  const loadExtensions = () => {
    if (loaded) return;
    loaded = true;
    sentinel?.remove();
    const script = document.createElement("script");
    script.src = "marketplace-extensions.js?v=ua-marketplace-extensions-03-20260813";
    script.async = true;
    script.crossOrigin = "anonymous";
    script.addEventListener("load", () => {
      const status = document.getElementById("marketplace-extensions-status");
      if (status) status.textContent = "Додаткові сервіси завантажено.";
    }, { once: true });
    document.body.appendChild(script);
  };

  const observeExtensions = () => {
    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        loadExtensions();
      }, { rootMargin: "800px 0px" });
      observer.observe(sentinel);
    } else {
      window.addEventListener("scroll", loadExtensions, { once: true, passive: true });
    }
  };
  window.addEventListener("uah:catalog-settled", () => {
    window.requestAnimationFrame(() => window.requestAnimationFrame(observeExtensions));
  }, { once: true });
})();
