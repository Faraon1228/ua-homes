import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_SORT,
  STORAGE_KEYS,
  filterAndSortProperties,
  resolveSortByForEOselya,
} from "./realEstateFilters";

const MOCK_PROPERTIES = [
  {
    id: 1,
    title: "Сучасна 2-кімнатна квартира, ЖК 'Грінвіль'",
    city: "Київ",
    district: "Печерський",
    price: 125000,
    rooms: 2,
    area: 68,
    eOselya: true,
    images: [
      "https://images.unsplash.com/photo-1560185007-c5ca9d2c014d?auto=format&fit=crop&w=1200&q=80",
      "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=1200&q=80",
    ],
  },
  {
    id: 2,
    title: "Видова смарт-квартира біля метро",
    city: "Київ",
    district: "Голосіївський",
    price: 48000,
    rooms: 1,
    area: 32,
    eOselya: true,
    images: [
      "https://images.unsplash.com/photo-1493809842364-78817add7ffb?auto=format&fit=crop&w=1200&q=80",
      "https://images.unsplash.com/photo-1484154218962-a197022b5858?auto=format&fit=crop&w=1200&q=80",
    ],
  },
  {
    id: 3,
    title: "Простора 3-к квартира для родини",
    city: "Львів",
    district: "Франківський",
    price: 95000,
    rooms: 3,
    area: 85,
    eOselya: false,
    images: [
      "https://images.unsplash.com/photo-1484154218962-a197022b5858?auto=format&fit=crop&w=1200&q=80",
      "https://images.unsplash.com/photo-1493809842364-78817add7ffb?auto=format&fit=crop&w=1200&q=80",
    ],
  },
];

const FALLBACK_IMAGE =
  "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1200' height='675' viewBox='0 0 1200 675'%3E%3Crect width='1200' height='675' fill='%23e2e8f0'/%3E%3Cpath d='M0 500h1200v175H0z' fill='%23cbd5e1'/%3E%3Ccircle cx='360' cy='260' r='70' fill='%23cbd5e1'/%3E%3Cpath d='M250 445l125-115 90 78 72-60 155 132H250z' fill='%2394a3b8'/%3E%3Ctext x='600' y='565' text-anchor='middle' font-family='Arial,sans-serif' font-size='28' fill='%23475569'%3EUA-Dim%3C/text%3E%3C/svg%3E";

const KEYWORD_SEARCH_KEY = "re.keywordSearch";
const SAVED_SEARCHES_KEY = "re.savedSearches";
const MAX_SAVED_SEARCHES = 10;

