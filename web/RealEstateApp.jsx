import React, { useEffect, useMemo, useRef, useState } from "./react-shim";
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

const SMART_SEARCH_PATH = "smart-search.html";

const INITIAL_LISTING_IMAGE_FIELDS = ["", "", ""];

function createInitialListingForm() {
  return {
    title: "",
    city: "Київ",
    district: "",
    propertyType: "квартира",
    conditionType: "вторинка",
    listingType: "sale",
    price: "",
    rooms: "",
    area: "",
    floor: "1",
    totalFloors: "1",
    yearBuilt: "",
    eOselya: false,
    description: "",
    images: [...INITIAL_LISTING_IMAGE_FIELDS],
  };
}

function normalizeImageSrc(src) {
  if (!src) return "";
  return src.includes("images.unsplash.com") ? FALLBACK_IMAGE : src;
}

function mapListingToProperty(listing) {
  const images = Array.isArray(listing?.images)
    ? listing.images.filter(Boolean)
    : [];

  return {
    id: listing?.id ?? 0,
    title: listing?.title || "Оголошення без назви",
    city: listing?.city || "Київ",
    district: listing?.district || "",
    price: Number(listing?.price || 0),
    rooms: Number(listing?.rooms || 0),
    area: Number(listing?.area || 0),
    eOselya: Boolean(listing?.e_oselya ?? listing?.eOselya),
    images,
    description: listing?.description || "",
    status: listing?.status || "published",
  };
}

function mapListingToForm(listing) {
  const images = Array.isArray(listing?.images) ? listing.images.filter(Boolean).slice(0, 8) : [];
  while (images.length < INITIAL_LISTING_IMAGE_FIELDS.length) {
    images.push("");
  }

  return {
    title: listing?.title || "",
    city: listing?.city || "Київ",
    district: listing?.district || "",
    propertyType: listing?.property_type || listing?.propertyType || "квартира",
    conditionType: listing?.condition_type || listing?.conditionType || "вторинка",
    listingType: listing?.listing_type || listing?.listingType || "sale",
    price: listing?.price != null ? String(listing.price) : "",
    rooms: listing?.rooms != null ? String(listing.rooms) : "",
    area: listing?.area != null ? String(listing.area) : "",
    floor: listing?.floor != null ? String(listing.floor) : "1",
    totalFloors: listing?.total_floors != null ? String(listing.total_floors) : "1",
    yearBuilt: listing?.year_built != null ? String(listing.year_built) : "",
    eOselya: Boolean(listing?.e_oselya ?? listing?.eOselya),
    description: listing?.description || "",
    images,
  };
}

