(() => {
  const SAVED_SEARCHES_KEY = "ua_homes_saved_searches_v1";
  const LEAD_SESSION_KEY = "uah.leadSessionId";
  const KEYWORD_SEARCH_KEY = "ua_homes_keyword_search_v1";
  const VERIFIED_AGENCY_FILTER_KEY = "ua_homes_verified_agency_only_v1";
  const DUPLICATE_RISK_FILTER_KEY = "ua_homes_duplicate_risk_filter_v1";
  const VIEW_MODE_KEY = "ua_homes_view_mode_v1";
  const LISTING_MODE_KEY = "ua_homes_listing_mode_v1";
  const MAX_SAVED_SEARCHES = 10;
  const UA_CENTERS_DATASET_URLS = ["/admin/ua-centers.json", "./admin/ua-centers.json"];
  let uaCentersDataset = null;
  let uaCentersDatasetPromise = null;

  const QUICK_SCENARIOS = [
    { label: "Київ · єОселя · до $130k", filters: { city: "Київ", onlyEOselya: true, maxPrice: "130000", minRooms: "1" } },
    { label: "Львів · 2+ кімнати · до $110k", filters: { city: "Львів", onlyEOselya: false, maxPrice: "110000", minRooms: "2" } },
    { label: "Київ · 1-2 кімнати · 35-65 м²", filters: { city: "Київ", onlyEOselya: false, minRooms: "1", maxRooms: "2", minArea: "35", maxArea: "65" } },
  ];

  const DISTRICT_HINTS = {
    Київ: ["Печерський", "Шевченківський", "Голосіївський", "Подільський", "Солом'янський", "Дарницький"],
    Львів: ["Франківський", "Сихівський", "Шевченківський", "Галицький", "Залізничний", "Личаківський"],
    Харків: ["Шевченківський", "Київський", "Салтівський", "Індустріальний", "Новобаварський", "Основ'янський"],
    Одеса: ["Приморський", "Київський", "Малиновський", "Суворовський", "Хаджибейський", "Пересипський"],
    Дніпро: ["Шевченківський", "Соборний", "Центральний", "Новокодацький", "Амур-Нижньодніпровський", "Індустріальний"],
  };

  const POPULAR_ROUTES = [
    { source: "popular_route:rent_kyiv_1k_700", label: "Оренда · Київ · 1к до $700", subtitle: "Швидко знайти стартове житло", filters: { listingMode: "rent", city: "Київ", propertyType: "квартира", maxPrice: "700", minRooms: "1", maxRooms: "1" } },
    { source: "popular_route:sale_kyiv_eoselya", label: "Продаж · Київ · єОселя", subtitle: "Готові об'єкти під програму", filters: { listingMode: "sale", city: "Київ", onlyEOselya: true, propertyType: "квартира" } },
    { source: "popular_route:newbuild_lviv_2plus", label: "Новобудови · Львів · 2+ кімнати", subtitle: "Сімейні варіанти з ростом ціни", filters: { listingMode: "sale", city: "Львів", propertyType: "квартира", minRooms: "2" } },
    { source: "popular_route:house_odessa_180k", label: "Будинки · Одеса · до $180k", subtitle: "Продаж будинків біля моря", filters: { listingMode: "sale", city: "Одеса", propertyType: "будинок", maxPrice: "180000" } },
    { source: "popular_route:commercial_dnipro_center", label: "Комерція · Дніпро · центр", subtitle: "Офіси і retail у щільному трафіку", filters: { listingMode: "sale", city: "Дніпро", propertyType: "комерція", district: "Центральний" } },
    { source: "popular_route:rent_kharkiv_area35", label: "Оренда · Харків · 35+ м²", subtitle: "Практичні варіанти з більшою площею", filters: { listingMode: "rent", city: "Харків", propertyType: "квартира", minArea: "35" } },
  ];

  const TRUSTED_PARTNERS = [
    { name: "Capital Alliance", kind: "Агентство", city: "Київ", specialization: "Преміум квартири та будинки", trustSignals: ["Перевірений контакт", "Робота за договором", "Підтверджені об'єкти"] },
    { name: "Lviv Home Experts", kind: "Агентство", city: "Львів", specialization: "Сімейні квартири + єОселя", trustSignals: ["Верифікований профіль", "Прозора комісія", "Швидкий показ"] },
    { name: "Dnipro Urban Group", kind: "Забудовник", city: "Дніпро", specialization: "Новобудови комфорт+ класу", trustSignals: ["Перевірений ЄДРПОУ", "Фото ходу будівництва", "Партнерські банки"] },
    { name: "Odesa Coast Build", kind: "Забудовник", city: "Одеса", specialization: "Будинки та апартаменти біля моря", trustSignals: ["Ліцензія верифікована", "Здані черги", "Публічні документи"] },
  ];

  const KEYWORD_SUGGESTIONS = [
    "ЖК",
    "метро",
    "центр",
    "з ремонтом",
    "тераса",
    "єОселя",
    "без комісії",
    "новобудова",
  ];

  function fireInput(el) {
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function ensureUaCentersDataset() {
    if (uaCentersDataset) return uaCentersDataset;
    if (uaCentersDatasetPromise) return uaCentersDatasetPromise;
    uaCentersDatasetPromise = (async () => {
      for (const candidate of UA_CENTERS_DATASET_URLS) {
        try {
          const response = await fetch(candidate, { credentials: "omit" });
          if (!response.ok) continue;
          const data = await response.json();
          if (Array.isArray(data?.regions) && data?.regionData && Array.isArray(data?.allCenters)) {
            uaCentersDataset = data;
            return uaCentersDataset;
          }
        } catch (_err) {}
      }
      uaCentersDataset = { regions: [], regionData: {}, allCenters: [] };
      return uaCentersDataset;
    })();
    return uaCentersDatasetPromise;
  }

  function sortUaNames(values) {
    return [...new Set((values || []).filter(Boolean))].sort((a, b) =>
      String(a).localeCompare(String(b), "uk", { sensitivity: "base" })
    );
  }

  function injectMarketplaceEffectsStyles() {
    if (document.getElementById("ua-marketplace-effects")) return;
    const style = document.createElement("style");
    style.id = "ua-marketplace-effects";
    style.textContent = `
      .market-card{transition:transform .2s ease,box-shadow .2s ease}
      .market-card:hover{transform:translateY(-4px)!important;box-shadow:0 18px 42px rgba(15,23,42,.14)!important}
      .market-card .gallery-img{transform:scale(1);transition:transform .25s ease,filter .35s ease,opacity .35s ease;filter:blur(8px);opacity:.86}
      .market-card .gallery-img.is-loaded{filter:blur(0);opacity:1}
      .market-card:hover .gallery-img.is-loaded{transform:scale(1.03)}
      .market-smart-panel{position:sticky;top:12px;z-index:25}
      .glass-badge{backdrop-filter:blur(8px);background:rgba(255,255,255,.72)!important;border:1px solid rgba(148,163,184,.35)!important}
      .tooltip-chip{position:relative;cursor:help}
      .tooltip-chip:hover::after{content:attr(data-tooltip);position:absolute;left:0;bottom:calc(100% + 6px);white-space:nowrap;background:rgba(15,23,42,.92);color:#fff;font-size:11px;line-height:1.2;padding:6px 8px;border-radius:8px;z-index:40}
      .map-shell-fade{transition:opacity .2s ease}
      .map-shell-fade.is-hidden{opacity:0;pointer-events:none}
      .map-skeleton{position:absolute;inset:0;z-index:20;display:grid;place-items:center;background:rgba(248,250,252,.92);backdrop-filter:blur(3px)}
      .map-skeleton .pulse{width:72%;max-width:360px;height:14px;border-radius:999px;background:linear-gradient(90deg,#e2e8f0 25%,#f8fafc 37%,#e2e8f0 63%);background-size:400% 100%;animation:uaShimmer 1.2s ease infinite}
      .empty-state-cta{border:1px dashed #cbd5e1;border-radius:24px;background:linear-gradient(180deg,#fff,#f8fafc)}
      .ua-pressable{transition:transform .16s ease,box-shadow .2s ease}
      .ua-pressable:active{transform:scale(.98)}
      .us-market-style{background:linear-gradient(180deg,#0b1220 0%,#101827 45%,#132238 100%)}
      .us-market-style header.sticky{background:rgba(15,23,42,.9)!important;border-bottom:1px solid rgba(100,116,139,.35)!important;box-shadow:0 10px 28px rgba(2,6,23,.45)}
      .us-market-style .us-hero-shell{background:linear-gradient(145deg,#111827 0%,#1f2937 52%,#1e3a5f 100%)!important;color:#e2e8f0!important;border:1px solid rgba(71,85,105,.65);box-shadow:0 30px 60px rgba(2,6,23,.45)}
      .us-market-style .us-hero-shell h1,
      .us-market-style .us-hero-shell h2,
      .us-market-style .us-hero-shell h3{color:#f1f5f9!important}
      .us-market-style .us-hero-shell p,
      .us-market-style .us-hero-shell .text-white,
      .us-market-style .us-hero-shell .text-slate-300,
      .us-market-style .us-hero-shell .text-slate-200{color:#cbd5e1!important}
      .us-market-style .us-hero-shell [class*="text-white"]{color:#e2e8f0!important}
      .us-market-style .us-hero-shell a{color:#93c5fd!important}
      .us-market-style .us-hero-shell .border-white\\/20{border-color:rgba(148,163,184,.4)!important}
      .us-market-style .us-hero-shell .bg-white\\/10{background:rgba(148,163,184,.16)!important}
      .us-market-style .us-hero-shell button,.us-market-style .us-hero-shell .inline-flex{background:rgba(30,41,59,.88)!important;border:1px solid rgba(100,116,139,.65)!important;color:#e2e8f0!important}
      .us-market-style .us-hero-shell button:hover{background:rgba(37,99,235,.22)!important;border-color:rgba(59,130,246,.5)!important}
      .us-market-style .us-filter-shell,.us-market-style .us-smart-shell,.us-market-style .us-map-shell,.us-market-style .us-results-shell{border:1px solid rgba(71,85,105,.55)!important;box-shadow:0 22px 46px rgba(2,6,23,.35)!important;border-radius:24px!important;background:linear-gradient(160deg,rgba(15,23,42,.88),rgba(17,24,39,.94))!important}
      .us-market-style .us-filter-shell *,.us-market-style .us-smart-shell *,.us-market-style .us-map-shell *,.us-market-style .us-results-shell *{color:#e2e8f0}
      .us-market-style .us-filter-shell select,.us-market-style .us-filter-shell input,.us-market-style .us-smart-shell select,.us-market-style .us-smart-shell input,.us-market-style .us-map-shell select{border-color:#475569!important;border-radius:12px!important;background:#0f172a!important;color:#e2e8f0!important}
      .us-market-style .us-smart-shell [data-role="clear-all-filters"],.us-market-style .us-smart-shell [data-role="apply-keyword-search"],.us-market-style .us-smart-shell [data-role="save-current-search"],.us-market-style .us-smart-shell [data-role="save-alert"]{border-radius:12px!important}
      .us-market-style .us-smart-shell [data-role="apply-keyword-search"],.us-market-style .us-smart-shell [data-role="save-current-search"]{background:#2563eb!important;color:#e0f2fe!important;border:1px solid rgba(59,130,246,.6)!important}
      .us-market-style .us-smart-shell [data-role="save-alert"]{background:#15803d!important;color:#dcfce7!important;border:1px solid rgba(34,197,94,.65)!important}
      .us-market-style .market-card{border-radius:22px!important;border:1px solid rgba(71,85,105,.58)!important;box-shadow:0 14px 30px rgba(2,6,23,.4)!important;background:linear-gradient(170deg,rgba(17,24,39,.96),rgba(30,41,59,.9))!important}
      .us-market-style .market-card:hover{box-shadow:0 28px 58px rgba(2,6,23,.56)!important}
      .us-market-style [data-role="map-first-mode"] .inline-flex{background:#1e293b!important;border-radius:12px!important}
      .us-market-style [data-role="mode-list"],.us-market-style [data-role="mode-map"]{border-radius:10px!important}
      @keyframes uaShimmer{0%{background-position:100% 50%}100%{background-position:0 50%}}
    `;
    document.head.appendChild(style);
  }

  function applyUsMarketplaceSkin() {
    document.body.classList.add("us-market-style");
    const hero = document.querySelector("main > section:first-of-type");
    const primaryFilters = document.querySelector("main > section:nth-of-type(2)");
    const smartPanel = document.querySelector(".market-smart-panel > div");
    const mapShell = document.querySelector('[data-role="map-first-mode"] > div');
    const resultsShell = document.querySelector("main > div.grid");
    if (hero) hero.classList.add("us-hero-shell");
    if (primaryFilters) primaryFilters.classList.add("us-filter-shell");
    if (smartPanel) smartPanel.classList.add("us-smart-shell");
    if (mapShell) mapShell.classList.add("us-map-shell");
    if (resultsShell) resultsShell.classList.add("us-results-shell");
  }

  function decorateListingCardsWithEffects() {
    const cards = document.querySelectorAll("article.group, .listing-card, article[data-listing-id]");
    cards.forEach((card) => {
      card.classList.add("market-card");
      card.querySelectorAll("img.gallery-img").forEach((img) => {
        if (img.complete) {
          img.classList.add("is-loaded");
        } else if (!img.dataset.uahLoaded) {
          img.dataset.uahLoaded = "1";
          img.addEventListener("load", () => img.classList.add("is-loaded"), { once: true });
        }
      });
      card.querySelectorAll("span").forEach((chip) => {
        const text = (chip.textContent || "").trim();
        if (!text) return;
        if (text.includes("єОселя") || text.includes("Власник підтверджено") || text.includes("Телефон підтверджено") || text.includes("Документи перевірено")) {
          chip.classList.add("glass-badge");
        }
        if (text.includes("TOP")) {
          chip.classList.add("glass-badge");
        }
      });
    });
  }

  function appendMissingCityOptions(citySelect, cities) {
    if (!citySelect || !Array.isArray(cities) || !cities.length) return;
    const existing = new Set([...citySelect.options].map((option) => option.value));
    sortUaNames(cities).forEach((city) => {
      if (!city || existing.has(city)) return;
      const option = document.createElement("option");
      option.value = city;
      option.textContent = city;
      citySelect.appendChild(option);
      existing.add(city);
    });
  }

  function resolveApiBase() {
    if (window.UA_HOMES_API) return window.UA_HOMES_API;
    const configured = "__UA_HOMES_API__";
    if (configured && configured !== "__UA_HOMES_API__") return configured;
    const host = window.location.hostname;
    if (!host || window.location.protocol === "file:") return "http://localhost:5050";
    if (host === "localhost" || host === "127.0.0.1") return "http://localhost:5050";
    if (!host.includes("192.168") && !/^\d+\.\d+/.test(host)) {
      return `https://${host.replace(/^www\./, "")}`.replace(/\/$/, "") + "/api-backend";
    }
    return `http://${host}:5050`;
  }

  function getLeadSessionId() {
    let sessionId = localStorage.getItem(LEAD_SESSION_KEY);
    if (!sessionId) {
      sessionId = `ls-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      localStorage.setItem(LEAD_SESSION_KEY, sessionId);
    }
    return sessionId;
  }

  function trackPopularRoute(route) {
    const payload = {
      event: "route_apply",
      intent: "popular_route_apply",
      source: route.source || "popular_route:unknown",
      listing_type: route.filters.propertyType || "",
      price: route.filters.maxPrice ? Number(route.filters.maxPrice) : null,
      session_id: getLeadSessionId(),
    };

    if (Array.isArray(window.dataLayer)) {
      window.dataLayer.push({
        event: "uah_popular_route_apply",
        source: payload.source,
        listing_type: payload.listing_type || null,
      });
    }

    const body = JSON.stringify(payload);
    const endpoint = `${resolveApiBase()}/api/analytics/lead-funnel`;
    fetch(endpoint, {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => {});
  }

  function installListingsSearchProxy() {
    if (window.__uaHomesListingsSearchProxyInstalled) return;
    const originalFetch = window.fetch.bind(window);
    window.fetch = function patchedFetch(input, init) {
      try {
        const keyword = (localStorage.getItem(KEYWORD_SEARCH_KEY) || "").trim();
        const rawUrl = typeof input === "string" ? input : input?.url;
        if (!rawUrl || !/\/api\/listings(\?|$)/.test(rawUrl)) {
          return originalFetch(input, init);
        }

        const parsed = new URL(rawUrl, window.location.href);
        if (keyword) {
          parsed.searchParams.set("search", keyword);
        }
        const currentSort = parsed.searchParams.get("sort");
        if (keyword && (!currentSort || currentSort === "newest" || currentSort === "price-desc")) {
          parsed.searchParams.set("sort", "relevance");
        }
        if (localStorage.getItem(VERIFIED_AGENCY_FILTER_KEY) === "1") {
          parsed.searchParams.set("verifiedAgency", "1");
        }
        const duplicateRisk = (localStorage.getItem(DUPLICATE_RISK_FILTER_KEY) || "all").trim();
        if (duplicateRisk === "low" || duplicateRisk === "medium" || duplicateRisk === "high") {
          parsed.searchParams.set("duplicateRisk", duplicateRisk);
        }

        if (typeof input === "string") {
          return originalFetch(parsed.toString(), init);
        }
        return originalFetch(new Request(parsed.toString(), input), init);
      } catch (_err) {
        return originalFetch(input, init);
      }
    };
    window.__uaHomesListingsSearchProxyInstalled = true;
  }

  function findFilters() {
    const citySelect = [...document.querySelectorAll("select")].find((select) =>
      [...select.options].some((option) => option.textContent.includes("Київ"))
    );
    const propertyTypeSelect = [...document.querySelectorAll("select")].find((select) =>
      [...select.options].some((option) => option.textContent.includes("Всі типи"))
    );
    const districtInput = [...document.querySelectorAll('input[type="text"]')].find((input) =>
      (input.placeholder || "").toLowerCase().includes("район")
    );
    const eoselyaCheckbox = document.querySelector("#eoselya") ||
      [...document.querySelectorAll('input[type="checkbox"]')].find((box) => {
        const label = box.id ? document.querySelector(`label[for="${box.id}"]`) : null;
        if ((label?.textContent || "").includes("єОселя")) return true;
        const rowText = box.closest("label,div")?.textContent || "";
        return rowText.includes("єОселя");
      });
    const numberInputs = [...document.querySelectorAll('input[type="number"]')];
    const listingModeButtons = {
      all: [...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "Всі"),
      sale: [...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "Продаж"),
      rent: [...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "Оренда"),
    };

    if (!citySelect || numberInputs.length < 6) return null;

    const [minPrice, maxPrice, minRooms, maxRooms, minArea, maxArea] = numberInputs;
    return {
      citySelect,
      propertyTypeSelect,
      districtInput,
      eoselyaCheckbox,
      minPrice,
      maxPrice,
      minRooms,
      maxRooms,
      minArea,
      maxArea,
      listingModeButtons,
    };
  }

  function setListingMode(mode, filters) {
    const target = filters.listingModeButtons?.[mode];
    if (target) target.click();
  }

  function readFilters(filters) {
    return {
      city: filters.citySelect.value || "Всі",
      district: filters.districtInput?.value || "",
      propertyType: filters.propertyTypeSelect?.value || "Всі типи",
      onlyEOselya: !!filters.eoselyaCheckbox?.checked,
      minPrice: filters.minPrice.value || "",
      maxPrice: filters.maxPrice.value || "",
      minRooms: filters.minRooms.value || "",
      maxRooms: filters.maxRooms.value || "",
      minArea: filters.minArea.value || "",
      maxArea: filters.maxArea.value || "",
    };
  }

  function applyFilters(values, filters) {
    if (typeof values.listingMode === "string") {
      setListingMode(values.listingMode, filters);
    }
    if (typeof values.city === "string") {
      filters.citySelect.value = values.city;
      fireInput(filters.citySelect);
    }
    if (typeof values.propertyType === "string" && filters.propertyTypeSelect) {
      filters.propertyTypeSelect.value = values.propertyType;
      fireInput(filters.propertyTypeSelect);
    }
    if (typeof values.district === "string" && filters.districtInput) {
      filters.districtInput.value = values.district;
      fireInput(filters.districtInput);
    }
    if (typeof values.onlyEOselya === "boolean" && filters.eoselyaCheckbox) {
      filters.eoselyaCheckbox.checked = values.onlyEOselya;
      fireInput(filters.eoselyaCheckbox);
    }
    [
      ["minPrice", filters.minPrice],
      ["maxPrice", filters.maxPrice],
      ["minRooms", filters.minRooms],
      ["maxRooms", filters.maxRooms],
      ["minArea", filters.minArea],
      ["maxArea", filters.maxArea],
    ].forEach(([key, input]) => {
      if (key in values) {
        input.value = values[key] ?? "";
        fireInput(input);
      }
    });
  }

  function getSavedSearches() {
    try {
      const raw = localStorage.getItem(SAVED_SEARCHES_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (_err) {
      return [];
    }
  }

  function setSavedSearches(list) {
    localStorage.setItem(SAVED_SEARCHES_KEY, JSON.stringify(list.slice(0, MAX_SAVED_SEARCHES)));
  }

  function districtHintsByCity(city) {
    if (!city || city === "Всі") {
      return Object.values(DISTRICT_HINTS).flat().slice(0, 8);
    }
    return DISTRICT_HINTS[city] || [];
  }

  function getFavoriteIds() {
    try {
      const raw = localStorage.getItem("re.favoriteIds");
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.filter((id) => Number.isFinite(Number(id))) : [];
    } catch (_err) {
      return [];
    }
  }

  function describeSearchState(values) {
    const parts = [];
    if (values.city && values.city !== "Всі") parts.push(values.city);
    if (values.district) parts.push(values.district);
    if (values.propertyType && values.propertyType !== "Всі типи") parts.push(values.propertyType);
    if (values.onlyEOselya) parts.push("єОселя");
    if (values.minRooms || values.maxRooms) {
      const rooms = `${values.minRooms || "1"}-${values.maxRooms || "∞"} кімн.`;
      parts.push(rooms);
    }
    if (values.minPrice || values.maxPrice) {
      const price = `$${values.minPrice || "0"}-${values.maxPrice || "∞"}`;
      parts.push(price);
    }
    if (values.minArea || values.maxArea) {
      const area = `${values.minArea || "0"}-${values.maxArea || "∞"} м²`;
      parts.push(area);
    }
    const keyword = (localStorage.getItem(KEYWORD_SEARCH_KEY) || "").trim();
    if (keyword) parts.push(`"${keyword}"`);
    return parts.length ? parts.join(" · ") : "Увімкніть фільтри або швидкий сценарій, щоб звузити пошук.";
  }

  function getListingMode(filters) {
    const cached = localStorage.getItem(LISTING_MODE_KEY);
    if (cached === "sale" || cached === "rent" || cached === "all") return cached;
    const saleBtn = filters?.listingModeButtons?.sale;
    const rentBtn = filters?.listingModeButtons?.rent;
    if (saleBtn?.className?.includes("bg-blue")) return "sale";
    if (rentBtn?.className?.includes("bg-blue")) return "rent";
    return "sale";
  }

  function trackListingMode(filters) {
    if (!filters?.listingModeButtons) return;
    Object.entries(filters.listingModeButtons).forEach(([mode, button]) => {
      if (!button) return;
      button.addEventListener("click", () => {
        localStorage.setItem(LISTING_MODE_KEY, mode);
      });
    });
  }

  function buildListingsApiUrl(filters, limit = 200) {
    const api = new URL(`${resolveApiBase()}/api/listings`, window.location.href);
    const values = readFilters(filters);
    api.searchParams.set("status", "published");
    api.searchParams.set("limit", String(limit));
    const mode = getListingMode(filters);
    if (mode === "sale" || mode === "rent") api.searchParams.set("listing_type", mode);
    if (values.city && values.city !== "Всі") api.searchParams.set("city", values.city);
    if (values.propertyType && values.propertyType !== "Всі типи") api.searchParams.set("type", values.propertyType);
    if (values.district) api.searchParams.set("district", values.district);
    if (values.minPrice) api.searchParams.set("minPrice", values.minPrice);
    if (values.maxPrice) api.searchParams.set("maxPrice", values.maxPrice);
    if (values.minRooms) api.searchParams.set("minRooms", values.minRooms);
    if (values.maxRooms) api.searchParams.set("maxRooms", values.maxRooms);
    if (values.minArea) api.searchParams.set("minArea", values.minArea);
    if (values.maxArea) api.searchParams.set("maxArea", values.maxArea);
    if (values.onlyEOselya) api.searchParams.set("eOselya", "1");
    const keyword = (localStorage.getItem(KEYWORD_SEARCH_KEY) || "").trim();
    if (keyword) {
      api.searchParams.set("search", keyword);
      api.searchParams.set("sort", "relevance");
    }
    if (localStorage.getItem(VERIFIED_AGENCY_FILTER_KEY) === "1") api.searchParams.set("verifiedAgency", "1");
    const duplicateRisk = localStorage.getItem(DUPLICATE_RISK_FILTER_KEY) || "all";
    if (duplicateRisk === "low" || duplicateRisk === "medium" || duplicateRisk === "high") {
      api.searchParams.set("duplicateRisk", duplicateRisk);
    }
    return api.toString();
  }

  let leafletLoader = null;
  function ensureLeafletLoaded() {
    if (window.L?.map) return Promise.resolve(window.L);
    if (leafletLoader) return leafletLoader;
    leafletLoader = new Promise((resolve, reject) => {
      const cssId = "uah-leaflet-css";
      if (!document.getElementById(cssId)) {
        const link = document.createElement("link");
        link.id = cssId;
        link.rel = "stylesheet";
        link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        document.head.appendChild(link);
      }
      const scriptId = "uah-leaflet-js";
      const existing = document.getElementById(scriptId);
      if (existing) {
        existing.addEventListener("load", () => resolve(window.L));
        existing.addEventListener("error", () => reject(new Error("Leaflet failed to load")));
        return;
      }
      const script = document.createElement("script");
      script.id = scriptId;
      script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      script.async = true;
      script.onload = () => resolve(window.L);
      script.onerror = () => reject(new Error("Leaflet failed to load"));
      document.head.appendChild(script);
    });
    return leafletLoader;
  }

  function clusterListings(items, zoom) {
    const precision = Math.max(0.002, 0.1 / Math.pow(2, Math.max(0, zoom - 9)));
    const groups = new Map();
    items.forEach((item) => {
      const lat = Number(item.latitude);
      const lng = Number(item.longitude);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
      const key = `${Math.round(lat / precision)}:${Math.round(lng / precision)}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });
    return [...groups.values()].map((group) => {
      const lat = group.reduce((sum, item) => sum + Number(item.latitude || 0), 0) / group.length;
      const lng = group.reduce((sum, item) => sum + Number(item.longitude || 0), 0) / group.length;
      return { lat, lng, items: group };
    });
  }

  function duplicateRiskLegendHtml(theme = "slate") {
    const textTone = theme === "blue" ? "text-blue-700" : "text-slate-700";
    const borderTone = theme === "blue" ? "border-blue-200" : "border-slate-200";
    const bgTone = theme === "blue" ? "bg-white/80" : "bg-slate-50";
    return `
      <details class="text-xs ${textTone}">
        <summary class="cursor-pointer select-none">Як рахується ризик дубля?</summary>
        <div class="mt-1 p-2 rounded-lg border ${borderTone} ${bgTone}">
          <p><b>Низький:</b> 1 схожий об'єкт у кластері.</p>
          <p><b>Середній:</b> 2 схожі об'єкти.</p>
          <p><b>Високий:</b> 3+ схожих об'єкти.</p>
          <p class="mt-1 opacity-80">Кластер: місто + район + тип + продаж/оренда + кімнати + близькі price/area.</p>
        </div>
      </details>
    `;
  }

  function installBaseVerifiedAgencyToggle(hostSection) {
    if (!hostSection) return null;
    const existing = document.querySelector('[data-role="base-verified-agency-toggle"]');
    if (existing) return existing;
    const row = document.createElement("div");
    row.setAttribute("data-role", "base-verified-agency-toggle");
    row.className = "max-w-7xl mx-auto px-4 mt-3";
    row.innerHTML = `
      <div class="bg-white border border-slate-200 rounded-xl px-4 py-3 shadow-sm">
        <div class="flex flex-wrap items-center gap-4">
          <label class="inline-flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
            <input type="checkbox" class="w-4 h-4" data-role="base-verified-agency-checkbox"/>
            Лише перевірені агентства/забудовники
          </label>
          <label class="inline-flex items-center gap-2 text-sm text-slate-700">
            <span>Ризик дубля:</span>
            <select class="px-2 py-1 rounded-lg border border-slate-300 bg-white text-sm" data-role="base-duplicate-risk-select">
              <option value="all">Всі</option>
              <option value="low">Низький</option>
              <option value="medium">Середній</option>
              <option value="high">Високий</option>
            </select>
          </label>
          ${duplicateRiskLegendHtml("slate")}
        </div>
      </div>
    `;
    hostSection.insertAdjacentElement("afterend", row);
    const checkbox = row.querySelector('[data-role="base-verified-agency-checkbox"]');
    const riskSelect = row.querySelector('[data-role="base-duplicate-risk-select"]');
    checkbox.checked = localStorage.getItem(VERIFIED_AGENCY_FILTER_KEY) === "1";
    checkbox.addEventListener("change", () => {
      localStorage.setItem(VERIFIED_AGENCY_FILTER_KEY, checkbox.checked ? "1" : "0");
      window.location.reload();
    });
    riskSelect.value = localStorage.getItem(DUPLICATE_RISK_FILTER_KEY) || "all";
    riskSelect.addEventListener("change", () => {
      localStorage.setItem(DUPLICATE_RISK_FILTER_KEY, riskSelect.value || "all");
      window.location.reload();
    });
    return row;
  }

  function buildPanel(filters) {
    const existingPanel = document.querySelector('[data-ua-homes-market-upgrade="1"]');
    if (existingPanel) return existingPanel;
    const hostSection = filters.citySelect.closest("section") || filters.citySelect.closest("div");
    if (!hostSection) return;
    const baseToggleRow = installBaseVerifiedAgencyToggle(hostSection);

    const panel = document.createElement("section");
    panel.setAttribute("data-ua-homes-market-upgrade", "1");
    panel.className = "max-w-7xl mx-auto px-4 mt-4 mb-4 market-smart-panel";
    panel.innerHTML = `
      <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
        <div class="flex flex-col gap-5">
          <div>
            <h2 class="text-lg font-bold text-slate-900">РОЗУМНИЙ ПОШУК</h2>
            <div class="mt-3 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3">
              <p class="text-[11px] font-bold uppercase tracking-wide text-blue-700">Активний запит</p>
              <p class="mt-1 text-sm text-slate-700" data-role="search-summary">—</p>
            </div>
          </div>

          <div class="sticky top-4 z-20 rounded-xl border border-slate-200 bg-white/95 p-4 shadow-sm backdrop-blur">
            <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <p class="text-xs font-black uppercase tracking-wide text-slate-500">Активні фільтри</p>
                <p class="mt-1 text-sm text-slate-600">Швидко вимикайте окремі умови або застосовуйте швидкі фільтри.</p>
              </div>
              <button type="button" class="px-4 py-2 rounded-xl bg-slate-900 text-white text-sm font-bold hover:bg-blue-700 transition" data-role="clear-all-filters">Скинути все</button>
            </div>
            <div class="mt-3 flex flex-wrap gap-2" data-role="active-filter-chips"></div>
            <div class="mt-4 flex flex-wrap gap-2" data-role="one-click-chips"></div>
          </div>

          <div>
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 mb-2">Швидкі сценарії</p>
            <div class="flex flex-wrap gap-2" data-role="quick-scenarios"></div>
          </div>

          <div class="p-3 rounded-xl bg-blue-50 border border-blue-100">
            <div class="flex items-center justify-between gap-3 mb-2">
              <p class="text-xs font-bold uppercase tracking-wide text-blue-700">Пошук за ключовими словами</p>
              <button type="button" class="px-2.5 py-1.5 rounded-lg bg-white border border-blue-200 text-blue-700 text-xs font-semibold hover:bg-blue-100 transition" data-role="clear-keyword-search">Очистити</button>
            </div>
            <div class="flex flex-col sm:flex-row gap-2">
              <input type="text" class="flex-1 px-3 py-2 rounded-lg border border-blue-200 bg-white text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-400" placeholder="ЖК, метро, вулиця, ремонт, тераса..." data-role="keyword-search-input"/>
              <button type="button" class="px-3 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition" data-role="apply-keyword-search">Застосувати</button>
            </div>
            <div class="mt-3 flex flex-wrap gap-2" data-role="keyword-suggestions"></div>
            <p class="text-xs text-blue-700 mt-2">Працює з релевантністю. Після застосування сторінка оновиться.</p>
            <label class="mt-2 inline-flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" class="w-4 h-4" data-role="verified-agency-filter"/>
              Лише перевірені агентства/забудовники
            </label>
            <label class="mt-2 inline-flex items-center gap-2 text-sm text-slate-700">
              <span>Ризик дубля:</span>
              <select class="px-2 py-1 rounded-lg border border-blue-200 bg-white text-sm" data-role="duplicate-risk-filter">
                <option value="all">Всі</option>
                <option value="low">Низький</option>
                <option value="medium">Середній</option>
                <option value="high">Високий</option>
              </select>
            </label>
            ${duplicateRiskLegendHtml("blue")}
          </div>

          <div class="p-3 rounded-xl bg-slate-50 border border-slate-200">
            <div class="flex items-center justify-between gap-3 mb-2">
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Розумні підказки району</p>
              <button type="button" class="px-2.5 py-1.5 rounded-lg bg-white border border-slate-300 text-slate-700 text-xs font-semibold hover:bg-slate-100 transition" data-role="clear-district">Очистити район</button>
            </div>
            <p class="text-sm text-slate-600 mb-2">Для міста <span class="font-semibold text-slate-900" data-role="district-city-label">—</span>:</p>
            <div class="flex flex-wrap gap-2" data-role="district-hints"></div>
          </div>

          <div class="p-3 rounded-xl bg-emerald-50 border border-emerald-100">
            <p class="text-xs font-bold uppercase tracking-wide text-emerald-700 mb-2">Центри України у пошуку</p>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-2">
              <select data-role="ua-region-select" class="px-2 py-2 rounded-lg border border-emerald-200 bg-white text-sm">
                <option value="">Оберіть область</option>
              </select>
              <select data-role="ua-center-select" class="px-2 py-2 rounded-lg border border-emerald-200 bg-white text-sm">
                <option value="">Оберіть обласний/районний центр</option>
              </select>
              <select data-role="ua-district-select" class="px-2 py-2 rounded-lg border border-emerald-200 bg-white text-sm">
                <option value="">Оберіть район</option>
              </select>
            </div>
            <div class="mt-2 flex items-center justify-between gap-2">
              <p class="text-xs text-emerald-700" data-role="ua-centers-meta">Завантажуємо перелік центрів…</p>
              <button type="button" class="px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 transition" data-role="ua-centers-apply">Застосувати локацію</button>
            </div>
          </div>

          <div>
            <div class="flex items-center justify-between gap-3 mb-2">
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Збережені пошуки</p>
              <div class="flex flex-wrap gap-2">
                <button type="button" class="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition" data-role="save-current-search">Зберегти поточний пошук</button>
                <button type="button" class="px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 transition" data-role="save-alert">Email/push алерт</button>
              </div>
            </div>
            <div class="flex flex-wrap gap-2" data-role="saved-scenarios"></div>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Порівняння обраних</p>
                <p class="text-sm text-slate-600 mt-1">Швидкий shortlist для прийняття рішення: ціна, площа, кімнати, єОселя.</p>
              </div>
              <button
                type="button"
                class="px-3 py-2 rounded-lg bg-slate-900 text-white text-sm font-semibold hover:bg-blue-700 transition"
                data-role="compare-favorites"
              >
                Порівняти зараз
              </button>
            </div>
            <div class="mt-3 rounded-xl bg-slate-50 border border-slate-200 p-3" data-role="compare-summary">
              <p class="text-sm text-slate-500">Додайте кілька обраних об'єктів, а потім натисніть «Порівняти зараз».</p>
            </div>
            <div class="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3" data-role="compare-grid"></div>
          </div>

          <div>
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 mb-2">Популярні маршрути пошуку</p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2" data-role="popular-routes"></div>
          </div>

          <div>
            <div class="flex items-center justify-between gap-3 mb-2">
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Перевірені агентства / забудовники</p>
              <a href="/agencies" target="_blank" rel="noopener" class="text-xs font-semibold text-blue-700 hover:text-blue-800">Весь каталог ↗</a>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3" data-role="trusted-partners"></div>
          </div>

          <div>
            <div class="flex items-center justify-between gap-3 mb-2">
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Огляди ринку</p>
              <a href="/insights" target="_blank" rel="noopener" class="text-xs font-semibold text-blue-700 hover:text-blue-800">Усі матеріали ↗</a>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3" data-role="content-discovery"></div>
          </div>
        </div>
      </div>
    `;
    (baseToggleRow || hostSection).insertAdjacentElement("afterend", panel);

    const quickWrap = panel.querySelector('[data-role="quick-scenarios"]');
    const savedWrap = panel.querySelector('[data-role="saved-scenarios"]');
    const saveButton = panel.querySelector('[data-role="save-current-search"]');
    const saveAlertButton = panel.querySelector('[data-role="save-alert"]');
    const districtWrap = panel.querySelector('[data-role="district-hints"]');
    const districtLabel = panel.querySelector('[data-role="district-city-label"]');
    const clearDistrictButton = panel.querySelector('[data-role="clear-district"]');
    const keywordSearchInput = panel.querySelector('[data-role="keyword-search-input"]');
    const applyKeywordSearchButton = panel.querySelector('[data-role="apply-keyword-search"]');
    const clearKeywordSearchButton = panel.querySelector('[data-role="clear-keyword-search"]');
    const searchSummary = panel.querySelector('[data-role="search-summary"]');
    const keywordSuggestionsWrap = panel.querySelector('[data-role="keyword-suggestions"]');
    const verifiedAgencyFilter = panel.querySelector('[data-role="verified-agency-filter"]');
    const duplicateRiskFilter = panel.querySelector('[data-role="duplicate-risk-filter"]');
    const popularRoutesWrap = panel.querySelector('[data-role="popular-routes"]');
    const clearAllFiltersButton = panel.querySelector('[data-role="clear-all-filters"]');
    const activeFilterChipsWrap = panel.querySelector('[data-role="active-filter-chips"]');
    const oneClickChipsWrap = panel.querySelector('[data-role="one-click-chips"]');
    const compareButton = panel.querySelector('[data-role="compare-favorites"]');
    const compareSummary = panel.querySelector('[data-role="compare-summary"]');
    const compareGrid = panel.querySelector('[data-role="compare-grid"]');
    const trustedPartnersWrap = panel.querySelector('[data-role="trusted-partners"]');
    const contentDiscoveryWrap = panel.querySelector('[data-role="content-discovery"]');
    const uaRegionSelect = panel.querySelector('[data-role="ua-region-select"]');
    const uaCenterSelect = panel.querySelector('[data-role="ua-center-select"]');
    const uaDistrictSelect = panel.querySelector('[data-role="ua-district-select"]');
    const uaCentersMeta = panel.querySelector('[data-role="ua-centers-meta"]');
    const uaCentersApply = panel.querySelector('[data-role="ua-centers-apply"]');
    let trustedPartnersLoaded = false;
    let contentDiscoveryLoaded = false;

    QUICK_SCENARIOS.forEach((scenario) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "px-3 py-2 rounded-lg bg-slate-100 text-slate-800 text-sm font-medium hover:bg-slate-200 transition";
      button.textContent = scenario.label;
      button.addEventListener("click", () => applyFilters(scenario.filters, filters));
      quickWrap.appendChild(button);
    });

    KEYWORD_SUGGESTIONS.forEach((suggestion) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "px-3 py-1.5 rounded-full border border-blue-200 bg-white text-blue-700 text-xs font-semibold hover:bg-blue-100 transition";
      chip.textContent = suggestion;
      chip.addEventListener("click", () => {
        if (!keywordSearchInput) return;
        keywordSearchInput.value = keywordSearchInput.value.trim()
          ? `${keywordSearchInput.value.trim()} ${suggestion}`
          : suggestion;
        keywordSearchInput.focus();
        applyKeywordSearch();
      });
      keywordSuggestionsWrap?.appendChild(chip);
    });

    function renderDistrictHints() {
      districtWrap.innerHTML = "";
      const city = filters.citySelect.value || "Всі";
      districtLabel.textContent = city;
      const hints = districtHintsByCity(city);
      hints.forEach((district) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "px-2.5 py-1.5 rounded-lg bg-white border border-slate-300 text-slate-700 text-xs font-medium hover:bg-blue-50 hover:border-blue-300 transition";
        chip.textContent = district;
        chip.addEventListener("click", () => {
          if (!filters.districtInput) return;
          filters.districtInput.value = district;
          fireInput(filters.districtInput);
        });
        districtWrap.appendChild(chip);
      });
    }

    async function initUaCentersDirectory() {
      const dataset = await ensureUaCentersDataset();
      appendMissingCityOptions(filters.citySelect, dataset.allCenters || []);
      if (!filters.districtInput) return;

      let districtList = document.getElementById("ua-homes-district-centers-list");
      if (!districtList) {
        districtList = document.createElement("datalist");
        districtList.id = "ua-homes-district-centers-list";
        document.body.appendChild(districtList);
      }
      const allDistricts = Array.from(
        new Set(
          Object.values(dataset.regionData || {}).flatMap((item) => item?.districts || [])
        )
      ).sort((a, b) => String(a).localeCompare(String(b), "uk", { sensitivity: "base" }));
      districtList.innerHTML = allDistricts.map((district) => `<option value="${district}"></option>`).join("");
      filters.districtInput.setAttribute("list", "ua-homes-district-centers-list");

      if (!uaRegionSelect || !uaCenterSelect || !uaDistrictSelect) return;
      uaRegionSelect.innerHTML = `<option value="">Оберіть область</option>${sortUaNames(dataset.regions || [])
        .map((region) => `<option value="${region}">${region}</option>`)
        .join("")}`;

      const renderRegionOptions = (region) => {
        const regionItem = (dataset.regionData || {})[region] || { centers: dataset.allCenters || [], districts: allDistricts };
        const sortedCenters = sortUaNames(regionItem.centers || []);
        const sortedDistricts = sortUaNames(regionItem.districts || []);
        uaCenterSelect.innerHTML = `<option value="">Оберіть обласний/районний центр</option>${sortedCenters
          .map((center) => `<option value="${center}">${center}</option>`)
          .join("")}`;
        uaDistrictSelect.innerHTML = `<option value="">Оберіть район</option>${sortedDistricts
          .map((district) => `<option value="${district}">${district}</option>`)
          .join("")}`;
        if (uaCentersMeta) {
          uaCentersMeta.textContent = region
            ? `${sortedCenters.length} центрів, ${sortedDistricts.length} районів у регіоні`
            : `${dataset.allCenters?.length || 0} центрів по Україні`;
        }
      };

      uaRegionSelect.addEventListener("change", () => {
        renderRegionOptions(uaRegionSelect.value);
      });

      uaCentersApply?.addEventListener("click", () => {
        const center = uaCenterSelect.value.trim();
        const district = uaDistrictSelect.value.trim();
        if (center) {
          filters.citySelect.value = center;
          fireInput(filters.citySelect);
        }
        if (filters.districtInput) {
          filters.districtInput.value = district;
          fireInput(filters.districtInput);
        }
      });

      renderRegionOptions("");
    }

    function renderSearchSummary() {
      if (!searchSummary) return;
      searchSummary.textContent = describeSearchState(readFilters(filters));
    }

    function clearActiveFilter(key) {
      if (key === "city") {
        filters.citySelect.value = "Всі";
        fireInput(filters.citySelect);
        return;
      }
      if (key === "district" && filters.districtInput) {
        filters.districtInput.value = "";
        fireInput(filters.districtInput);
        return;
      }
      if (key === "propertyType" && filters.propertyTypeSelect) {
        filters.propertyTypeSelect.value = "Всі типи";
        fireInput(filters.propertyTypeSelect);
        return;
      }
      if (key === "eOselya" && filters.eoselyaCheckbox) {
        filters.eoselyaCheckbox.checked = false;
        fireInput(filters.eoselyaCheckbox);
        return;
      }
      if (key === "price") {
        filters.minPrice.value = "";
        filters.maxPrice.value = "";
        fireInput(filters.minPrice);
        fireInput(filters.maxPrice);
        return;
      }
      if (key === "rooms") {
        filters.minRooms.value = "";
        filters.maxRooms.value = "";
        fireInput(filters.minRooms);
        fireInput(filters.maxRooms);
        return;
      }
      if (key === "area") {
        filters.minArea.value = "";
        filters.maxArea.value = "";
        fireInput(filters.minArea);
        fireInput(filters.maxArea);
        return;
      }
      if (key === "keyword") {
        localStorage.removeItem(KEYWORD_SEARCH_KEY);
        if (keywordSearchInput) keywordSearchInput.value = "";
        window.location.reload();
      }
    }

    function renderActiveFilters() {
      if (!activeFilterChipsWrap) return;
      const values = readFilters(filters);
      const items = [];
      if (values.city !== "Всі") items.push({ key: "city", label: `Місто: ${values.city}` });
      if (values.district) items.push({ key: "district", label: `Район: ${values.district}` });
      if (values.propertyType && values.propertyType !== "Всі типи") items.push({ key: "propertyType", label: `Тип: ${values.propertyType}` });
      if (values.onlyEOselya) items.push({ key: "eOselya", label: "єОселя" });
      if (values.minPrice || values.maxPrice) items.push({ key: "price", label: `Ціна: $${values.minPrice || "0"}-${values.maxPrice || "∞"}` });
      if (values.minRooms || values.maxRooms) items.push({ key: "rooms", label: `Кімнати: ${values.minRooms || "1"}-${values.maxRooms || "∞"}` });
      if (values.minArea || values.maxArea) items.push({ key: "area", label: `Площа: ${values.minArea || "0"}-${values.maxArea || "∞"} м²` });
      const keyword = (localStorage.getItem(KEYWORD_SEARCH_KEY) || "").trim();
      if (keyword) items.push({ key: "keyword", label: `Пошук: "${keyword}"` });

      activeFilterChipsWrap.innerHTML = "";
      if (!items.length) {
        activeFilterChipsWrap.innerHTML = '<p class="text-sm text-slate-500">Активних фільтрів немає.</p>';
        return;
      }

      items.forEach((item) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-blue-50 hover:border-blue-200 transition";
        chip.textContent = item.label;
        chip.addEventListener("click", () => clearActiveFilter(item.key));
        activeFilterChipsWrap.appendChild(chip);
      });
    }

    function renderOneClickChips() {
      if (!oneClickChipsWrap) return;
      const values = readFilters(filters);
      const chips = [
        { label: "Київ", onClick: () => applyFilters({ city: "Київ" }, filters) },
        { label: "Львів", onClick: () => applyFilters({ city: "Львів" }, filters) },
        { label: "єОселя", onClick: () => applyFilters({ onlyEOselya: !values.onlyEOselya }, filters) },
        { label: "1-2 кімн.", onClick: () => applyFilters({ minRooms: "1", maxRooms: "2" }, filters) },
        { label: "до $100k", onClick: () => applyFilters({ maxPrice: "100000" }, filters) },
        { label: "35+ м²", onClick: () => applyFilters({ minArea: "35" }, filters) },
        { label: "Релевантні", onClick: () => {
          localStorage.setItem(KEYWORD_SEARCH_KEY, (localStorage.getItem(KEYWORD_SEARCH_KEY) || "").trim());
          window.location.reload();
        } },
      ];
      oneClickChipsWrap.innerHTML = "";
      chips.forEach((chipDef) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "px-3 py-1.5 rounded-full border border-blue-200 bg-white text-blue-700 text-xs font-semibold hover:bg-blue-100 transition";
        chip.textContent = chipDef.label;
        chip.addEventListener("click", chipDef.onClick);
        oneClickChipsWrap.appendChild(chip);
      });
      const reset = document.createElement("button");
      reset.type = "button";
      reset.className = "px-3 py-1.5 rounded-full border border-slate-200 bg-slate-50 text-slate-700 text-xs font-semibold hover:bg-slate-100 transition";
      reset.textContent = "Скинути все";
      reset.addEventListener("click", () => window.location.reload());
      oneClickChipsWrap.appendChild(reset);
    }

    async function renderFavoriteCompare() {
      if (!compareSummary || !compareGrid) return;
      const favoriteIds = getFavoriteIds().slice(0, 3);
      compareGrid.innerHTML = "";
      if (!favoriteIds.length) {
        compareSummary.innerHTML = '<p class="text-sm text-slate-500">Поки що немає обраних об\'єктів для порівняння.</p>';
        return;
      }

      compareSummary.innerHTML = `<p class="text-sm text-slate-700">Порівнюємо ${favoriteIds.length} обраних об\'єктів. Кращий value позначимо окремо.</p>`;
      compareGrid.innerHTML = '<p class="text-sm text-slate-500">Завантаження порівняння…</p>';

      try {
        const listings = await Promise.all(
          favoriteIds.map(async (id) => {
            const res = await fetch(`${resolveApiBase()}/api/listings/${id}`, { credentials: "omit" });
            if (!res.ok) throw new Error(`Listing ${id} failed`);
            const payload = await res.json();
            return payload?.listing || payload;
          })
        );

        const activeListings = listings.filter(Boolean);
        if (!activeListings.length) {
          compareGrid.innerHTML = '<p class="text-sm text-slate-500">Не вдалося завантажити обрані об\'єкти.</p>';
          return;
        }

        const bestValueId = activeListings.reduce((best, item) => {
          const currentScore = Number(item.price || 0) / Math.max(Number(item.area || 1), 1);
          if (!best) return item.id;
          const bestItem = activeListings.find((candidate) => candidate.id === best);
          const bestScore = Number(bestItem?.price || 0) / Math.max(Number(bestItem?.area || 1), 1);
          return currentScore < bestScore ? item.id : best;
        }, null);

        compareGrid.innerHTML = activeListings
          .map((item) => `
            <div class="rounded-xl border ${item.id === bestValueId ? "border-emerald-300 bg-emerald-50" : "border-slate-200 bg-white"} p-3">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <p class="text-sm font-bold text-slate-900 line-clamp-2">${item.title}</p>
                  <p class="text-xs text-slate-500 mt-1">${item.city || "—"} · ${item.district || "—"}</p>
                </div>
                ${item.id === bestValueId ? '<span class="text-[10px] px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 font-semibold">BEST VALUE</span>' : ""}
              </div>
              <div class="mt-3 space-y-1.5 text-sm text-slate-700">
                <div class="flex justify-between gap-3"><span>Ціна</span><b>$${Number(item.price || 0).toLocaleString("uk-UA")}</b></div>
                <div class="flex justify-between gap-3"><span>Площа</span><b>${Number(item.area || 0)} м²</b></div>
                <div class="flex justify-between gap-3"><span>Кімнати</span><b>${Number(item.rooms || 0)}</b></div>
                <div class="flex justify-between gap-3"><span>єОселя</span><b>${item.eOselya ? "Так" : "Ні"}</b></div>
              </div>
              <a class="mt-3 inline-flex text-xs font-semibold text-blue-700 hover:text-blue-800" href="/listing/${item.id}" target="_blank" rel="noopener">Відкрити ↗</a>
            </div>
          `)
          .join("");
      } catch (_err) {
        compareGrid.innerHTML = '<p class="text-sm text-slate-500">Не вдалося завантажити порівняння.</p>';
      }
    }

    function renderSaved() {
      const searches = getSavedSearches();
      savedWrap.innerHTML = "";
      if (!searches.length) {
        const empty = document.createElement("p");
        empty.className = "text-sm text-slate-500";
        empty.textContent = "Поки що немає збережених пошуків.";
        savedWrap.appendChild(empty);
        return;
      }
      searches.forEach((item) => {
        const row = document.createElement("div");
        row.className = "inline-flex items-center gap-1.5";

        const applyBtn = document.createElement("button");
        applyBtn.type = "button";
        applyBtn.className = "px-3 py-2 rounded-lg bg-blue-50 border border-blue-200 text-blue-700 text-sm font-medium hover:bg-blue-100 transition";
        applyBtn.textContent = item.name;
        applyBtn.addEventListener("click", () => applyFilters(item.filters, filters));

        const deleteBtn = document.createElement("button");
        deleteBtn.type = "button";
        deleteBtn.className = "px-2 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs font-semibold hover:bg-red-100 transition";
        deleteBtn.textContent = "×";
        deleteBtn.setAttribute("aria-label", `Видалити пошук ${item.name}`);
        deleteBtn.addEventListener("click", () => {
          setSavedSearches(getSavedSearches().filter((entry) => entry.id !== item.id));
          renderSaved();
        });

        row.append(applyBtn, deleteBtn);
        savedWrap.appendChild(row);
      });
    }

    POPULAR_ROUTES.forEach((route) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "text-left p-3 rounded-xl bg-slate-50 border border-slate-200 hover:border-blue-300 hover:bg-blue-50 transition";
      button.innerHTML = `
        <p class="text-sm font-semibold text-slate-900">${route.label}</p>
        <p class="text-xs text-slate-600 mt-1">${route.subtitle}</p>
      `;
      button.addEventListener("click", () => {
        applyFilters(route.filters, filters);
        trackPopularRoute(route);
      });
      popularRoutesWrap.appendChild(button);
    });

    async function renderAgencyProfiles() {
      trustedPartnersLoaded = true;
      trustedPartnersWrap.innerHTML = "";
      try {
        const res = await fetch(`${resolveApiBase()}/api/agencies?verified_only=1&sort=reputation&limit=8`, { credentials: "omit" });
        const payload = await res.json();
        const agencies = Array.isArray(payload?.agencies) && payload.agencies.length
          ? payload.agencies
          : TRUSTED_PARTNERS.map((item) => ({
              slug: item.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
              name: item.name,
              kind: item.kind === "Забудовник" ? "developer" : "agency",
              city: item.city,
              specialization: item.specialization,
              active_listings: 0,
              team_size: 3,
              completed_deals: 0,
              avg_response_minutes: null,
              verified_rate: 100,
              moderation_rate: 100,
              freshness_index: 82,
              reputation_score: 82,
              reputation_tier: "A",
              is_verified: true,
              last_verified_at: null,
            }));

        agencies.forEach((agency) => {
          const kindLabel = agency.kind === "developer" ? "Забудовник" : "Агентство";
          const verifiedDate = agency.last_verified_at
            ? new Date(agency.last_verified_at).toLocaleDateString("uk-UA")
            : "сьогодні";
          const card = document.createElement("div");
          card.className = "p-3 rounded-xl border border-emerald-200 bg-emerald-50";
          card.innerHTML = `
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="text-sm font-bold text-slate-900">${agency.name}</p>
                <p class="text-xs text-slate-600 mt-0.5">${kindLabel} · ${agency.city}</p>
              </div>
              <span class="text-[10px] px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 font-semibold">${agency.is_verified ? "VERIFIED" : "PENDING"}</span>
            </div>
            <p class="text-xs text-slate-700 mt-2">${agency.specialization || "Нерухомість та супровід угод"}</p>
            <div class="grid grid-cols-3 gap-1.5 mt-2">
              <span class="text-[10px] px-2 py-1 rounded bg-white border border-emerald-200 text-emerald-700 font-medium">Активні: ${agency.active_listings ?? 0}</span>
              <span class="text-[10px] px-2 py-1 rounded bg-white border border-emerald-200 text-emerald-700 font-medium">Команда: ${agency.team_size ?? "—"}</span>
              <span class="text-[10px] px-2 py-1 rounded bg-white border border-emerald-200 text-emerald-700 font-medium">Репутація: ${agency.reputation_tier || "B"} · ${Math.round(Number(agency.reputation_score || 0))}</span>
            </div>
            <div class="grid grid-cols-2 gap-1.5 mt-2">
              <span class="text-[10px] px-2 py-1 rounded bg-white border border-emerald-200 text-emerald-700 font-medium">Відповідь: ${agency.avg_response_minutes ?? "—"} хв</span>
              <span class="text-[10px] px-2 py-1 rounded bg-white border border-emerald-200 text-emerald-700 font-medium">Угод: ${agency.completed_deals ?? 0}</span>
            </div>
            <p class="text-[11px] text-slate-500 mt-2">Verified: ${Math.round(Number(agency.verified_rate || 0))}% · Перевірка: ${verifiedDate}</p>
          `;
          const controls = document.createElement("div");
          controls.className = "mt-3 flex flex-wrap gap-2";

          const cityBtn = document.createElement("button");
          cityBtn.type = "button";
          cityBtn.className = "px-3 py-1.5 rounded-lg bg-white border border-emerald-300 text-emerald-700 text-xs font-semibold hover:bg-emerald-100 transition";
          cityBtn.textContent = `Показати пропозиції в ${agency.city}`;
          cityBtn.addEventListener("click", () => applyFilters({ city: agency.city, listingMode: "sale" }, filters));

          const profileLink = document.createElement("a");
          profileLink.href = `/agencies/${agency.slug}`;
          profileLink.target = "_blank";
          profileLink.rel = "noopener";
          profileLink.className = "px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-blue-700 transition";
          profileLink.textContent = "Профіль і метрики ↗";

          controls.append(cityBtn, profileLink);
          card.appendChild(controls);
          trustedPartnersWrap.appendChild(card);
        });
      } catch (_err) {
        trustedPartnersWrap.innerHTML = '<p class="text-sm text-slate-500">Не вдалося завантажити профілі агентств.</p>';
      }
    }

    async function renderContentDiscovery() {
      contentDiscoveryLoaded = true;
      if (!contentDiscoveryWrap) return;
      contentDiscoveryWrap.innerHTML = "";
      try {
        const res = await fetch(`${resolveApiBase()}/api/content?limit=4`, { credentials: "omit" });
        const payload = await res.json();
        const articles = Array.isArray(payload?.articles) ? payload.articles : [];
        if (!articles.length) throw new Error("No content");
        articles.forEach((article) => {
          const card = document.createElement("article");
          card.className = "rounded-xl border border-blue-100 bg-blue-50 p-3";
          const stats = Array.isArray(article.stats) ? article.stats.slice(0, 3) : [];
          card.innerHTML = `
            <div class="flex items-center justify-between gap-3">
              <span class="text-[10px] px-2 py-1 rounded-full bg-white border border-blue-200 text-blue-700 font-semibold">${article.category || "Insights"}</span>
              <span class="text-[10px] text-slate-500">${article.published_at || ""} · ${article.reading_time || 3} хв</span>
            </div>
            <h4 class="mt-2 text-sm font-bold text-slate-900 line-clamp-2">${article.title}</h4>
            <p class="mt-1 text-xs text-slate-600 line-clamp-3">${article.excerpt || ""}</p>
            <div class="mt-2 flex flex-wrap gap-1.5">${stats.map((stat) => `<span class="text-[10px] px-2 py-1 rounded bg-white border border-blue-200 text-blue-700 font-medium">${stat.label}: ${stat.value}</span>`).join("")}</div>
          `;
          const footer = document.createElement("div");
          footer.className = "mt-3 flex items-center justify-between gap-2";

          const openLink = document.createElement("a");
          openLink.href = `/insights/${article.slug}`;
          openLink.target = "_blank";
          openLink.rel = "noopener";
          openLink.className = "text-xs font-semibold text-blue-700 hover:text-blue-800";
          openLink.textContent = "Читати матеріал ↗";

          const category = document.createElement("span");
          category.className = "text-[10px] px-2 py-1 rounded-full bg-white border border-slate-200 text-slate-500";
          category.textContent = article.featured ? "Featured" : "Fresh";

          footer.append(category, openLink);
          card.appendChild(footer);
          contentDiscoveryWrap.appendChild(card);
        });
      } catch (_err) {
        const fallback = [
          { title: "Ринок: топ-міста і середні ціни", href: "/insights/market-update-kyiv-leads" },
          { title: "єОселя watch та карти попиту", href: "/insights/eoselya-watch" },
          { title: "Лідери перевірки серед агентств", href: "/insights/verified-agencies-leadership" },
        ];
        contentDiscoveryWrap.innerHTML = fallback.map((item) => `
          <a href="${item.href}" target="_blank" rel="noopener" class="rounded-xl border border-blue-100 bg-blue-50 p-3 hover:bg-blue-100 transition">
            <p class="text-sm font-bold text-slate-900">${item.title}</p>
            <p class="mt-1 text-xs text-blue-700 font-semibold">Відкрити ↗</p>
          </a>
        `).join("");
      }
    }

    function loadDeferredDiscovery() {
      if (!trustedPartnersLoaded) renderAgencyProfiles();
      if (!contentDiscoveryLoaded) renderContentDiscovery();
    }

    function setupDeferredDiscovery() {
      if (!trustedPartnersWrap && !contentDiscoveryWrap) return;
      const targets = [trustedPartnersWrap, contentDiscoveryWrap].filter(Boolean);
      if (!("IntersectionObserver" in window)) {
        loadDeferredDiscovery();
        return;
      }
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          if (entry.target === trustedPartnersWrap && !trustedPartnersLoaded) renderAgencyProfiles();
          if (entry.target === contentDiscoveryWrap && !contentDiscoveryLoaded) renderContentDiscovery();
          if (trustedPartnersLoaded && contentDiscoveryLoaded) observer.disconnect();
        });
      }, { rootMargin: "240px 0px" });
      targets.forEach((target) => observer.observe(target));
    }

    compareButton?.addEventListener("click", renderFavoriteCompare);
    window.addEventListener("focus", renderFavoriteCompare);
    clearAllFiltersButton?.addEventListener("click", () => {
      filters.citySelect.value = "Всі";
      fireInput(filters.citySelect);
      if (filters.propertyTypeSelect) {
        filters.propertyTypeSelect.value = "Всі типи";
        fireInput(filters.propertyTypeSelect);
      }
      if (filters.districtInput) {
        filters.districtInput.value = "";
        fireInput(filters.districtInput);
      }
      if (filters.eoselyaCheckbox) {
        filters.eoselyaCheckbox.checked = false;
        fireInput(filters.eoselyaCheckbox);
      }
      [filters.minPrice, filters.maxPrice, filters.minRooms, filters.maxRooms, filters.minArea, filters.maxArea].forEach((input) => {
        input.value = "";
        fireInput(input);
      });
      localStorage.removeItem(KEYWORD_SEARCH_KEY);
      if (keywordSearchInput) keywordSearchInput.value = "";
      renderSearchSummary();
      renderActiveFilters();
      refreshMapListings();
    });

    saveButton.addEventListener("click", () => {
      const current = readFilters(filters);
      const defaultName = `${current.city || "Всі"} · ${current.onlyEOselya ? "єОселя" : "всі"} · ${new Date().toLocaleDateString("uk-UA")}`;
      const name = (window.prompt("Назва для збереженого пошуку:", defaultName) || "").trim();
      if (!name) return;
      setSavedSearches([{ id: `search_${Date.now()}`, name, filters: current, createdAt: Date.now() }, ...getSavedSearches()]);
      renderSaved();
    });
    saveAlertButton?.addEventListener("click", async () => {
      const current = readFilters(filters);
      const savedEmail = localStorage.getItem("ua_homes_alert_email_v1") || "";
      const email = (window.prompt("Email для алерта:", savedEmail) || "").trim();
      if (!email) return;
      localStorage.setItem("ua_homes_alert_email_v1", email);
      const push = window.confirm("Увімкнути push-канал (через webhook/інтеграцію)?");
      const payload = {
        name: `${current.city || "Всі"} · алерт`,
        email,
        city: current.city === "Всі" ? "" : current.city,
        district: current.district || "",
        type: current.propertyType === "Всі типи" ? "" : current.propertyType,
        minPrice: current.minPrice || null,
        maxPrice: current.maxPrice || null,
        minRooms: current.minRooms || null,
        maxRooms: current.maxRooms || null,
        eOselya: !!current.onlyEOselya,
        listingType: getListingMode(filters),
        email: true,
        push,
      };
      try {
        const res = await fetch(`${resolveApiBase()}/api/alerts`, {
          method: "POST",
          credentials: "omit",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
          window.alert(data?.error || "Не вдалося зберегти алерт");
          return;
        }
        window.alert("Алерт збережено. Надішлемо email/push при новому релевантному об'єкті.");
      } catch (_err) {
        window.alert("Не вдалося створити алерт. Перевірте з'єднання.");
      }
    });

    clearDistrictButton.addEventListener("click", () => {
      if (!filters.districtInput) return;
      filters.districtInput.value = "";
      fireInput(filters.districtInput);
    });

    function applyKeywordSearch() {
      const value = (keywordSearchInput?.value || "").trim();
      if (value) {
        localStorage.setItem(KEYWORD_SEARCH_KEY, value);
      } else {
        localStorage.removeItem(KEYWORD_SEARCH_KEY);
      }
      window.location.reload();
    }

    if (keywordSearchInput) {
      keywordSearchInput.value = localStorage.getItem(KEYWORD_SEARCH_KEY) || "";
      keywordSearchInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          applyKeywordSearch();
        } else if (event.key === "Escape") {
          event.preventDefault();
          localStorage.removeItem(KEYWORD_SEARCH_KEY);
          keywordSearchInput.value = "";
          window.location.reload();
        }
      });
    }
    applyKeywordSearchButton?.addEventListener("click", applyKeywordSearch);
    clearKeywordSearchButton?.addEventListener("click", () => {
      localStorage.removeItem(KEYWORD_SEARCH_KEY);
      if (keywordSearchInput) keywordSearchInput.value = "";
      window.location.reload();
    });
    if (verifiedAgencyFilter) {
      verifiedAgencyFilter.checked = localStorage.getItem(VERIFIED_AGENCY_FILTER_KEY) === "1";
      verifiedAgencyFilter.addEventListener("change", () => {
        localStorage.setItem(VERIFIED_AGENCY_FILTER_KEY, verifiedAgencyFilter.checked ? "1" : "0");
        window.location.reload();
      });
    }
    if (duplicateRiskFilter) {
      duplicateRiskFilter.value = localStorage.getItem(DUPLICATE_RISK_FILTER_KEY) || "all";
      duplicateRiskFilter.addEventListener("change", () => {
        localStorage.setItem(DUPLICATE_RISK_FILTER_KEY, duplicateRiskFilter.value || "all");
        window.location.reload();
      });
    }

    filters.citySelect.addEventListener("change", renderDistrictHints);
    [
      filters.citySelect,
      filters.propertyTypeSelect,
      filters.districtInput,
      filters.eoselyaCheckbox,
      filters.minPrice,
      filters.maxPrice,
      filters.minRooms,
      filters.maxRooms,
      filters.minArea,
      filters.maxArea,
    ].forEach((input) => {
      if (!input) return;
      input.addEventListener("input", renderSearchSummary);
      input.addEventListener("change", renderSearchSummary);
      input.addEventListener("input", renderActiveFilters);
      input.addEventListener("change", renderActiveFilters);
    });
    window.addEventListener("keydown", (event) => {
      if (event.defaultPrevented) return;
      if (event.key !== "/") return;
      const target = event.target;
      const tagName = target?.tagName || "";
      if (tagName === "INPUT" || tagName === "TEXTAREA" || target?.isContentEditable) return;
      if (!keywordSearchInput) return;
      event.preventDefault();
      keywordSearchInput.focus();
      keywordSearchInput.select();
    });
    renderDistrictHints();
    renderSaved();
    renderSearchSummary();
    renderActiveFilters();
    renderOneClickChips();
    renderFavoriteCompare();
    if (trustedPartnersWrap && !trustedPartnersWrap.children.length) {
      trustedPartnersWrap.innerHTML = '<p class="text-sm text-slate-500">Профілі агентств завантажаться трохи нижче під час скролу.</p>';
    }
    if (contentDiscoveryWrap && !contentDiscoveryWrap.children.length) {
      contentDiscoveryWrap.innerHTML = '<p class="text-sm text-slate-500">Контентні матеріали підтягнуться нижче під час скролу.</p>';
    }
    setupDeferredDiscovery();
    initUaCentersDirectory();
    return panel;
  }

  function installMapFirstMode(filters, panel) {
    if (!panel || document.querySelector('[data-role="map-first-mode"]')) return;
    const section = document.createElement("section");
    section.setAttribute("data-role", "map-first-mode");
    section.className = "max-w-7xl mx-auto px-4 mb-4";
    section.innerHTML = `
      <div class="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div class="px-4 py-3 border-b border-slate-200 flex items-center justify-between gap-3">
          <div>
            <p class="text-sm font-bold text-slate-900">Режим карти</p>
            <p class="text-xs text-slate-500">Перемикач між списком і картою.</p>
          </div>
          <div class="inline-flex bg-slate-100 rounded-lg p-1">
            <button type="button" data-role="mode-list" class="px-3 py-1.5 rounded-md text-sm font-semibold">Список</button>
            <button type="button" data-role="mode-map" class="px-3 py-1.5 rounded-md text-sm font-semibold">Карта</button>
          </div>
        </div>
        <div class="relative hidden opacity-0 map-shell-fade is-hidden" data-role="map-shell">
          <div data-role="map-canvas" style="height:520px"></div>
          <div class="map-skeleton" data-role="map-skeleton">
            <div>
              <div class="pulse"></div>
              <p class="mt-3 text-xs font-semibold text-slate-500">Завантажуємо карту та кластери…</p>
            </div>
          </div>
          <div class="absolute top-3 left-3 right-3 md:right-auto md:w-[420px] bg-white/95 backdrop-blur border border-slate-200 rounded-xl p-3 shadow" data-role="map-overlay">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 mb-2">Фільтри на мапі</p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <select data-role="map-city" class="px-2 py-2 rounded-lg border border-slate-300 bg-white text-sm"></select>
              <select data-role="map-type" class="px-2 py-2 rounded-lg border border-slate-300 bg-white text-sm"></select>
            </div>
            <label class="mt-2 inline-flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" data-role="map-eoselya" class="w-4 h-4"/>
              Лише єОселя
            </label>
            <div class="mt-2 flex items-center gap-2">
              <button type="button" data-role="map-apply" class="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition">Застосувати</button>
              <span data-role="map-count" class="text-xs text-slate-500">—</span>
            </div>
          </div>
        </div>
      </div>
    `;
    panel.insertAdjacentElement("afterend", section);

    const modeListBtn = section.querySelector('[data-role="mode-list"]');
    const modeMapBtn = section.querySelector('[data-role="mode-map"]');
    const mapShell = section.querySelector('[data-role="map-shell"]');
    const mapCanvas = section.querySelector('[data-role="map-canvas"]');
    const mapCount = section.querySelector('[data-role="map-count"]');
    const mapCity = section.querySelector('[data-role="map-city"]');
    const mapType = section.querySelector('[data-role="map-type"]');
    const mapEoselya = section.querySelector('[data-role="map-eoselya"]');
    const mapApply = section.querySelector('[data-role="map-apply"]');
    const mapSkeleton = section.querySelector('[data-role="map-skeleton"]');
    mapCity.innerHTML = filters.citySelect.innerHTML;
    mapType.innerHTML = filters.propertyTypeSelect?.innerHTML || '<option value="Всі типи">Всі типи</option>';

    const hiddenBlocks = [];
    let sibling = section.nextElementSibling;
    while (sibling) {
      hiddenBlocks.push(sibling);
      sibling = sibling.nextElementSibling;
    }

    const state = {
      map: null,
      layer: null,
      listings: [],
      refreshing: false,
    };

    function styleModeButtons(mode) {
      if (mode === "map") {
        modeMapBtn.className = "px-3 py-1.5 rounded-md text-sm font-semibold bg-blue-600 text-white";
        modeListBtn.className = "px-3 py-1.5 rounded-md text-sm font-semibold text-slate-700";
      } else {
        modeListBtn.className = "px-3 py-1.5 rounded-md text-sm font-semibold bg-blue-600 text-white";
        modeMapBtn.className = "px-3 py-1.5 rounded-md text-sm font-semibold text-slate-700";
      }
    }

    function renderMapClusters() {
      if (!state.map || !state.layer) return;
      state.layer.clearLayers();
      const clusters = clusterListings(state.listings, state.map.getZoom());
      clusters.forEach((cluster) => {
        if (!Number.isFinite(cluster.lat) || !Number.isFinite(cluster.lng)) return;
        const first = cluster.items[0];
        const count = cluster.items.length;
        const icon = count > 1
          ? window.L.divIcon({
              html: `<div style="background:#1d4ed8;color:#fff;border:2px solid #fff;border-radius:9999px;width:34px;height:34px;display:flex;align-items:center;justify-content:center;font-weight:700;box-shadow:0 4px 14px rgba(0,0,0,.2)">${count}</div>`,
              className: "",
              iconSize: [34, 34],
            })
          : window.L.divIcon({
              html: `<div style="background:#059669;color:#fff;border:2px solid #fff;border-radius:9999px;width:16px;height:16px;box-shadow:0 2px 8px rgba(0,0,0,.2)"></div>`,
              className: "",
              iconSize: [16, 16],
            });
        const marker = window.L.marker([cluster.lat, cluster.lng], { icon });
        if (count === 1) {
          marker.bindPopup(
            `<b>${first.title}</b><br/>$${Number(first.price || 0).toLocaleString("en-US")} · ${first.city}, ${first.district}<br/><a href="/listing/${first.id}" target="_blank" rel="noopener">Відкрити</a>`
          );
        } else {
          const listHtml = cluster.items
            .slice(0, 4)
            .map((item) => `<li><a href="/listing/${item.id}" target="_blank" rel="noopener">${item.title}</a></li>`)
            .join("");
          marker.bindPopup(`<b>${count} об'єктів</b><ul style="margin:6px 0 0 18px;padding:0">${listHtml}</ul>`);
        }
        state.layer.addLayer(marker);
      });
      mapCount.textContent = `На мапі: ${state.listings.length} об'єктів`;
    }

    async function refreshMapListings() {
      if (!state.map || state.refreshing) return;
      state.refreshing = true;
      if (mapSkeleton) mapSkeleton.style.display = "grid";
      try {
        const res = await fetch(buildListingsApiUrl(filters, 200), { credentials: "omit" });
        const data = await res.json();
        state.listings = Array.isArray(data?.listings) ? data.listings : [];
        renderMapClusters();
      } catch (_err) {
        mapCount.textContent = "Не вдалося завантажити об'єкти для мапи";
      } finally {
        if (mapSkeleton) mapSkeleton.style.display = "none";
        state.refreshing = false;
      }
    }

    function syncOverlayFromFilters() {
      const values = readFilters(filters);
      mapCity.value = values.city || "Всі";
      mapType.value = values.propertyType || "Всі типи";
      mapEoselya.checked = !!values.onlyEOselya;
    }

    async function ensureMap() {
      if (state.map) return;
      await ensureLeafletLoaded();
      state.map = window.L.map(mapCanvas, { zoomControl: true }).setView([49.0, 31.2], 6);
      window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution: "&copy; OpenStreetMap",
      }).addTo(state.map);
      state.layer = window.L.layerGroup().addTo(state.map);
      state.map.on("zoomend moveend", renderMapClusters);
      syncOverlayFromFilters();
      await refreshMapListings();
    }

    function applyViewMode(mode) {
      localStorage.setItem(VIEW_MODE_KEY, mode);
      styleModeButtons(mode);
      if (mode === "map") {
        mapShell.classList.remove("hidden");
        mapShell.classList.remove("is-hidden");
        requestAnimationFrame(() => {
          mapShell.style.opacity = "1";
        });
        hiddenBlocks.forEach((block) => { block.style.display = "none"; });
        ensureMap().then(() => {
          setTimeout(() => state.map?.invalidateSize(), 80);
        });
      } else {
        mapShell.classList.add("is-hidden");
        mapShell.style.opacity = "0";
        setTimeout(() => mapShell.classList.add("hidden"), 210);
        hiddenBlocks.forEach((block) => { block.style.display = ""; });
      }
    }

    modeListBtn.addEventListener("click", () => applyViewMode("list"));
    modeMapBtn.addEventListener("click", () => applyViewMode("map"));
    mapApply.addEventListener("click", () => {
      applyFilters({
        city: mapCity.value,
        propertyType: mapType.value,
        onlyEOselya: !!mapEoselya.checked,
      }, filters);
      refreshMapListings();
    });

    const refreshDebounced = (() => {
      let t = null;
      return () => {
        if (t) clearTimeout(t);
        t = setTimeout(() => {
          syncOverlayFromFilters();
          refreshMapListings();
        }, 350);
      };
    })();
    [
      filters.citySelect,
      filters.propertyTypeSelect,
      filters.districtInput,
      filters.eoselyaCheckbox,
      filters.minPrice,
      filters.maxPrice,
      filters.minRooms,
      filters.maxRooms,
      filters.minArea,
      filters.maxArea,
    ].filter(Boolean).forEach((el) => {
      el.addEventListener("change", refreshDebounced);
      el.addEventListener("input", refreshDebounced);
    });

    applyViewMode(localStorage.getItem(VIEW_MODE_KEY) === "map" ? "map" : "list");
  }

  function attachTrustBadgesToCards() {
    const listingLinks = [...document.querySelectorAll('a[href*="/listing/"]')];
    if (!listingLinks.length) return;
    const listingIds = [...new Set(listingLinks
      .map((link) => {
        const match = (link.getAttribute("href") || "").match(/\/listing\/(\d+)/);
        return match ? Number(match[1]) : null;
      })
      .filter((id) => Number.isInteger(id) && id > 0))];
    if (!listingIds.length) return;

    const signature = listingIds.join(",");
    if (attachTrustBadgesToCards._lastSignature === signature) {
      const hasAllBadges = listingIds.every((id) => {
        const link = listingLinks.find((candidate) => {
          const match = (candidate.getAttribute("href") || "").match(/\/listing\/(\d+)/);
          return match && Number(match[1]) === id;
        });
        const card = link?.closest(".group, article, .rounded-2xl, .rounded-xl, .listing-card, [data-listing-id]") || link?.parentElement;
        return !!card?.querySelector('[data-role="trust2-badges"]');
      });
      if (hasAllBadges) return;
    }
    attachTrustBadgesToCards._lastSignature = signature;

    fetch(`${resolveApiBase()}/api/listings?status=published&ids=${listingIds.join(",")}&limit=200`, { credentials: "omit" })
      .then((r) => r.json())
      .then((payload) => {
        const byId = new Map((payload.listings || []).map((item) => [Number(item.id), item]));
        listingLinks.forEach((link) => {
          const href = link.getAttribute("href") || "";
          const match = href.match(/\/listing\/(\d+)/);
          if (!match) return;
          const listing = byId.get(Number(match[1]));
          if (!listing) return;
          const card = link.closest(".group, article, .rounded-2xl, .rounded-xl, .listing-card, [data-listing-id]") || link.parentElement;
          if (!card) return;
          const existingWrap = card.querySelector('[data-role="trust2-badges"]');
          const wrap = existingWrap || document.createElement("div");
          wrap.setAttribute("data-role", "trust2-badges");
          wrap.className = "mb-2 p-2 rounded-xl border border-slate-200 bg-slate-50";
          const qualitySignals = [];
          const proofChips = [];
          const trustChips = [];
          const freshnessLabel = Number.isFinite(listing.freshness_hours_ago)
            ? `🕒 Оновлено ${listing.freshness_hours_ago} год тому`
            : "🕒 Оновлено нещодавно";
          const verifiedLabel = Number.isFinite(listing.verified_days_ago)
            ? `🛡️ Перевірено ${listing.verified_days_ago} дн тому`
            : "🛡️ Перевірено модератором";
          const riskMap = {
            high: { label: "Ризик дубля: високий", tone: "bg-red-50 border-red-200 text-red-700" },
            medium: { label: "Ризик дубля: середній", tone: "bg-amber-50 border-amber-200 text-amber-700" },
            low: { label: "Ризик дубля: низький", tone: "bg-emerald-50 border-emerald-200 text-emerald-700" },
          };
          const risk = riskMap[listing.duplicate_risk] || riskMap.low;
          const proofToneMap = {
            documents: "bg-emerald-100 border-emerald-300 text-emerald-800",
            video: "bg-indigo-100 border-indigo-300 text-indigo-800",
            inspector: "bg-blue-100 border-blue-300 text-blue-800",
            tour360: "bg-violet-100 border-violet-300 text-violet-800",
            owner: "bg-emerald-50 border-emerald-200 text-emerald-700",
            phone: "bg-sky-50 border-sky-200 text-sky-700",
          };
          const evidenceLevelLabel = {
            strong: "Рівень перевірки: високий",
            medium: "Рівень перевірки: середній",
            basic: "Рівень перевірки: базовий",
            none: "Рівень перевірки: мінімальний",
          };
          const verificationProofs = Array.isArray(listing.verification_proofs) ? listing.verification_proofs : [];
          verificationProofs.slice(0, 4).forEach((proof) => {
            const tone = proofToneMap[proof.code] || "bg-slate-100 border-slate-300 text-slate-800";
            proofChips.push(`<span class="text-[10px] px-2 py-1 rounded-full border font-bold ${tone} glass-badge tooltip-chip" data-tooltip="${(proof.details || proof.label || "").replace(/"/g, "&quot;")}">${proof.label}</span>`);
          });
          qualitySignals.push(freshnessLabel);
          qualitySignals.push(verifiedLabel);
          qualitySignals.push(risk.label);
          const evidenceScore = Number(listing.trust_evidence_score || 0);
          const evidenceLevel = evidenceLevelLabel[listing.trust_evidence_level] || evidenceLevelLabel.none;
          trustChips.push(`⭐ ${evidenceLevel} (${Math.max(0, Math.min(100, evidenceScore))}/100)`);
          if (listing.agency_verified) trustChips.push("🏢 Перевірене агентство");
          if (!proofChips.length) {
            if (listing.verified_docs) proofChips.push('<span class="text-[10px] px-2 py-1 rounded-full border font-bold bg-emerald-100 border-emerald-300 text-emerald-800">Перевірено по документах</span>');
            if (listing.has_video_tour) proofChips.push('<span class="text-[10px] px-2 py-1 rounded-full border font-bold bg-indigo-100 border-indigo-300 text-indigo-800">Перевірено по відео</span>');
            if (listing.has_photo_tour) proofChips.push('<span class="text-[10px] px-2 py-1 rounded-full border font-bold bg-violet-100 border-violet-300 text-violet-800">Є 360°/фото-тур</span>');
          }
          const proofDetails = verificationProofs.length
            ? verificationProofs.slice(0, 3).map((proof) => proof.details).filter(Boolean).join(" · ")
            : "Модерація профілю, контактів і документів.";
          wrap.innerHTML = `
            <div class="flex flex-wrap gap-1.5 mb-1">${proofChips.join("") || '<span class="text-[10px] px-2 py-1 rounded-full border border-slate-300 bg-slate-100 text-slate-700 font-semibold glass-badge">Докази перевірки оновлюються</span>'}</div>
            <div class="flex flex-wrap gap-1.5 mb-1">${qualitySignals
              .map((chip, idx) => {
                if (idx === 2) return `<span class="text-[10px] px-2 py-1 rounded-full border font-bold ${risk.tone} glass-badge tooltip-chip" data-tooltip="Оцінка дублювання за схожими параметрами">${chip}</span>`;
                return `<span class="text-[10px] px-2 py-1 rounded-full bg-blue-50 border border-blue-200 text-blue-700 font-bold glass-badge">${chip}</span>`;
              })
              .join("")}</div>
            <div class="flex flex-wrap gap-1.5">${trustChips
              .map((chip) => `<span class="text-[10px] px-2 py-1 rounded-full bg-slate-100 border border-slate-300 text-slate-700 font-semibold glass-badge tooltip-chip" data-tooltip="Індикатор перевірки об'єкта">${chip}</span>`)
              .join("")}</div>
            <p class="mt-1 text-[11px] text-slate-500">Як перевірено: ${proofDetails} Дата перевірки: ${listing.trust_verified_at ? new Date(listing.trust_verified_at).toLocaleDateString("uk-UA") : "—"}.</p>
          `;
          if (!existingWrap) {
            card.insertAdjacentElement("afterbegin", wrap);
          }
        });
      })
      .catch(() => {});
  }

  function init() {
    const filters = findFilters();
    if (!filters) return false;
    injectMarketplaceEffectsStyles();
    installListingsSearchProxy();
    trackListingMode(filters);
    const panel = buildPanel(filters);
    installMapFirstMode(filters, panel);
    decorateListingCardsWithEffects();
    attachTrustBadgesToCards();
    applyUsMarketplaceSkin();
    const listingObserver = new MutationObserver(() => {
      decorateListingCardsWithEffects();
      attachTrustBadgesToCards();
      applyUsMarketplaceSkin();
    });
    listingObserver.observe(document.body, { childList: true, subtree: true });
    setTimeout(() => listingObserver.disconnect(), 20000);
    return true;
  }

  if (!init()) {
    const observer = new MutationObserver(() => {
      if (init()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    setTimeout(() => observer.disconnect(), 12000);
  }
})();
