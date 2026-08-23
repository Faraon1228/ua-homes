(function () {
  let requested = false;

  function loadApplication() {
    if (requested) return;
    requested = true;
    const script = document.createElement("script");
    script.type = "module";
    script.src = sellerPage
      ? "/seller-app.js?v=perf-cab0858f6144"
      : "/real-estate-app.js?v=perf-cab0858f6144";
    script.onerror = function () {
      const root = document.getElementById("root");
      if (!root) return;
      root.innerHTML =
        '<p role="alert" style="margin:24px;padding:16px;border-radius:16px;background:#fff1f2;color:#be123c;font-weight:700">Не вдалося завантажити каталог. Перевірте з’єднання та оновіть сторінку.</p>';
    };
    document.head.appendChild(script);
  }

  const sellerPage =
    /^\/seller\/?$/.test(window.location.pathname) ||
    new URLSearchParams(window.location.search).get("seller") === "1";
  const hero = sellerPage
    ? null
    : document.querySelector('[data-role="homepage-hero"]');
  const supportsLcp =
    hero &&
    "PerformanceObserver" in window &&
    PerformanceObserver.supportedEntryTypes?.includes(
      "largest-contentful-paint",
    );

  if (!supportsLcp) {
    window.requestAnimationFrame(loadApplication);
    return;
  }

  const observer = new PerformanceObserver((list) => {
    const heroPainted = list.getEntries().some((entry) => {
      const element = entry.element;
      return !element || element === hero || hero.contains(element);
    });
    if (!heroPainted) return;
    observer.disconnect();
    window.setTimeout(loadApplication, 0);
  });
  observer.observe({ type: "largest-contentful-paint", buffered: true });
  window.setTimeout(() => {
    observer.disconnect();
    loadApplication();
  }, 350);
})();