const QUICK_SCENARIOS = [
  {
    label: "Київ · єОселя · до $130k",
    filters: { cityFilter: "Київ", onlyEOselya: true, maxPrice: "130000", minRooms: "1" },
  },
  {
    label: "Львів · 2+ кімнати · до $110k",
    filters: { cityFilter: "Львів", onlyEOselya: false, maxPrice: "110000", minRooms: "2" },
  },
  {
    label: "Київ · 1-2 кімнати · 35-65 м²",
    filters: {
      cityFilter: "Київ",
      onlyEOselya: false,
      minRooms: "1",
      maxRooms: "2",
      minArea: "35",
      maxArea: "65",
    },
  },
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

function normalizeImageSrc(src) {
  if (!src) return "";
  return src.includes("images.unsplash.com") ? FALLBACK_IMAGE : src;
}

function getStored(key, fallback) {
  if (typeof window === "undefined") return fallback;
  const value = window.localStorage.getItem(key);
  return value ?? fallback;
}

function safeParseJSON(value, fallback) {
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function describeSearchState(filters, keywordSearch) {
  const parts = [];
  if (filters.cityFilter && filters.cityFilter !== "Всі") parts.push(filters.cityFilter);
  if (filters.onlyEOselya) parts.push("єОселя");
  if (filters.minRooms || filters.maxRooms) {
    parts.push(`${filters.minRooms || "1"}-${filters.maxRooms || "∞"} кімн.`);
  }
  if (filters.minPrice || filters.maxPrice) {
    parts.push(`$${filters.minPrice || "0"}-${filters.maxPrice || "∞"}`);
  }
  if (filters.minArea || filters.maxArea) {
    parts.push(`${filters.minArea || "0"}-${filters.maxArea || "∞"} м²`);
  }
  if (keywordSearch.trim()) parts.push(`"${keywordSearch.trim()}"`);
  return parts.length ? parts.join(" · ") : "Спробуйте швидкий сценарій або ключове слово.";
}

function PhotoGallery({ images, title }) {
  const [index, setIndex] = useState(0);
  const items = Array.isArray(images) ? images.map(normalizeImageSrc).filter(Boolean) : [];

  if (!items.length) {
    return (
      <div className="flex h-56 items-center justify-center bg-gray-200 text-5xl text-gray-400">
        🏠
      </div>
    );
  }

  const prev = (e) => {
    e.stopPropagation();
    setIndex((current) => (current - 1 + items.length) % items.length);
  };

  const next = (e) => {
    e.stopPropagation();
    setIndex((current) => (current + 1) % items.length);
  };

  return (
    <div className="relative h-56 overflow-hidden bg-gray-200">
      <img src={items[index]} alt={title} className="h-full w-full object-cover" />
      {items.length > 1 && (
        <>
          <button
            type="button"
            onClick={prev}
            className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full bg-black/50 px-3 py-1 text-white hover:bg-black/70"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={next}
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-black/50 px-3 py-1 text-white hover:bg-black/70"
          >
            ›
          </button>
        </>
      )}
    </div>
  );
}

export default function RealEstateApp() {
  const keywordInputRef = useRef(null);
  const [cityFilter, setCityFilter] = useState(() => getStored("re.cityFilter", "Всі"));
  const [onlyEOselya, setOnlyEOselya] = useState(
    () => getStored("re.onlyEOselya", "false") === "true"
  );
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(
    () => getStored("re.showFavoritesOnly", "false") === "true"
  );
  const [minPrice, setMinPrice] = useState(() => getStored("re.minPrice", ""));
  const [maxPrice, setMaxPrice] = useState(() => getStored("re.maxPrice", ""));
  const [minRooms, setMinRooms] = useState(() => getStored("re.minRooms", ""));
  const [maxRooms, setMaxRooms] = useState(() => getStored("re.maxRooms", ""));
  const [minArea, setMinArea] = useState(() => getStored("re.minArea", ""));
  const [maxArea, setMaxArea] = useState(() => getStored("re.maxArea", ""));
  const [sortBy, setSortBy] = useState(() => getStored("re.sortBy", DEFAULT_SORT));
  const [keywordDraft, setKeywordDraft] = useState(() => getStored(KEYWORD_SEARCH_KEY, ""));
  const [keywordSearch, setKeywordSearch] = useState(() => getStored(KEYWORD_SEARCH_KEY, ""));
  const [savedSearches, setSavedSearches] = useState(() =>
    safeParseJSON(getStored(SAVED_SEARCHES_KEY, "[]"), [])
  );
  const [favoriteIds, setFavoriteIds] = useState(() => {
    try {
      const raw = getStored("re.favoriteIds", "[]");
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });

  const cities = useMemo(
    () => ["Всі", ...Array.from(new Set(MOCK_PROPERTIES.map((p) => p.city)))],
    []
  );

  useEffect(() => {
    setSortBy((prev) => resolveSortByForEOselya(prev, onlyEOselya));
  }, [onlyEOselya]);

  useEffect(() => {
    setKeywordDraft(keywordSearch);
    window.localStorage.setItem(KEYWORD_SEARCH_KEY, keywordSearch);
  }, [keywordSearch]);

  useEffect(() => {
    window.localStorage.setItem("re.cityFilter", cityFilter);
    window.localStorage.setItem("re.onlyEOselya", String(onlyEOselya));
    window.localStorage.setItem("re.showFavoritesOnly", String(showFavoritesOnly));
    window.localStorage.setItem("re.minPrice", minPrice);
    window.localStorage.setItem("re.maxPrice", maxPrice);
    window.localStorage.setItem("re.minRooms", minRooms);
    window.localStorage.setItem("re.maxRooms", maxRooms);
    window.localStorage.setItem("re.minArea", minArea);
    window.localStorage.setItem("re.maxArea", maxArea);
    window.localStorage.setItem("re.sortBy", sortBy);
    window.localStorage.setItem("re.favoriteIds", JSON.stringify(favoriteIds));
    window.localStorage.setItem(SAVED_SEARCHES_KEY, JSON.stringify(savedSearches.slice(0, MAX_SAVED_SEARCHES)));
  }, [
    cityFilter,
    onlyEOselya,
    showFavoritesOnly,
    minPrice,
    maxPrice,
    minRooms,
    maxRooms,
    minArea,
    maxArea,
    sortBy,
    favoriteIds,
    savedSearches,
  ]);

  const searchFilters = useMemo(
    () => ({
      cityFilter,
      onlyEOselya,
      minPrice,
      maxPrice,
      minRooms,
      maxRooms,
      minArea,
      maxArea,
      sortBy,
      keywordSearch,
    }),
    [cityFilter, onlyEOselya, minPrice, maxPrice, minRooms, maxRooms, minArea, maxArea, sortBy, keywordSearch]
  );

  const filteredProperties = useMemo(
    () => filterAndSortProperties(MOCK_PROPERTIES, searchFilters),
    [searchFilters]
  );
  const favoriteProperties = useMemo(
    () => MOCK_PROPERTIES.filter((property) => favoriteIds.includes(property.id)),
    [favoriteIds]
  );
  const compareProperties = useMemo(() => favoriteProperties.slice(0, 3), [favoriteProperties]);
  const bestValueId = useMemo(() => {
    if (!compareProperties.length) return null;
    return compareProperties.reduce((best, item) => {
      if (!best) return item.id;
      const bestItem = compareProperties.find((candidate) => candidate.id === best);
      const bestScore = Number(bestItem?.price || 0) / Math.max(Number(bestItem?.area || 1), 1);
      const currentScore = Number(item.price || 0) / Math.max(Number(item.area || 1), 1);
      return currentScore < bestScore ? item.id : best;
    }, null);
  }, [compareProperties]);
  const compareSummary = useMemo(() => {
    if (!compareProperties.length) {
      return "Додайте кілька обраних об'єктів, щоб порівняти їх тут.";
    }
    return `Порівнюємо ${compareProperties.length} обраних об'єктів. Кращий value позначено окремо.`;
  }, [compareProperties]);
  const visibleProperties = useMemo(
    () => (showFavoritesOnly ? filteredProperties.filter((p) => favoriteIds.includes(p.id)) : filteredProperties),
    [filteredProperties, favoriteIds, showFavoritesOnly]
  );
  const favoriteStats = useMemo(() => {
    if (!favoriteProperties.length) return { count: 0, avgPrice: 0, verifiedCount: 0 };
    const totalPrice = favoriteProperties.reduce((sum, item) => sum + item.price, 0);
    return {
      count: favoriteProperties.length,
      avgPrice: Math.round(totalPrice / favoriteProperties.length),
      verifiedCount: favoriteProperties.filter((item) => item.eOselya).length,
    };
  }, [favoriteProperties]);
  const searchSummary = useMemo(
    () => describeSearchState(searchFilters, keywordSearch),
    [searchFilters, keywordSearch]
  );
  const activeFilters = useMemo(() => {
    const items = [];
    if (cityFilter !== "Всі") items.push({ key: "cityFilter", label: `Місто: ${cityFilter}` });
    if (onlyEOselya) items.push({ key: "onlyEOselya", label: "єОселя" });
    if (minPrice || maxPrice) {
      items.push({ key: "price", label: `Ціна: $${minPrice || "0"}-${maxPrice || "∞"}` });
    }
    if (minRooms || maxRooms) {
      items.push({ key: "rooms", label: `Кімнати: ${minRooms || "1"}-${maxRooms || "∞"}` });
    }
    if (minArea || maxArea) {
      items.push({ key: "area", label: `Площа: ${minArea || "0"}-${maxArea || "∞"} м²` });
    }
    if (keywordSearch.trim()) items.push({ key: "keywordSearch", label: `Пошук: "${keywordSearch.trim()}"` });
    return items;
  }, [cityFilter, onlyEOselya, minPrice, maxPrice, minRooms, maxRooms, minArea, maxArea, keywordSearch]);

  const toggleFavorite = (property) => {
    setFavoriteIds((current) =>
      current.includes(property.id)
        ? current.filter((id) => id !== property.id)
        : [...current, property.id]
    );
  };

  const resetFilters = () => {
    setCityFilter("Всі");
    setOnlyEOselya(false);
    setShowFavoritesOnly(false);
    setMinPrice("");
    setMaxPrice("");
    setMinRooms("");
    setMaxRooms("");
    setMinArea("");
    setMaxArea("");
    setSortBy(DEFAULT_SORT);
  };

  const oneClickChips = useMemo(
    () => [
      { label: "Київ", action: () => setCityFilter("Київ") },
      { label: "Львів", action: () => setCityFilter("Львів") },
      { label: "єОселя", action: () => setOnlyEOselya((current) => !current) },
      { label: "1-2 кімн.", action: () => { setMinRooms("1"); setMaxRooms("2"); } },
      { label: "до $100k", action: () => { setMinPrice(""); setMaxPrice("100000"); } },
      { label: "35+ м²", action: () => { setMinArea("35"); setMaxArea(""); } },
      { label: "Релевантні", action: () => setSortBy("relevance") },
      { label: "Скинути все", action: resetFilters },
    ],
    [resetFilters]
  );

  const clearSavedFilters = () => {
    STORAGE_KEYS.forEach((key) => window.localStorage.removeItem(key));
    window.localStorage.removeItem("re.showFavoritesOnly");
    window.localStorage.removeItem("re.favoriteIds");
    window.localStorage.removeItem(SAVED_SEARCHES_KEY);
    window.localStorage.removeItem(KEYWORD_SEARCH_KEY);
    resetFilters();
    setFavoriteIds([]);
    setKeywordDraft("");
    setKeywordSearch("");
    setSavedSearches([]);
  };

  const applyScenario = (scenario) => {
    const { filters } = scenario;
    if ("cityFilter" in filters) setCityFilter(filters.cityFilter);
    if ("onlyEOselya" in filters) setOnlyEOselya(filters.onlyEOselya);
    if ("minPrice" in filters) setMinPrice(filters.minPrice);
    if ("maxPrice" in filters) setMaxPrice(filters.maxPrice);
    if ("minRooms" in filters) setMinRooms(filters.minRooms);
    if ("maxRooms" in filters) setMaxRooms(filters.maxRooms);
    if ("minArea" in filters) setMinArea(filters.minArea);
    if ("maxArea" in filters) setMaxArea(filters.maxArea);
    if ("sortBy" in filters) setSortBy(filters.sortBy);
    if ("keywordSearch" in filters) {
      setKeywordDraft(filters.keywordSearch);
      setKeywordSearch(filters.keywordSearch);
    }
  };

  const saveCurrentSearch = () => {
    const defaultName = `${cityFilter || "Всі"} · ${onlyEOselya ? "єОселя" : "всі"} · ${
      new Date().toLocaleDateString("uk-UA")
    }`;
    const name = (window.prompt("Назва для збереженого пошуку:", defaultName) || "").trim();
    if (!name) return;
    const entry = {
      id: `search_${Date.now()}`,
      name,
      filters: { ...searchFilters },
      createdAt: Date.now(),
    };
    setSavedSearches((current) => [entry, ...current].slice(0, MAX_SAVED_SEARCHES));
  };

  const applyKeywordSearch = () => {
    setKeywordSearch(keywordDraft.trim());
  };

  const clearKeywordSearch = () => {
    setKeywordDraft("");
    setKeywordSearch("");
  };

  const openSavedSearch = (entry) => {
    const next = entry.filters || {};
    if ("cityFilter" in next) setCityFilter(next.cityFilter);
    if ("onlyEOselya" in next) setOnlyEOselya(next.onlyEOselya);
    if ("minPrice" in next) setMinPrice(next.minPrice);
    if ("maxPrice" in next) setMaxPrice(next.maxPrice);
    if ("minRooms" in next) setMinRooms(next.minRooms);
    if ("maxRooms" in next) setMaxRooms(next.maxRooms);
    if ("minArea" in next) setMinArea(next.minArea);
    if ("maxArea" in next) setMaxArea(next.maxArea);
    if ("sortBy" in next) setSortBy(next.sortBy);
    if ("keywordSearch" in next) {
      setKeywordDraft(next.keywordSearch || "");
      setKeywordSearch(next.keywordSearch || "");
    }
  };

  const clearActiveFilter = (key) => {
    if (key === "cityFilter") setCityFilter("Всі");
    if (key === "onlyEOselya") setOnlyEOselya(false);
    if (key === "price") {
      setMinPrice("");
      setMaxPrice("");
    }
    if (key === "rooms") {
      setMinRooms("");
      setMaxRooms("");
    }
    if (key === "area") {
      setMinArea("");
      setMaxArea("");
    }
    if (key === "keywordSearch") {
      setKeywordDraft("");
      setKeywordSearch("");
    }
  };

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key !== "/") return;
      const target = event.target;
      if (
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable
      ) {
        return;
      }
      event.preventDefault();
      keywordInputRef.current?.focus();
      keywordInputRef.current?.select?.();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 font-sans">
      <section className="max-w-7xl mx-auto px-4 mt-8">
        <div className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
          <h1 className="text-2xl font-bold mb-4">Пошук нерухомості в Україні</h1>
          <div className="mb-4 rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3">
            <p className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Активний запит</p>
            <p className="mt-1 text-sm text-slate-700">{searchSummary}</p>
          </div>

          <div className="mb-5 sticky top-4 z-20 rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-sm backdrop-blur">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-xs font-black uppercase tracking-wide text-slate-500">Активні фільтри</p>
                <p className="mt-1 text-sm text-slate-600">Швидко вимикайте окремі умови або застосовуйте one-click chips.</p>
              </div>
              <button
                type="button"
                onClick={resetFilters}
                className="min-h-[44px] rounded-2xl bg-slate-900 px-4 text-sm font-bold text-white hover:bg-blue-700 transition"
              >
                Скинути все
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {activeFilters.length ? (
                activeFilters.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => clearActiveFilter(item.key)}
                    className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-blue-50 hover:border-blue-200 transition"
                    aria-label={`Прибрати фільтр ${item.label}`}
                  >
                    {item.label}
                    <span className="text-slate-400">✕</span>
                  </button>
                ))
              ) : (
                <p className="text-sm text-slate-500">Активних фільтрів немає.</p>
              )}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {oneClickChips.map((chip) => (
                <button
                  key={chip.label}
                  type="button"
                  onClick={chip.action}
                  className="px-3 py-1.5 rounded-full border border-blue-200 bg-white text-blue-700 text-xs font-semibold hover:bg-blue-100 transition"
                >
                  {chip.label}
                </button>
              ))}
            </div>
          </div>

          <div className="mb-5 rounded-2xl border border-blue-100 bg-blue-50 p-4">
            <div className="flex items-center justify-between gap-3 mb-2">
              <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Full-text пошук</p>
              <button
                type="button"
                onClick={clearKeywordSearch}
                className="px-2.5 py-1.5 rounded-lg bg-white border border-blue-200 text-blue-700 text-xs font-semibold hover:bg-blue-100 transition"
              >
                Очистити
              </button>
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                ref={keywordInputRef}
                type="text"
                value={keywordDraft}
                onChange={(e) => setKeywordDraft(e.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    applyKeywordSearch();
                  }
                }}
                placeholder="ЖК, метро, вулиця, ремонт, тераса..."
                className="flex-1 p-3 bg-white border border-blue-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
              <button
                type="button"
                onClick={applyKeywordSearch}
                className="px-4 py-3 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 transition"
              >
                Застосувати
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {KEYWORD_SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => {
                    const current = keywordDraft.trim();
                    const nextValue = current ? `${current} ${suggestion}` : suggestion;
                    setKeywordDraft(nextValue);
                    setKeywordSearch(nextValue);
                    window.requestAnimationFrame(() => {
                      keywordInputRef.current?.focus();
                      keywordInputRef.current?.select?.();
                    });
                  }}
                  className="px-3 py-1.5 rounded-full border border-blue-200 bg-white text-blue-700 text-xs font-semibold hover:bg-blue-100 transition"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>

          <div className="mb-5">
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="text-xs font-bold uppercase tracking-wide text-gray-500">Швидкі сценарії</p>
              <button
                type="button"
                onClick={saveCurrentSearch}
                className="text-sm font-semibold text-blue-600 hover:text-blue-700 underline"
              >
                Зберегти поточний пошук
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {QUICK_SCENARIOS.map((scenario) => (
                <button
                  key={scenario.label}
                  type="button"
                  onClick={() => applyScenario(scenario)}
                  className="px-3 py-2 rounded-xl bg-gray-100 text-gray-800 text-sm font-medium hover:bg-gray-200 transition"
                >
                  {scenario.label}
                </button>
              ))}
            </div>
            {!!savedSearches.length && (
              <div className="mt-4 flex flex-wrap gap-2">
                {savedSearches.slice(0, 4).map((entry) => (
                  <span
                    key={entry.id}
                    className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-700 border border-blue-100"
                  >
                    <button
                      type="button"
                      onClick={() => openSavedSearch(entry)}
                      className="hover:text-blue-700"
                    >
                      {entry.name}
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setSavedSearches((current) => current.filter((item) => item.id !== entry.id))
                      }
                      className="text-rose-500 hover:text-rose-700"
                      aria-label={`Видалити пошук ${entry.name}`}
                    >
                      ✕
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            <div>
              <label className="text-xs font-bold text-gray-500 uppercase">Місто</label>
              <select
                value={cityFilter}
                onChange={(e) => setCityFilter(e.target.value)}
                className="w-full p-3 bg-gray-50 border border-gray-200 rounded-xl"
              >
                {cities.map((city) => (
                  <option key={city} value={city}>
                    {city === "Всі" ? "Всі міста України" : city}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs font-bold text-gray-500 uppercase">Ціна, $</label>
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="number"
                  min="0"
                  placeholder="від"
                  value={minPrice}
                  onChange={(e) => setMinPrice(e.target.value)}
                  className="p-3 bg-gray-50 border border-gray-200 rounded-xl"
                />
                <input
                  type="number"
                  min="0"
                  placeholder="до"
                  value={maxPrice}
                  onChange={(e) => setMaxPrice(e.target.value)}
                  className="p-3 bg-gray-50 border border-gray-200 rounded-xl"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-bold text-gray-500 uppercase">Кімнати</label>
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="number"
                  min="0"
                  placeholder="від"
                  value={minRooms}
                  onChange={(e) => setMinRooms(e.target.value)}
                  className="p-3 bg-gray-50 border border-gray-200 rounded-xl"
                />
                <input
                  type="number"
                  min="0"
                  placeholder="до"
                  value={maxRooms}
                  onChange={(e) => setMaxRooms(e.target.value)}
                  className="p-3 bg-gray-50 border border-gray-200 rounded-xl"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-bold text-gray-500 uppercase">Площа, м²</label>
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="number"
                  min="0"
                  placeholder="від"
                  value={minArea}
                  onChange={(e) => setMinArea(e.target.value)}
                  className="p-3 bg-gray-50 border border-gray-200 rounded-xl"
                />
                <input
                  type="number"
                  min="0"
                  placeholder="до"
                  value={maxArea}
                  onChange={(e) => setMaxArea(e.target.value)}
                  className="p-3 bg-gray-50 border border-gray-200 rounded-xl"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-bold text-gray-500 uppercase">Сортування</label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="w-full p-3 bg-gray-50 border border-gray-200 rounded-xl"
              >
                <option value="relevance">Найбільш релевантні</option>
                <option value="price-asc">Дешевші спочатку</option>
                <option value="price-desc">Дорожчі спочатку</option>
                <option value="area-desc">Більша площа спочатку</option>
                <option value="area-asc">Менша площа спочатку</option>
              </select>
              <p className="text-xs text-gray-500 mt-1">Авто: дешевші спочатку для єОселя</p>
            </div>
          </div>

          <div className="flex items-center justify-between mt-4 gap-4 flex-wrap">
            <label className="flex items-center space-x-3">
              <input
                type="checkbox"
                checked={onlyEOselya}
                onChange={(e) => setOnlyEOselya(e.target.checked)}
                className="w-5 h-5"
              />
              <span className="font-medium text-gray-700">
                Тільки об&apos;єкти під <span className="text-blue-600 font-bold">єОселя</span>
              </span>
            </label>

            <div className="flex items-center gap-4">
              <button
                onClick={resetFilters}
                className="text-blue-600 font-bold underline hover:text-blue-700"
              >
                Скинути фільтри
              </button>
              <button
                onClick={clearSavedFilters}
                className="text-red-600 font-bold underline hover:text-red-700"
              >
                Очистити localStorage
              </button>
            </div>
          </div>

          <div className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 p-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-xs font-black uppercase tracking-wide text-rose-600">Обрані</p>
                <p className="mt-1 text-sm text-slate-600">
                  {favoriteStats.count
                    ? `Збережено ${favoriteStats.count} об'єктів, середня ціна $${favoriteStats.avgPrice.toLocaleString(
                        "uk-UA"
                      )}, ${favoriteStats.verifiedCount} під єОселя.`
                    : "Додавайте об'єкти в обране, щоб повертатися до них швидше."}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setShowFavoritesOnly((current) => !current)}
                  className={`min-h-[44px] rounded-2xl px-4 text-sm font-bold transition ${
                    showFavoritesOnly
                      ? "bg-rose-600 text-white hover:bg-rose-700"
                      : "bg-white text-rose-700 border border-rose-200 hover:bg-rose-100"
                  }`}
                >
                  {showFavoritesOnly ? "❤️ Показую лише обрані" : "🤍 Показати лише обрані"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setFavoriteIds([]);
                    setShowFavoritesOnly(false);
                  }}
                  className="min-h-[44px] rounded-2xl border border-rose-200 px-4 text-sm font-bold text-rose-700 hover:bg-rose-100 transition"
                >
                  Очистити обрані
                </button>
              </div>
            </div>

            <div className="mt-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Порівняння обраних</p>
                  <p className="mt-1 text-sm text-slate-600">
                    Швидкий shortlist для прийняття рішення: ціна, площа, кімнати, єОселя.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowFavoritesOnly(true)}
                  className="min-h-[44px] rounded-2xl bg-slate-900 px-4 text-sm font-bold text-white hover:bg-blue-700 transition"
                >
                  Порівняти зараз
                </button>
              </div>

              <div className="mt-3 rounded-xl bg-slate-50 border border-slate-200 p-3">
                <p className="text-sm text-slate-700">{compareSummary}</p>
              </div>

              {!!compareProperties.length && (
                <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
                  {compareProperties.map((property) => (
                    <div
                      key={property.id}
                      className={`rounded-xl border p-3 ${
                        property.id === bestValueId
                          ? "border-emerald-300 bg-emerald-50"
                          : "border-slate-200 bg-white"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-bold text-slate-900">{property.title}</p>
                          <p className="text-xs text-slate-500 mt-1">
                            {property.city}, {property.district}
                          </p>
                        </div>
                        {property.id === bestValueId && (
                          <span className="text-[10px] px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 font-semibold">
                            BEST VALUE
                          </span>
                        )}
                      </div>
                      <div className="mt-3 space-y-1.5 text-sm text-slate-700">
                        <div className="flex justify-between gap-3">
                          <span>Ціна</span>
                          <b>${property.price.toLocaleString("uk-UA")}</b>
                        </div>
                        <div className="flex justify-between gap-3">
                          <span>Площа</span>
                          <b>{property.area} м²</b>
                        </div>
                        <div className="flex justify-between gap-3">
                          <span>Кімнати</span>
                          <b>{property.rooms}</b>
                        </div>
                        <div className="flex justify-between gap-3">
                          <span>єОселя</span>
                          <b>{property.eOselya ? "Так" : "Ні"}</b>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {!!favoriteProperties.length && (
              <div className="mt-4 flex flex-wrap gap-2">
                {favoriteProperties.slice(0, 4).map((property) => (
                  <span
                    key={property.id}
                    className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-700 border border-rose-100"
                  >
                    {property.title}
                    <button
                      type="button"
                      onClick={() => toggleFavorite(property)}
                      className="text-rose-500 hover:text-rose-700"
                      aria-label={`Прибрати ${property.title} з обраного`}
                    >
                      ✕
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      <main className="max-w-7xl mx-auto px-4 my-8">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {visibleProperties.map((property) => (
            <div
              key={property.id}
              className="bg-white rounded-2xl overflow-hidden shadow-sm border border-gray-100"
            >
              <div className="relative">
                <PhotoGallery images={property.images} title={property.title} />
                <button
                  type="button"
                  onClick={() => toggleFavorite(property)}
                  className="absolute right-3 top-3 rounded-full bg-white/90 px-3 py-1 text-sm font-bold shadow hover:bg-white"
                  aria-label={
                    favoriteIds.includes(property.id)
                      ? `Прибрати ${property.title} з обраного`
                      : `Додати ${property.title} в обране`
                  }
                >
                  {favoriteIds.includes(property.id) ? "❤️" : "🤍"}
                </button>
              </div>
              <div className="p-5">
                <h3 className="font-bold text-lg mb-2">{property.title}</h3>
                <div className="flex gap-4 text-sm text-gray-500 font-medium mb-4">
                  <span>{property.rooms} кімн.</span>
                  <span>•</span>
                  <span>{property.area} м²</span>
                </div>
                <p className="text-2xl font-black text-blue-600">
                  ${property.price.toLocaleString("uk-UA")}
                </p>
              </div>
            </div>
          ))}
        </div>

        {visibleProperties.length === 0 && (
          <div className="text-center py-16 bg-white rounded-2xl border border-dashed border-gray-200 mt-6">
            <p className="text-gray-400 font-medium text-lg">
              {showFavoritesOnly
                ? "У вас ще немає обраних об'єктів."
                : "За вказаними фільтрами нічого не знайдено."}
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