function getListingStatusLabel(listing) {
  if (listing?.status === "published" && listing?.listing_status === "active") return "Активне";
  if (listing?.status === "published") return "Опубліковано";
  if (listing?.moderation_status === "approved") return "Підтверджено";
  return "На модерації";
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

function getStoredJSON(key, fallback) {
  if (typeof window === "undefined") return fallback;
  try {
    const value = window.localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
}

function getApiBaseUrl() {
  if (typeof window === "undefined") return "/api-backend";
  const hostname = window.location.hostname || "";
  if (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "0.0.0.0") {
    return "http://127.0.0.1:5050/api";
  }
  return "/api-backend";
}

function getApiUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getApiBaseUrl()}${normalizedPath}`;
}

function allowMockCatalogFallback() {
  if (typeof window === "undefined") return true;
  return window.location.protocol === "file:";
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

function SmartSearchPage({
  keywordInputRef,
  keywordDraft,
  setKeywordDraft,
  applyKeywordSearch,
  clearKeywordSearch,
  searchSummary,
  oneClickChips,
  activeFilters,
  clearActiveFilter,
  visibleProperties,
  filteredProperties,
  favoriteIds,
  toggleFavorite,
  showFavoritesOnly,
  setShowFavoritesOnly,
  saveCurrentSearch,
  resetFilters,
}) {
  const previewProperties = visibleProperties.slice(0, 6);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-50 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-4">
          <a
            href="real-estate-demo.html"
            className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-bold text-slate-700 transition hover:bg-slate-100"
          >
            ← Повернутися
          </a>
          <div className="text-center">
            <div className="text-lg font-black tracking-tight text-slate-900">UA-DIM</div>
            <div className="text-xs font-medium text-slate-500">Розумний пошук</div>
          </div>
          <a
            href="real-estate-demo.html"
            className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700"
          >
            Повний каталог
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8">
        <div className="grid gap-6 lg:grid-cols-12">
          <section className="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm lg:col-span-8">
            <p className="text-xs font-black uppercase tracking-[0.28em] text-blue-600">РОЗУМНИЙ ПОШУК</p>
            <h1 className="mt-3 text-4xl font-black tracking-tight text-slate-900 sm:text-5xl">UA-DIM</h1>
            <p className="mt-4 max-w-2xl text-base leading-relaxed text-slate-600">
              Швидкий пошук по тексту, району, ЖК чи метро. Зберігайте запити, перемикайте сценарії та одразу
              дивіться релевантні результати.
            </p>
            <div className="mt-6 rounded-[28px] border border-blue-100 bg-blue-50 p-4">
              <div className="flex flex-col gap-3 sm:flex-row">
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
                  placeholder="ЖК, метро, район, ремонт..."
                  className="flex-1 rounded-2xl border border-blue-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                />
                <button
                  type="button"
                  onClick={applyKeywordSearch}
                  className="rounded-2xl bg-blue-600 px-5 py-3 text-sm font-bold text-white transition hover:bg-blue-700"
                >
                  Шукати
                </button>
              </div>
              <p className="mt-3 text-sm text-slate-700">{searchSummary}</p>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {oneClickChips.slice(0, 6).map((chip) => (
                <button
                  key={chip.label}
                  type="button"
                  onClick={chip.action}
                  className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                >
                  {chip.label}
                </button>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={saveCurrentSearch}
                className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700"
              >
                Зберегти запит
              </button>
              <button
                type="button"
                onClick={resetFilters}
                className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700 transition hover:bg-slate-50"
              >
                Скинути
              </button>
              <button
                type="button"
                onClick={() => setShowFavoritesOnly((current) => !current)}
                className={`rounded-2xl px-4 py-2 text-sm font-bold transition ${
                  showFavoritesOnly
                    ? "bg-rose-600 text-white hover:bg-rose-700"
                    : "border border-rose-200 bg-white text-rose-700 hover:bg-rose-50"
                }`}
              >
                {showFavoritesOnly ? "Лише обрані" : "Показати обрані"}
              </button>
              <button
                type="button"
                onClick={clearKeywordSearch}
                className="rounded-2xl border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-bold text-blue-700 transition hover:bg-blue-100"
              >
                Очистити текст
              </button>
            </div>
          </section>

          <aside className="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm lg:col-span-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-black uppercase tracking-wide text-slate-500">Поточний стан</p>
                <p className="mt-1 text-2xl font-black text-slate-900">Пошук</p>
              </div>
              <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700">
                {filteredProperties.length} знайдено
              </span>
            </div>

            <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-black uppercase tracking-wide text-slate-500">Фільтри</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {activeFilters.length ? (
                  activeFilters.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => clearActiveFilter(item.key)}
                      className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-blue-200 hover:bg-blue-50"
                    >
                      {item.label}
                    </button>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">Активних фільтрів немає.</p>
                )}
              </div>
            </div>

            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-4">
              <p className="text-xs font-black uppercase tracking-wide text-rose-600">Обрані</p>
              <p className="mt-1 text-sm text-slate-600">
                {favoriteIds.length ? `Збережено ${favoriteIds.length} об'єктів.` : "Додайте об'єкти в обране."}
              </p>
            </div>
          </aside>
        </div>

        <div className="mt-8 flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-black uppercase tracking-wide text-slate-500">Релевантні результати</p>
            <h2 className="mt-1 text-2xl font-black text-slate-900">
              {visibleProperties.length ? `Показано ${previewProperties.length} з ${visibleProperties.length}` : "Нічого не знайдено"}
            </h2>
          </div>
          <a
            href="real-estate-demo.html"
            className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700"
          >
            Відкрити повний каталог
          </a>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
          {previewProperties.map((property) => (
            <div key={property.id} className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
              <PhotoGallery images={property.images} title={property.title} />
              <div className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="line-clamp-2 text-lg font-bold text-slate-900">{property.title}</h3>
                    <p className="mt-1 text-sm text-slate-500">
                      {property.city} • {property.district}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleFavorite(property)}
                    className="rounded-full bg-slate-100 px-3 py-1 text-sm font-bold text-slate-700"
                  >
                    {favoriteIds.includes(property.id) ? "❤️" : "🤍"}
                  </button>
                </div>
                <div className="mt-4 flex items-center justify-between gap-3">
                  <div className="text-sm text-slate-600">
                    {property.rooms} кімн. • {property.area} м²
                  </div>
                  <div className="text-xl font-black text-blue-600">${property.price.toLocaleString("uk-UA")}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
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
    <div className="relative h-60 overflow-hidden bg-slate-200">
      <img src={items[index]} alt={title} loading="lazy" decoding="async" className="h-full w-full object-cover" />
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
  const [authToken, setAuthToken] = useState(() => getStored("uaDim.authToken", ""));
  const [currentUser, setCurrentUser] = useState(() => getStoredJSON("uaDim.currentUser", null));
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({ name: "", email: "", password: "" });
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authSuccess, setAuthSuccess] = useState("");
  const [showCreateListingModal, setShowCreateListingModal] = useState(false);
  const [editingListingId, setEditingListingId] = useState(null);
  const [listingForm, setListingForm] = useState(() => createInitialListingForm());
  const [listingSubmitting, setListingSubmitting] = useState(false);
  const [listingMessage, setListingMessage] = useState("");
  const [myListings, setMyListings] = useState([]);
  const [myListingsLoading, setMyListingsLoading] = useState(false);
  const [selectedListingFiles, setSelectedListingFiles] = useState([]);
  const [selectedListingFilePreviews, setSelectedListingFilePreviews] = useState([]);
  const [liveCatalogListings, setLiveCatalogListings] = useState([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");

  const catalogProperties = useMemo(() => {
    if (liveCatalogListings.length) return liveCatalogListings;
    if (allowMockCatalogFallback() && !catalogError) return MOCK_PROPERTIES;
    return [];
  }, [catalogError, liveCatalogListings]);

  const cities = useMemo(
    () => ["Всі", ...Array.from(new Set(catalogProperties.map((p) => p.city)))],
    [catalogProperties]
  );
  const activeMyListingsCount = useMemo(
    () => myListings.filter((item) => item.status === "published" && item.listing_status === "active").length,
    [myListings]
  );

  useEffect(() => {
    setSortBy((prev) => resolveSortByForEOselya(prev, onlyEOselya));
  }, [onlyEOselya]);

  useEffect(() => {
    setKeywordDraft(keywordSearch);
    window.localStorage.setItem(KEYWORD_SEARCH_KEY, keywordSearch);
  }, [keywordSearch]);

  const loadCatalogListings = async () => {
    setCatalogLoading(true);
    setCatalogError("");
    try {
      const response = await fetch(getApiUrl("/listings?status=published&limit=60&sort=newest"));
      if (!response.ok) throw new Error("Не вдалося завантажити оголошення");
      const data = await response.json();
      const rows = Array.isArray(data.listings) ? data.listings : [];
      const mapped = rows.map(mapListingToProperty);
      setLiveCatalogListings(mapped);
    } catch (error) {
      setCatalogError(error.message || "Не вдалося завантажити оголошення");
      setLiveCatalogListings([]);
    } finally {
      setCatalogLoading(false);
    }
  };

  const mergeListingIntoCatalog = (listing) => {
    if (!listing?.id) return;
    const mappedListing = mapListingToProperty(listing);
    setLiveCatalogListings((current) => {
      const next = current.filter((item) => item.id !== mappedListing.id);
      return [mappedListing, ...next];
    });
  };

  useEffect(() => {
    loadCatalogListings();
  }, []);

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

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (authToken) {
      window.localStorage.setItem("uaDim.authToken", authToken);
    } else {
      window.localStorage.removeItem("uaDim.authToken");
    }
    if (currentUser) {
      window.localStorage.setItem("uaDim.currentUser", JSON.stringify(currentUser));
    } else {
      window.localStorage.removeItem("uaDim.currentUser");
    }
  }, [authToken, currentUser]);

  const loadMyListings = async () => {
    if (!authToken) {
      setMyListings([]);
      return;
    }
    setMyListingsLoading(true);
    setListingMessage("");
    try {
      const response = await fetch(getApiUrl("/listings?mine=1&status=all&limit=100&sort=newest"), {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) throw new Error("Не вдалося завантажити оголошення");
      const data = await response.json();
      const rows = Array.isArray(data.listings) ? data.listings : [];
      setMyListings(rows);
    } catch (error) {
      setListingMessage(error.message || "Не вдалося завантажити оголошення");
    } finally {
      setMyListingsLoading(false);
    }
  };

  useEffect(() => {
    if (!authToken) {
      setMyListings([]);
      return;
    }
    loadMyListings();
  }, [authToken, currentUser?.id]);

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
    () => filterAndSortProperties(catalogProperties, searchFilters),
    [catalogProperties, searchFilters]
  );
  const favoriteProperties = useMemo(
    () => catalogProperties.filter((property) => favoriteIds.includes(property.id)),
    [catalogProperties, favoriteIds]
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
  const eOselyaCount = useMemo(
    () => filteredProperties.filter((property) => property.eOselya).length,
    [filteredProperties]
  );
  const smartSearchMode =
    typeof window !== "undefined" && window.location.pathname.endsWith(SMART_SEARCH_PATH);
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

  const updateAuthForm = (field, value) => {
    setAuthForm((current) => ({ ...current, [field]: value }));
  };

  const handleAuthSubmit = async (event) => {
    event.preventDefault();
    setAuthLoading(true);
    setAuthError("");
    setAuthSuccess("");
    try {
      const response = await fetch(getApiUrl(authMode === "login" ? "/auth/login" : "/auth/register"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          authMode === "login"
            ? {
                email: authForm.email.trim(),
                password: authForm.password,
              }
            : {
                name: authForm.name.trim(),
                email: authForm.email.trim(),
                password: authForm.password,
              }
        ),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || "Не вдалося виконати дію");
      }
      setAuthToken(result.token || "");
      setCurrentUser(result.user || null);
      setAuthSuccess(authMode === "login" ? "Увійшли в профіль" : "Обліковий запис створено");
      setAuthForm({ name: "", email: "", password: "" });
    } catch (error) {
      setAuthError(error.message || "Не вдалося виконати дію");
    } finally {
      setAuthLoading(false);
    }
  };

  const logoutProfile = () => {
    setAuthToken("");
    setCurrentUser(null);
    setAuthSuccess("Ви вийшли з профілю");
    setMyListings([]);
    setListingMessage("");
    setEditingListingId(null);
    setListingForm(createInitialListingForm());
    setSelectedListingFiles([]);
    setSelectedListingFilePreviews([]);
  };

  const closeListingModal = () => {
    setShowCreateListingModal(false);
    setEditingListingId(null);
    setListingForm(createInitialListingForm());
    setSelectedListingFiles([]);
    setSelectedListingFilePreviews([]);
  };

  const openCreateListingModal = () => {
    setEditingListingId(null);
    setListingForm(createInitialListingForm());
    setSelectedListingFiles([]);
    setSelectedListingFilePreviews([]);
    setListingMessage("");
    setShowCreateListingModal(true);
  };

  const openEditListingModal = (listing) => {
    setEditingListingId(listing.id);
    setListingForm(mapListingToForm(listing));
    setSelectedListingFiles([]);
    setSelectedListingFilePreviews([]);
    setListingMessage("");
    setShowCreateListingModal(true);
  };

  const updateListingField = (field, value) => {
    setListingForm((current) => ({ ...current, [field]: value }));
  };

  const updateListingImage = (index, value) => {
    setListingForm((current) => {
      const images = [...current.images];
      images[index] = value;
      return { ...current, images };
    });
  };

  const addListingImageField = () => {
    setListingForm((current) => ({ ...current, images: [...current.images, ""] }));
  };

  const removeListingImageField = (index) => {
    setListingForm((current) => ({
      ...current,
      images: current.images.filter((_, itemIndex) => itemIndex !== index),
    }));
  };

  const handleListingFileSelection = (event) => {
    const files = Array.from(event.target.files || []).filter((file) => file.type.startsWith("image/"));
    setSelectedListingFiles(files);
  };

  useEffect(() => {
    if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
      setSelectedListingFilePreviews([]);
      return undefined;
    }

    const previews = selectedListingFiles.map((file) => ({
      id: `${file.name}-${file.size}-${file.lastModified}`,
      name: file.name,
      src: URL.createObjectURL(file),
    }));

    setSelectedListingFilePreviews(previews);

    return () => {
      previews.forEach((preview) => URL.revokeObjectURL(preview.src));
    };
  }, [selectedListingFiles]);

  const readListingFileAsDataUrl = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error(`Не вдалося прочитати файл ${file.name}`));
      reader.readAsDataURL(file);
    });
  };

  const handleCreateListing = async (event) => {
    event.preventDefault();
    if (!authToken) {
      setListingMessage("Спочатку увійдіть у профіль");
      return;
    }
    setListingSubmitting(true);
    setListingMessage("");
    try {
      const imageUrls = listingForm.images.filter(Boolean).slice(0, 8);
      const uploadedImageDataUrls = selectedListingFiles.length
        ? await Promise.all(selectedListingFiles.map((file) => readListingFileAsDataUrl(file)))
        : [];
      const payload = {
        title: listingForm.title.trim(),
        city: listingForm.city.trim(),
        district: listingForm.district.trim(),
        propertyType: listingForm.propertyType,
        conditionType: listingForm.conditionType,
        listingType: listingForm.listingType,
        price: Number(listingForm.price),
        rooms: Number(listingForm.rooms),
        area: Number(listingForm.area),
        floor: Number(listingForm.floor) || 1,
        totalFloors: Number(listingForm.totalFloors) || 1,
        yearBuilt: listingForm.yearBuilt ? Number(listingForm.yearBuilt) : undefined,
        eOselya: Boolean(listingForm.eOselya),
        description: listingForm.description.trim(),
        listingStatus: "active",
        source: "owner",
        publishNow: true,
        images: [...uploadedImageDataUrls, ...imageUrls].slice(0, 8),
      };

      const isEditing = Boolean(editingListingId);
      const response = await fetch(getApiUrl(isEditing ? `/listings/${editingListingId}` : "/listings"), {
        method: isEditing ? "PATCH" : "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || "Не вдалося створити оголошення");
      }
      mergeListingIntoCatalog(result.listing);
      setListingMessage(
        isEditing
          ? "Оголошення оновлено та залишено опублікованим."
          : `Оголошення створено${result.listing?.status === "published" ? " і вже опубліковане" : " і надіслане на модерацію"}.`
      );
      setEditingListingId(null);
      setListingForm(createInitialListingForm());
      setSelectedListingFiles([]);
      setSelectedListingFilePreviews([]);
      setShowCreateListingModal(false);
      if (!isEditing && result.listing?.id && result.listing?.status === "published") {
        window.location.assign(`/listing/${result.listing.id}`);
        return;
      }
      await Promise.all([loadMyListings(), loadCatalogListings()]);
    } catch (error) {
      setListingMessage(error.message || "Не вдалося зберегти оголошення");
    } finally {
      setListingSubmitting(false);
    }
  };

  if (smartSearchMode) {
    return React.createElement(SmartSearchPage, {
      keywordInputRef,
      keywordDraft,
      setKeywordDraft,
      applyKeywordSearch,
      clearKeywordSearch,
      searchSummary,
      oneClickChips,
      activeFilters,
      clearActiveFilter,
      visibleProperties,
      filteredProperties,
      favoriteIds,
      toggleFavorite,
      showFavoritesOnly,
      setShowFavoritesOnly,
      saveCurrentSearch,
      resetFilters,
    });
  }

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
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-50 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-slate-900 via-slate-800 to-blue-700 text-sm font-black text-white shadow-lg shadow-slate-900/20">
              UA
            </div>
            <div>
              <div className="text-lg font-black tracking-tight text-slate-900">UA-Dim</div>
              <div className="text-xs font-medium text-slate-500">Пошук нерухомості</div>
            </div>
          </div>

          <nav className="hidden items-center gap-2 lg:flex">
            {["Купити", "Орендувати", "Новобудови", "єОселя"].map((item) => (
              <span
                key={item}
                className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm font-semibold text-slate-700"
              >
                {item}
              </span>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            <a
              href={SMART_SEARCH_PATH}
              className="inline-flex rounded-2xl border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-bold text-blue-700 transition hover:bg-blue-100"
            >
              Розумний пошук
            </a>
            <button
              type="button"
              onClick={() => setShowFavoritesOnly((current) => !current)}
              className="hidden rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-bold text-rose-700 transition hover:bg-rose-100 sm:inline-flex"
            >
              Обрані {favoriteIds.length}
            </button>
            <button
              type="button"
              onClick={saveCurrentSearch}
              className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700"
            >
              + Зберегти пошук
            </button>
          </div>
        </div>
      </header>

      <section className="bg-[radial-gradient(circle_at_top_left,rgba(37,99,235,.16),transparent_35%),linear-gradient(180deg,#0f172a_0%,#1e293b_58%,#f8fafc_58%)]">
        <div className="mx-auto max-w-7xl px-4 pb-10 pt-10 lg:pb-14">
          <div className="grid gap-6 lg:grid-cols-12">
            <div className="rounded-[32px] border border-white/10 bg-slate-900/95 p-6 shadow-2xl shadow-slate-900/20 backdrop-blur lg:col-span-7">
              <p className="text-xs font-black uppercase tracking-[0.28em] text-blue-300">
                Search-first marketplace
              </p>
              <h1 className="mt-3 text-4xl font-black leading-tight text-white sm:text-5xl">
                Нерухомість України
              </h1>
              <p className="mt-4 max-w-2xl text-base leading-relaxed text-slate-300">
                Знаходьте об&apos;єкти за містом, районом, площею й бюджетом, зберігайте пошук, порівнюйте
                обрані та швидко відсікайте неактуальні варіанти.
              </p>

              <div className="mt-6 flex flex-wrap gap-2">
                <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white">
                  Пошук відразу по всій Україні
                </span>
                <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white">
                  єОселя 3% / 7%
                </span>
                <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white">
                  Порівняння обраних
                </span>
                <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white">
                  Швидкі сценарії
                </span>
              </div>

              <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: "Знайдено", value: visibleProperties.length, note: "об'єктів" },
                  { label: "У фільтрі", value: filteredProperties.length, note: "після умов" },
                  { label: "Обрані", value: favoriteStats.count, note: "збережено" },
                  { label: "єОселя", value: eOselyaCount, note: "пропозицій" },
                ].map((metric) => (
                  <div key={metric.label} className="rounded-[24px] border border-white/10 bg-white/10 p-4">
                    <div className="text-xs font-black uppercase tracking-wide text-blue-200">{metric.label}</div>
                    <div className="mt-1 text-3xl font-black text-white">{metric.value}</div>
                    <div className="mt-1 text-xs font-semibold text-slate-300">{metric.note}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-[32px] border border-slate-200 bg-white p-5 shadow-xl shadow-slate-200/70 lg:col-span-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Активний запит</p>
                  <p className="mt-1 text-2xl font-black text-slate-900">UA-DIM</p>
                </div>
                <button
                  type="button"
                  onClick={clearKeywordSearch}
                  className="rounded-2xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-bold text-blue-700 transition hover:bg-blue-100"
                >
                  Очистити слово
                </button>
              </div>

              <div className="mt-4 rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3">
                <p className="text-[11px] font-black uppercase tracking-wide text-blue-700">Поточний запит</p>
                <p className="mt-1 text-sm leading-relaxed text-slate-700">{searchSummary}</p>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {oneClickChips.slice(0, 6).map((chip) => (
                  <button
                    key={chip.label}
                    type="button"
                    onClick={chip.action}
                    className="rounded-full border border-blue-200 bg-white px-3 py-1.5 text-xs font-semibold text-blue-700 transition hover:bg-blue-100"
                  >
                    {chip.label}
                  </button>
                ))}
              </div>

              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Ключові слова</p>
                  <span className="text-xs font-semibold text-slate-400">Швидке автодоповнення</span>
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
                      className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={saveCurrentSearch}
                  className="min-h-[44px] rounded-2xl bg-slate-900 px-4 text-sm font-bold text-white transition hover:bg-blue-700"
                >
                  Зберегти поточний пошук
                </button>
                <button
                  type="button"
                  onClick={resetFilters}
                  className="min-h-[44px] rounded-2xl border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700 transition hover:bg-slate-50"
                >
                  Скинути фільтри
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 pb-12">
        <div className="grid gap-6 lg:grid-cols-12">
          <aside className="space-y-6 lg:col-span-4 lg:sticky lg:top-24 self-start">
            <div className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Профіль власника</p>
                  <h2 className="mt-1 text-xl font-black text-slate-900">
                    {currentUser ? currentUser.name : "Увійдіть у профіль"}
                  </h2>
                </div>
                <span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${currentUser ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-700"}`}>
                  {currentUser ? "Авторизовано" : "Потрібен вхід"}
                </span>
              </div>

              <p className="mt-2 text-sm text-slate-600">
                Створюйте оголошення з профілю, одразу публікуйте їх на сайті та редагуйте без переходу в адмінку.
              </p>

              {authError ? <div className="mt-3 rounded-2xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{authError}</div> : null}
              {authSuccess ? <div className="mt-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{authSuccess}</div> : null}
              {listingMessage ? <div className="mt-3 rounded-2xl border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{listingMessage}</div> : null}

              {!currentUser ? (
                <form onSubmit={handleAuthSubmit} className="mt-4 space-y-3">
                  {authMode === "register" ? (
                    <input
                      type="text"
                      value={authForm.name}
                      onChange={(event) => updateAuthForm("name", event.target.value)}
                      placeholder="Ваше ім'я"
                      className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                    />
                  ) : null}
                  <input
                    type="email"
                    value={authForm.email}
                    onChange={(event) => updateAuthForm("email", event.target.value)}
                    placeholder="Email"
                    className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                  />
                  <input
                    type="password"
                    value={authForm.password}
                    onChange={(event) => updateAuthForm("password", event.target.value)}
                    placeholder="Пароль"
                    className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                  />
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="submit"
                      disabled={authLoading}
                      className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-70"
                    >
                      {authLoading ? "Зачекайте..." : authMode === "login" ? "Увійти" : "Зареєструватися"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setAuthMode((current) => (current === "login" ? "register" : "login"))}
                      className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
                    >
                      {authMode === "login" ? "Створити акаунт" : "Уже є акаунт"}
                    </button>
                  </div>
                </form>
              ) : (
                <div className="mt-4 space-y-3">
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                    <p className="text-xs font-black uppercase tracking-wide text-slate-500">Профіль</p>
                    <p className="mt-1 font-semibold text-slate-900">{currentUser.email}</p>
                    <p className="mt-1 text-xs text-slate-500">У профілі видно активні оголошення, їх статус і доступне швидке редагування.</p>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-3">
                      <p className="text-[11px] font-black uppercase tracking-wide text-emerald-700">Активні</p>
                      <p className="mt-1 text-2xl font-black text-emerald-700">{activeMyListingsCount}</p>
                    </div>
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                      <p className="text-[11px] font-black uppercase tracking-wide text-slate-500">Усього</p>
                      <p className="mt-1 text-2xl font-black text-slate-900">{myListings.length}</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={openCreateListingModal}
                      className="rounded-2xl bg-blue-600 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700"
                    >
                      + Створити оголошення
                    </button>
                    <button
                      type="button"
                      onClick={logoutProfile}
                      className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
                    >
                      Вийти
                    </button>
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-black uppercase tracking-wide text-slate-500">Мої оголошення</p>
                      {myListingsLoading ? (
                        <span className="text-xs text-slate-500">Завантаження…</span>
                      ) : (
                        <span className="rounded-full bg-white px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                          {activeMyListingsCount} активних
                        </span>
                      )}
                    </div>
                    {myListings.length ? (
                      <ul className="mt-3 space-y-2">
                        {myListings.map((item) => (
                          <li key={item.id} className="rounded-xl border border-slate-200 bg-white p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <p className="text-sm font-semibold text-slate-900">{item.title}</p>
                                <p className="mt-1 text-xs text-slate-500">{item.city}, {item.district}</p>
                                <p className="mt-2 text-xs font-semibold text-slate-500">
                                  ${Number(item.price || 0).toLocaleString("uk-UA")} • {item.rooms} кімн. • {item.area} м²
                                </p>
                              </div>
                              <span className="rounded-full bg-blue-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-blue-700">
                                {getListingStatusLabel(item)}
                              </span>
                            </div>
                            <div className="mt-3 flex flex-wrap gap-2">
                              <button
                                type="button"
                                onClick={() => openEditListingModal(item)}
                                className="rounded-2xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-bold text-blue-700 transition hover:bg-blue-100"
                              >
                                Редагувати
                              </button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-3 text-sm text-slate-500">Ще немає створених оголошень.</p>
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Фільтри</p>
                  <h2 className="mt-1 text-xl font-black text-slate-900">Пошук</h2>
                </div>
                <button
                  type="button"
                  onClick={resetFilters}
                  className="rounded-2xl bg-slate-900 px-3 py-2 text-xs font-bold text-white transition hover:bg-blue-700"
                >
                  Скинути
                </button>
              </div>

              <div className="mt-4 rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3">
                <p className="text-[11px] font-black uppercase tracking-wide text-blue-700">Активні умови</p>
                <p className="mt-1 text-sm text-slate-700">{searchSummary}</p>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {activeFilters.length ? (
                  activeFilters.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => clearActiveFilter(item.key)}
                      className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-blue-200 hover:bg-blue-50"
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

              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Full-text пошук</p>
                  <button
                    type="button"
                    onClick={clearKeywordSearch}
                    className="rounded-lg border border-blue-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-blue-700 transition hover:bg-blue-100"
                  >
                    Очистити
                  </button>
                </div>
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
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
                    className="flex-1 rounded-xl border border-slate-200 bg-white p-3 text-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  />
                  <button
                    type="button"
                    onClick={applyKeywordSearch}
                    className="rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700"
                  >
                    Застосувати
                  </button>
                </div>
              </div>

              <div className="mt-4">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Швидкі сценарії</p>
                  <button
                    type="button"
                    onClick={saveCurrentSearch}
                    className="text-sm font-semibold text-blue-600 underline transition hover:text-blue-700"
                  >
                    Зберегти пошук
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {QUICK_SCENARIOS.map((scenario) => (
                    <button
                      key={scenario.label}
                      type="button"
                      onClick={() => applyScenario(scenario)}
                      className="rounded-xl bg-slate-100 px-3 py-2 text-sm font-medium text-slate-800 transition hover:bg-slate-200"
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
                        className="inline-flex items-center gap-2 rounded-full border border-blue-100 bg-white px-3 py-1 text-xs font-semibold text-slate-700"
                      >
                        <button type="button" onClick={() => openSavedSearch(entry)} className="hover:text-blue-700">
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

              <div className="mt-4 grid grid-cols-1 gap-4">
                <div>
                  <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Місто</label>
                  <select
                    value={cityFilter}
                    onChange={(e) => setCityFilter(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                  >
                    {cities.map((city) => (
                      <option key={city} value={city}>
                        {city === "Всі" ? "Всі міста України" : city}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Ціна, $</label>
                  <div className="mt-1 grid grid-cols-2 gap-2">
                    <input
                      type="number"
                      min="0"
                      placeholder="від"
                      value={minPrice}
                      onChange={(e) => setMinPrice(e.target.value)}
                      className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                    />
                    <input
                      type="number"
                      min="0"
                      placeholder="до"
                      value={maxPrice}
                      onChange={(e) => setMaxPrice(e.target.value)}
                      className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Кімнати</label>
                  <div className="mt-1 grid grid-cols-2 gap-2">
                    <input
                      type="number"
                      min="0"
                      placeholder="від"
                      value={minRooms}
                      onChange={(e) => setMinRooms(e.target.value)}
                      className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                    />
                    <input
                      type="number"
                      min="0"
                      placeholder="до"
                      value={maxRooms}
                      onChange={(e) => setMaxRooms(e.target.value)}
                      className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Площа, м²</label>
                  <div className="mt-1 grid grid-cols-2 gap-2">
                    <input
                      type="number"
                      min="0"
                      placeholder="від"
                      value={minArea}
                      onChange={(e) => setMinArea(e.target.value)}
                      className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                    />
                    <input
                      type="number"
                      min="0"
                      placeholder="до"
                      value={maxArea}
                      onChange={(e) => setMaxArea(e.target.value)}
                      className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Сортування</label>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                  >
                    <option value="relevance">Найбільш релевантні</option>
                    <option value="price-asc">Дешевші спочатку</option>
                    <option value="price-desc">Дорожчі спочатку</option>
                    <option value="area-desc">Більша площа спочатку</option>
                    <option value="area-asc">Менша площа спочатку</option>
                  </select>
                  <p className="mt-1 text-xs text-slate-500">Авто: дешевші спочатку для єОселя</p>
                </div>
              </div>

              <div className="mt-5 flex items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3">
                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={onlyEOselya}
                    onChange={(e) => setOnlyEOselya(e.target.checked)}
                    className="h-5 w-5"
                  />
                  <span className="font-medium text-slate-700">
                    Тільки об&apos;єкти під <span className="font-bold text-blue-600">єОселя</span>
                  </span>
                </label>
              </div>

              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setFavoriteIds([]);
                    setShowFavoritesOnly(false);
                  }}
                  className="rounded-2xl border border-rose-200 bg-white px-4 py-2 text-sm font-bold text-rose-700 transition hover:bg-rose-50"
                >
                  Очистити обрані
                </button>
                <button
                  type="button"
                  onClick={clearSavedFilters}
                  className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-bold text-slate-700 transition hover:bg-slate-100"
                >
                  Очистити localStorage
                </button>
              </div>
            </div>

            <div className="rounded-[28px] border border-rose-200 bg-rose-50 p-5 shadow-sm">
              <div className="flex flex-col gap-3">
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
                        : "border border-rose-200 bg-white text-rose-700 hover:bg-rose-100"
                    }`}
                  >
                    {showFavoritesOnly ? "❤️ Показую лише обрані" : "🤍 Показати лише обрані"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowFavoritesOnly(true)}
                    className="min-h-[44px] rounded-2xl bg-slate-900 px-4 text-sm font-bold text-white transition hover:bg-blue-700"
                  >
                    Порівняти зараз
                  </button>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Порівняння обраних</p>
                  <p className="mt-1 text-sm text-slate-600">{compareSummary}</p>

                  {!!compareProperties.length && (
                    <div className="mt-4 space-y-3">
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
                              <p className="mt-1 text-xs text-slate-500">
                                {property.city}, {property.district}
                              </p>
                            </div>
                            {property.id === bestValueId && (
                              <span className="rounded-full bg-emerald-100 px-2 py-1 text-[10px] font-semibold text-emerald-700">
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
                  <div className="flex flex-wrap gap-2">
                    {favoriteProperties.slice(0, 4).map((property) => (
                      <span
                        key={property.id}
                        className="inline-flex items-center gap-2 rounded-full border border-rose-100 bg-white px-3 py-1 text-xs font-semibold text-slate-700"
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
          </aside>

          <div className="space-y-4 lg:col-span-8">
            <div className="rounded-[28px] border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Результати</p>
                  <h2 className="mt-1 text-2xl font-black text-slate-900">
                    {catalogLoading && !catalogProperties.length
                      ? "Завантажуємо оголошення"
                      : visibleProperties.length
                      ? `Показано ${visibleProperties.length} з ${filteredProperties.length}`
                      : "Нічого не знайдено"}
                  </h2>
                  <p className="mt-1 text-sm text-slate-600">
                    {catalogError
                      ? catalogError
                      : showFavoritesOnly
                      ? "Лише обрані об'єкти"
                      : "Об'єкти відсортовано за вашими фільтрами та релевантністю"}
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowFavoritesOnly((current) => !current)}
                    className={`rounded-2xl px-4 py-2 text-sm font-bold transition ${
                      showFavoritesOnly
                        ? "bg-rose-600 text-white hover:bg-rose-700"
                        : "border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
                    }`}
                  >
                    {showFavoritesOnly ? "Лише обрані" : "Показати обрані"}
                  </button>
                  <button
                    type="button"
                    onClick={resetFilters}
                    className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-bold text-slate-700 transition hover:bg-slate-100"
                  >
                    Скинути
                  </button>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
                  >
                    <option value="relevance">Релевантність</option>
                    <option value="price-asc">Дешевші</option>
                    <option value="price-desc">Дорожчі</option>
                    <option value="area-desc">Більша площа</option>
                    <option value="area-asc">Менша площа</option>
                  </select>
                </div>
              </div>
            </div>

            {catalogError ? (
             <div className="rounded-[28px] border border-rose-200 bg-rose-50 p-4 shadow-sm">
               <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                 <div>
                   <p className="text-sm font-bold text-rose-700">Каталог тимчасово недоступний</p>
                   <p className="mt-1 text-sm text-rose-600">{catalogError}</p>
                 </div>
                 <button
                   type="button"
                   onClick={loadCatalogListings}
                   className="rounded-2xl border border-rose-200 bg-white px-4 py-2 text-sm font-bold text-rose-700 transition hover:bg-rose-100"
                 >
                   Спробувати ще раз
                 </button>
               </div>
             </div>
            ) : null}

            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-2">
              {visibleProperties.map((property) => (
                <div
                  key={property.id}
                  className="group overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm transition hover:-translate-y-1 hover:shadow-xl"
                >
                  <div className="relative">
                    <PhotoGallery images={property.images} title={property.title} />
                    <div className="absolute left-3 top-3 flex flex-col gap-2">
                      {property.eOselya && (
                        <span className="rounded-full bg-blue-600 px-3 py-1.5 text-[10px] font-black uppercase tracking-wider text-white shadow-md">
                          єОселя
                        </span>
                      )}
                      <span className="rounded-full bg-black/60 px-3 py-1.5 text-[10px] font-semibold text-white backdrop-blur-sm">
                        {property.city}, {property.district}
                      </span>
                    </div>
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
                    <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between gap-2">
                      <span className="rounded-full bg-black/60 px-3 py-1.5 text-xs font-semibold text-white backdrop-blur-sm">
                        {property.rooms} кімн.
                      </span>
                      <span className="rounded-full bg-white/90 px-3 py-1.5 text-xs font-bold text-slate-700">
                        {property.area} м²
                      </span>
                    </div>
                  </div>

                  <div className="p-5">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="line-clamp-2 text-lg font-bold leading-snug text-slate-900 group-hover:text-blue-700">
                          {property.title}
                        </h3>
                        <p className="mt-2 text-sm text-slate-500">
                          {property.city} • {property.district}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-2xl font-black text-blue-600">${property.price.toLocaleString("uk-UA")}</p>
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Ціна</p>
                      </div>
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                      <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700">
                        {property.rooms} кімн.
                      </span>
                      <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700">
                        {property.area} м²
                      </span>
                      <span
                        className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
                          property.eOselya
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-amber-50 text-amber-700"
                        }`}
                      >
                        {property.eOselya ? "Під єОселя" : "Стандартна пропозиція"}
                      </span>
                    </div>

                    <div className="mt-4 flex items-center justify-between gap-3">
                      <p className="text-xs text-slate-500">
                        {property.eOselya
                          ? "Підходить під державну програму"
                          : "Базова пропозиція без держпрограми"}
                      </p>
                      <button
                        type="button"
                        onClick={() => toggleFavorite(property)}
                        className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-bold text-slate-700 transition hover:bg-blue-50 hover:text-blue-700"
                      >
                        {favoriteIds.includes(property.id) ? "В обраному" : "В обране"}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {visibleProperties.length === 0 && (
              <div className="rounded-[28px] border border-dashed border-slate-200 bg-white py-16 text-center">
                <p className="text-lg font-medium text-slate-400">
                  {catalogLoading && !catalogProperties.length
                    ? "Завантажуємо каталог..."
                    : showFavoritesOnly
                    ? "У вас ще немає обраних об'єктів."
                    : "За вказаними фільтрами нічого не знайдено."}
                </p>
              </div>
            )}
          </div>
        </div>
      </section>

      {showCreateListingModal ? (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/70 px-4 py-8">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-[32px] border border-slate-200 bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-black uppercase tracking-wide text-slate-500">
                  {editingListingId ? "Редагувати оголошення" : "Створити оголошення"}
                </p>
                <h3 className="mt-1 text-2xl font-black text-slate-900">Профільне оголошення</h3>
                <p className="mt-2 text-sm text-slate-600">
                  {editingListingId
                    ? "Змініть поля, збережіть і оголошення залишиться опублікованим на сайті."
                    : "Після відправки оголошення одразу з'явиться в профілі та на сайті."}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  closeListingModal();
                  setListingMessage("");
                }}
                className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateListing} className="mt-6 grid gap-4 md:grid-cols-2">
              <div className="md:col-span-2">
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Назва</label>
                <input
                  required
                  value={listingForm.title}
                  onChange={(event) => updateListingField("title", event.target.value)}
                  placeholder="Сучасна квартира з ремонтом"
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Місто</label>
                <input
                  required
                  value={listingForm.city}
                  onChange={(event) => updateListingField("city", event.target.value)}
                  placeholder="Київ"
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Район</label>
                <input
                  required
                  value={listingForm.district}
                  onChange={(event) => updateListingField("district", event.target.value)}
                  placeholder="Печерський"
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Тип об'єкта</label>
                <select
                  value={listingForm.propertyType}
                  onChange={(event) => updateListingField("propertyType", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                >
                  <option value="квартира">Квартира</option>
                  <option value="будинок">Будинок</option>
                  <option value="комерція">Комерція</option>
                  <option value="земля">Земля</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Стан</label>
                <select
                  value={listingForm.conditionType}
                  onChange={(event) => updateListingField("conditionType", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                >
                  <option value="нова будова">Нова будова</option>
                  <option value="вторинка">Вторинка</option>
                  <option value="після ремонту">Після ремонту</option>
                  <option value="без ремонту">Без ремонту</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Ціна, $</label>
                <input
                  required
                  type="number"
                  min="1"
                  value={listingForm.price}
                  onChange={(event) => updateListingField("price", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Кімнат</label>
                <input
                  required
                  type="number"
                  min="0"
                  value={listingForm.rooms}
                  onChange={(event) => updateListingField("rooms", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Площа, м²</label>
                <input
                  required
                  type="number"
                  min="1"
                  value={listingForm.area}
                  onChange={(event) => updateListingField("area", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Поверх</label>
                <input
                  type="number"
                  min="1"
                  value={listingForm.floor}
                  onChange={(event) => updateListingField("floor", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Загалом поверхів</label>
                <input
                  type="number"
                  min="1"
                  value={listingForm.totalFloors}
                  onChange={(event) => updateListingField("totalFloors", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Рік будівництва</label>
                <input
                  type="number"
                  min="1900"
                  value={listingForm.yearBuilt}
                  onChange={(event) => updateListingField("yearBuilt", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Тип пропозиції</label>
                <select
                  value={listingForm.listingType}
                  onChange={(event) => updateListingField("listingType", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                >
                  <option value="sale">Продаж</option>
                  <option value="rent">Оренда</option>
                </select>
              </div>
              <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 md:col-span-2">
                <input
                  type="checkbox"
                  checked={listingForm.eOselya}
                  onChange={(event) => updateListingField("eOselya", event.target.checked)}
                  className="h-5 w-5"
                />
                <label className="text-sm font-semibold text-slate-700">Під єОселя</label>
              </div>
              <div className="md:col-span-2">
                <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Опис</label>
                <textarea
                  rows="4"
                  value={listingForm.description}
                  onChange={(event) => updateListingField("description", event.target.value)}
                  placeholder="Коротко про переваги об'єкта"
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div className="md:col-span-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <label className="text-xs font-bold uppercase tracking-wide text-slate-500">Фото (URL / файли)</label>
                  <button
                    type="button"
                    onClick={addListingImageField}
                    className="rounded-2xl border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700"
                  >
                    + Додати URL
                  </button>
                </div>
                <div className="mt-3 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-4">
                  <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-6 text-center text-sm font-semibold text-slate-700 transition hover:border-blue-300 hover:bg-blue-50">
                    <span className="text-lg font-black text-blue-600">⬆</span>
                    <span>Виберіть фото з комп'ютера</span>
                    <span className="text-xs font-medium text-slate-500">PNG, JPG, WEBP. Декілька файлів за раз.</span>
                    <input type="file" multiple accept="image/*" onChange={handleListingFileSelection} className="hidden" />
                  </label>
                  {selectedListingFiles.length ? (
                    <div className="mt-3 space-y-3">
                      <div className="flex flex-wrap gap-2">
                        {selectedListingFiles.map((file) => (
                          <span
                            key={`${file.name}-${file.size}-${file.lastModified}`}
                            className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700"
                          >
                            {file.name}
                          </span>
                        ))}
                      </div>
                      {selectedListingFilePreviews.length ? (
                        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                          {selectedListingFilePreviews.map((preview) => (
                            <div key={preview.id} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                              <img src={preview.src} alt={preview.name} className="h-28 w-full object-cover" />
                              <div className="border-t border-slate-100 px-3 py-2 text-xs font-medium text-slate-600">
                                {preview.name}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <div className="mt-3 space-y-2">
                  {listingForm.images.map((image, index) => (
                    <div key={`${index}-${image}`} className="flex items-center gap-2">
                      <input
                        value={image}
                        onChange={(event) => updateListingImage(index, event.target.value)}
                        placeholder={`Посилання на фото ${index + 1}`}
                        className="flex-1 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                      />
                      {listingForm.images.length > 1 ? (
                        <button
                          type="button"
                          onClick={() => removeListingImageField(index)}
                          className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700"
                        >
                          ✕
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap gap-3 md:col-span-2">
                <button
                  type="submit"
                  disabled={listingSubmitting}
                  className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {listingSubmitting ? "Зберігаємо…" : editingListingId ? "Зберегти зміни" : "Публікувати оголошення"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    closeListingModal();
                    setListingMessage("");
                  }}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
                >
                  Скасувати
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}

if (typeof document !== "undefined") {
  const root = document.getElementById("root");
  if (root && window.ReactDOM?.createRoot) {
    window.ReactDOM.createRoot(root).render(React.createElement(RealEstateApp));
  }
}
