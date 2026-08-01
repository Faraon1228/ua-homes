(() => {
  const SAVED_SEARCHES_KEY = "ua_homes_saved_searches_v1";
  const LEAD_SESSION_KEY = "uah.leadSessionId";
  const KEYWORD_SEARCH_KEY = "ua_homes_keyword_search_v1";
  const MAX_SAVED_SEARCHES = 10;

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

  function fireInput(el) {
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function resolveApiBase() {
    if (window.UA_HOMES_API) return window.UA_HOMES_API;
    const configured = "__UA_HOMES_API__";
    if (configured && configured !== "__UA_HOMES_API__") return configured;
    const host = window.location.hostname;
    if (!host || window.location.protocol === "file:") return "http://localhost:5050";
    if (host === "localhost" || host === "127.0.0.1") return "http://localhost:5050";
    return "";
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
        if (!keyword) return originalFetch(input, init);

        const rawUrl = typeof input === "string" ? input : input?.url;
        if (!rawUrl || !/\/api\/listings(\?|$)/.test(rawUrl)) {
          return originalFetch(input, init);
        }

        const parsed = new URL(rawUrl, window.location.href);
        parsed.searchParams.set("search", keyword);
        const currentSort = parsed.searchParams.get("sort");
        if (!currentSort || currentSort === "newest" || currentSort === "price-desc") {
          parsed.searchParams.set("sort", "relevance");
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

  function buildPanel(filters) {
    if (document.querySelector('[data-ua-homes-market-upgrade="1"]')) return;
    const hostSection = filters.citySelect.closest("section") || filters.citySelect.closest("div");
    if (!hostSection) return;

    const panel = document.createElement("section");
    panel.setAttribute("data-ua-homes-market-upgrade", "1");
    panel.className = "max-w-7xl mx-auto px-4 mt-4 mb-4";
    panel.innerHTML = `
      <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
        <div class="flex flex-col gap-5">
          <div>
            <h2 class="text-lg font-bold text-slate-900">Розумний пошук (як на топ-порталах)</h2>
            <p class="text-sm text-slate-600 mt-1">Швидкі сценарії, розумні підказки району, збережені пошуки і trust-блоки.</p>
          </div>

          <div>
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 mb-2">Швидкі сценарії</p>
            <div class="flex flex-wrap gap-2" data-role="quick-scenarios"></div>
          </div>

          <div class="p-3 rounded-xl bg-blue-50 border border-blue-100">
            <div class="flex items-center justify-between gap-3 mb-2">
              <p class="text-xs font-bold uppercase tracking-wide text-blue-700">Full-text пошук</p>
              <button type="button" class="px-2.5 py-1.5 rounded-lg bg-white border border-blue-200 text-blue-700 text-xs font-semibold hover:bg-blue-100 transition" data-role="clear-keyword-search">Очистити</button>
            </div>
            <div class="flex flex-col sm:flex-row gap-2">
              <input type="text" class="flex-1 px-3 py-2 rounded-lg border border-blue-200 bg-white text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-400" placeholder="ЖК, метро, вулиця, ремонт, тераса..." data-role="keyword-search-input"/>
              <button type="button" class="px-3 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition" data-role="apply-keyword-search">Застосувати</button>
            </div>
            <p class="text-xs text-blue-700 mt-2">Працює з релевантністю. Після застосування сторінка оновиться.</p>
          </div>

          <div class="p-3 rounded-xl bg-slate-50 border border-slate-200">
            <div class="flex items-center justify-between gap-3 mb-2">
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Розумні підказки району</p>
              <button type="button" class="px-2.5 py-1.5 rounded-lg bg-white border border-slate-300 text-slate-700 text-xs font-semibold hover:bg-slate-100 transition" data-role="clear-district">Очистити район</button>
            </div>
            <p class="text-sm text-slate-600 mb-2">Для міста <span class="font-semibold text-slate-900" data-role="district-city-label">—</span>:</p>
            <div class="flex flex-wrap gap-2" data-role="district-hints"></div>
          </div>

          <div>
            <div class="flex items-center justify-between gap-3 mb-2">
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Збережені пошуки</p>
              <button type="button" class="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition" data-role="save-current-search">Зберегти поточний пошук</button>
            </div>
            <div class="flex flex-wrap gap-2" data-role="saved-scenarios"></div>
          </div>

          <div>
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 mb-2">Популярні маршрути пошуку</p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2" data-role="popular-routes"></div>
          </div>

          <div>
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 mb-2">Перевірені агентства / забудовники</p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3" data-role="trusted-partners"></div>
          </div>
        </div>
      </div>
    `;
    hostSection.insertAdjacentElement("afterend", panel);

    const quickWrap = panel.querySelector('[data-role="quick-scenarios"]');
    const savedWrap = panel.querySelector('[data-role="saved-scenarios"]');
    const saveButton = panel.querySelector('[data-role="save-current-search"]');
    const districtWrap = panel.querySelector('[data-role="district-hints"]');
    const districtLabel = panel.querySelector('[data-role="district-city-label"]');
    const clearDistrictButton = panel.querySelector('[data-role="clear-district"]');
    const keywordSearchInput = panel.querySelector('[data-role="keyword-search-input"]');
    const applyKeywordSearchButton = panel.querySelector('[data-role="apply-keyword-search"]');
    const clearKeywordSearchButton = panel.querySelector('[data-role="clear-keyword-search"]');
    const popularRoutesWrap = panel.querySelector('[data-role="popular-routes"]');
    const trustedPartnersWrap = panel.querySelector('[data-role="trusted-partners"]');

    QUICK_SCENARIOS.forEach((scenario) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "px-3 py-2 rounded-lg bg-slate-100 text-slate-800 text-sm font-medium hover:bg-slate-200 transition";
      button.textContent = scenario.label;
      button.addEventListener("click", () => applyFilters(scenario.filters, filters));
      quickWrap.appendChild(button);
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

    TRUSTED_PARTNERS.forEach((partner) => {
      const card = document.createElement("div");
      card.className = "p-3 rounded-xl border border-emerald-200 bg-emerald-50";
      card.innerHTML = `
        <div class="flex items-start justify-between gap-3">
          <div>
            <p class="text-sm font-bold text-slate-900">${partner.name}</p>
            <p class="text-xs text-slate-600 mt-0.5">${partner.kind} · ${partner.city}</p>
          </div>
          <span class="text-[10px] px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 font-semibold">TRUST+</span>
        </div>
        <p class="text-xs text-slate-700 mt-2">${partner.specialization}</p>
        <div class="flex flex-wrap gap-1.5 mt-2">${partner.trustSignals
          .map((signal) => `<span class="text-[10px] px-2 py-1 rounded-full bg-white border border-emerald-200 text-emerald-700 font-medium">${signal}</span>`)
          .join("")}</div>
      `;
      const cta = document.createElement("button");
      cta.type = "button";
      cta.className = "mt-3 px-3 py-1.5 rounded-lg bg-white border border-emerald-300 text-emerald-700 text-xs font-semibold hover:bg-emerald-100 transition";
      cta.textContent = `Показати пропозиції в ${partner.city}`;
      cta.addEventListener("click", () => applyFilters({ city: partner.city, listingMode: "sale" }, filters));
      card.appendChild(cta);
      trustedPartnersWrap.appendChild(card);
    });

    saveButton.addEventListener("click", () => {
      const current = readFilters(filters);
      const defaultName = `${current.city || "Всі"} · ${current.onlyEOselya ? "єОселя" : "всі"} · ${new Date().toLocaleDateString("uk-UA")}`;
      const name = (window.prompt("Назва для збереженого пошуку:", defaultName) || "").trim();
      if (!name) return;
      setSavedSearches([{ id: `search_${Date.now()}`, name, filters: current, createdAt: Date.now() }, ...getSavedSearches()]);
      renderSaved();
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
        }
      });
    }
    applyKeywordSearchButton?.addEventListener("click", applyKeywordSearch);
    clearKeywordSearchButton?.addEventListener("click", () => {
      localStorage.removeItem(KEYWORD_SEARCH_KEY);
      if (keywordSearchInput) keywordSearchInput.value = "";
      window.location.reload();
    });

    filters.citySelect.addEventListener("change", renderDistrictHints);
    renderDistrictHints();
    renderSaved();
  }

  function init() {
    const filters = findFilters();
    if (!filters) return false;
    installListingsSearchProxy();
    buildPanel(filters);
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
