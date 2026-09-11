(function () {
  const catalogKey = "uaDim.catalogEntry";
  const returnKey = "uaDim.listingReturn";
  const pendingKey = "uaDim.pendingListing";
  const catalogPaths = new Set(["/", "/app", "/app/", "/real-estate-demo.html", "/smart-search.html"]);
  const currentUrl = () => location.pathname + location.search + location.hash;
  const isCatalog = (url) => url.origin === location.origin && catalogPaths.has(url.pathname) && url.searchParams.get("seller") !== "1";
  const isListing = (url) => url.origin === location.origin && /^\/listing\/\d+$/.test(url.pathname);
  const writeState = (key, value) => history.replaceState({ ...history.state, [key]: value }, "");

  function storage(action, value) {
    try {
      if (action === "write") sessionStorage.setItem(pendingKey, JSON.stringify(value));
      if (action === "clear") sessionStorage.removeItem(pendingKey);
      if (action === "read") return JSON.parse(sessionStorage.getItem(pendingKey) || "null");
    } catch (error) {
      console.warn("UA-Dim: не вдалося зберегти перехід до оголошення", error);
    }
    return null;
  }

  function validReturn(value) {
    if (!value || typeof value.url !== "string" || !Number.isInteger(value.steps) || value.steps < 1) return null;
    try {
      return isCatalog(new URL(value.url, location.origin)) ? value : null;
    } catch {
      return null;
    }
  }

  function listingLink(event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
    const link = event.target.closest?.("a[href]");
    if (!link || link.hasAttribute("download") || (link.target && link.target !== "_self")) return null;
    return isListing(new URL(link.href)) ? link : null;
  }

  function rememberTransition(link, returnTo) {
    storage("write", {
      destination: link.href,
      source: location.href.split("#")[0],
      returnTo,
      createdAt: Date.now(),
    });
  }

  function readCatalog() {
    const entry = history.state?.[catalogKey];
    return isCatalog(new URL(location.href)) && entry?.url === currentUrl() ? entry : null;
  }

  function restorePosition(entry) {
    if (!entry) return;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const links = [...document.querySelectorAll('a[href]')];
      const target = links.filter((link) => link.getAttribute("href") === entry.focusHref)[entry.focusIndex];
      (target || document.getElementById("results"))?.focus({ preventScroll: true });
      window.scrollTo({ left: entry.x, top: entry.y, behavior: "instant" });
    }));
  }

  function bindCatalog(getSnapshot) {
    const save = (link) => {
      const previous = readCatalog();
      const focusHref = link?.getAttribute("href") || previous?.focusHref;
      const entry = {
        ...getSnapshot(),
        url: currentUrl(),
        x: scrollX,
        y: scrollY,
        focusHref,
        focusIndex: link
          ? [...document.querySelectorAll("a[href]")].filter((item) => item.getAttribute("href") === focusHref).indexOf(link)
          : previous?.focusIndex,
      };
      writeState(catalogKey, entry);
      return entry;
    };
    const onClick = (event) => {
      const link = listingLink(event);
      if (!link) return;
      const entry = save(link);
      rememberTransition(link, { url: entry.url, steps: 1 });
    };
    const onPageHide = () => save();
    const onPageShow = (event) => {
      storage("clear");
      if (event.persisted) restorePosition(readCatalog());
    };
    storage("clear");
    document.addEventListener("click", onClick);
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      document.removeEventListener("click", onClick);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("pageshow", onPageShow);
    };
  }

  function installListing() {
    const button = document.getElementById("listing-back");
    if (!button) return;
    const navigationType = performance.getEntriesByType("navigation")[0]?.type;
    let returnTo = ["reload", "back_forward"].includes(navigationType)
      ? validReturn(history.state?.[returnKey])
      : null;
    const pending = storage("read");
    storage("clear");
    if (!returnTo && pending && pending.destination === location.href &&
        pending.source === document.referrer.split("#")[0] &&
        Date.now() - pending.createdAt < 30000 &&
        navigationType === "navigate" &&
        history.length > 1) {
      returnTo = validReturn(pending.returnTo);
    }
    if (returnTo || history.state?.[returnKey]) writeState(returnKey, returnTo);

    window.uaListingBack = () => {
      const target = validReturn(history.state?.[returnKey]);
      if (target && history.length > target.steps) history.go(-target.steps);
      else location.replace(button.dataset.catalogUrl);
      return true;
    };
    button.addEventListener("click", window.uaListingBack);
    document.addEventListener("click", (event) => {
      const link = listingLink(event);
      const target = validReturn(history.state?.[returnKey]);
      if (link && target) rememberTransition(link, { ...target, steps: target.steps + 1 });
    });
    // Fragment entries are real history entries too (e.g. the contact link).
    window.addEventListener("popstate", () => {
      const target = validReturn(history.state?.[returnKey]);
      if (!target && returnTo && location.hash) {
        returnTo = { ...returnTo, steps: returnTo.steps + 1 };
        writeState(returnKey, returnTo);
      } else {
        returnTo = target;
      }
    });
  }

  window.uaListingNavigation = { readCatalog, restorePosition, bindCatalog };
  installListing();
})();
