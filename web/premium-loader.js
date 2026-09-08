(function () {
  let loadPromise = null;
  const premiumStub = {
    open: (...args) => loadPremium()
      .then(() => window.uaPremium.open(...args))
      .catch(() => {
        window.location.href = "premium.html";
      }),
  };
  window.uaPremium = premiumStub;

  function loadPremium() {
    if (loadPromise) return loadPromise;
    loadPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "premium.js?v=ua-premium-08-payment-hardening-20260813";
      script.async = true;
      script.onload = resolve;
      script.onerror = () => {
        loadPromise = null;
        reject(new Error("Не вдалося завантажити тарифи"));
      };
      document.body.appendChild(script);
    });
    return loadPromise;
  }

  const paymentParams = new URLSearchParams(window.location.search);
  if (paymentParams.get("payment") === "return" && paymentParams.get("order_id")) {
    loadPremium().catch(() => {});
  }

  window.addEventListener("uah:meaningful-interaction", (event) => {
    const detail = event.detail;
    loadPremium().then(() => {
      window.dispatchEvent(new CustomEvent("uah:meaningful-interaction", { detail }));
    }).catch(() => {});
  }, { once: true });
  const loadPremiumAfterScroll = () => {
    if (window.scrollY < Math.max(320, window.innerHeight * 0.55)) return;
    window.removeEventListener("scroll", loadPremiumAfterScroll);
    loadPremium().catch(() => {});
  };
  window.addEventListener("scroll", loadPremiumAfterScroll, { passive: true });
})();
