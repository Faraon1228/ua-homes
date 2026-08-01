import React, { useEffect, useMemo, useState } from "react";
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
  "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1200' height='675' viewBox='0 0 1200 675'%3E%3Crect width='1200' height='675' fill='%23e2e8f0'/%3E%3Cpath d='M0 500h1200v175H0z' fill='%23cbd5e1'/%3E%3Ccircle cx='360' cy='260' r='70' fill='%23cbd5e1'/%3E%3Cpath d='M250 445l125-115 90 78 72-60 155 132H250z' fill='%2394a3b8'/%3E%3Ctext x='600' y='565' text-anchor='middle' font-family='Arial,sans-serif' font-size='28' fill='%23475569'%3EUA Homes%3C/text%3E%3C/svg%3E";

function normalizeImageSrc(src) {
  if (!src) return "";
  return src.includes("images.unsplash.com") ? FALLBACK_IMAGE : src;
}

function getStored(key, fallback) {
  if (typeof window === "undefined") return fallback;
  const value = window.localStorage.getItem(key);
  return value ?? fallback;
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
  ]);

  const filteredProperties = useMemo(
    () =>
      filterAndSortProperties(MOCK_PROPERTIES, {
        cityFilter,
        onlyEOselya,
        minPrice,
        maxPrice,
        minRooms,
        maxRooms,
        minArea,
        maxArea,
        sortBy,
      }),
    [cityFilter, onlyEOselya, minPrice, maxPrice, minRooms, maxRooms, minArea, maxArea, sortBy]
  );
  const favoriteProperties = useMemo(
    () => MOCK_PROPERTIES.filter((property) => favoriteIds.includes(property.id)),
    [favoriteIds]
  );
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

  const clearSavedFilters = () => {
    STORAGE_KEYS.forEach((key) => window.localStorage.removeItem(key));
    window.localStorage.removeItem("re.showFavoritesOnly");
    window.localStorage.removeItem("re.favoriteIds");
    resetFilters();
    setFavoriteIds([]);
  };

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 font-sans">
      <section className="max-w-7xl mx-auto px-4 mt-8">
        <div className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
          <h1 className="text-2xl font-bold mb-4">Пошук нерухомості в Україні</h1>

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
