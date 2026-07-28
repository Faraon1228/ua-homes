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
    image:
      "https://images.unsplash.com/photo-1560185007-c5ca9d2c014d?auto=format&fit=crop&w=1200&q=80",
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
    image:
      "https://images.unsplash.com/photo-1493809842364-78817add7ffb?auto=format&fit=crop&w=1200&q=80",
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
    image:
      "https://images.unsplash.com/photo-1484154218962-a197022b5858?auto=format&fit=crop&w=1200&q=80",
  },
];

function getStored(key, fallback) {
  if (typeof window === "undefined") return fallback;
  const value = window.localStorage.getItem(key);
  return value ?? fallback;
}

export default function RealEstateApp() {
  const [cityFilter, setCityFilter] = useState(() => getStored("re.cityFilter", "Всі"));
  const [onlyEOselya, setOnlyEOselya] = useState(
    () => getStored("re.onlyEOselya", "false") === "true"
  );
  const [minPrice, setMinPrice] = useState(() => getStored("re.minPrice", ""));
  const [maxPrice, setMaxPrice] = useState(() => getStored("re.maxPrice", ""));
  const [minRooms, setMinRooms] = useState(() => getStored("re.minRooms", ""));
  const [maxRooms, setMaxRooms] = useState(() => getStored("re.maxRooms", ""));
  const [minArea, setMinArea] = useState(() => getStored("re.minArea", ""));
  const [maxArea, setMaxArea] = useState(() => getStored("re.maxArea", ""));
  const [sortBy, setSortBy] = useState(() => getStored("re.sortBy", DEFAULT_SORT));

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
    window.localStorage.setItem("re.minPrice", minPrice);
    window.localStorage.setItem("re.maxPrice", maxPrice);
    window.localStorage.setItem("re.minRooms", minRooms);
    window.localStorage.setItem("re.maxRooms", maxRooms);
    window.localStorage.setItem("re.minArea", minArea);
    window.localStorage.setItem("re.maxArea", maxArea);
    window.localStorage.setItem("re.sortBy", sortBy);
  }, [cityFilter, onlyEOselya, minPrice, maxPrice, minRooms, maxRooms, minArea, maxArea, sortBy]);

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

  const resetFilters = () => {
    setCityFilter("Всі");
    setOnlyEOselya(false);
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
    resetFilters();
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
        </div>
      </section>

      <main className="max-w-7xl mx-auto px-4 my-8">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredProperties.map((property) => (
            <div
              key={property.id}
              className="bg-white rounded-2xl overflow-hidden shadow-sm border border-gray-100"
            >
              <div className="relative h-56 overflow-hidden bg-gray-200">
                <img src={property.image} alt={property.title} className="w-full h-full object-cover" />
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

        {filteredProperties.length === 0 && (
          <div className="text-center py-16 bg-white rounded-2xl border border-dashed border-gray-200 mt-6">
            <p className="text-gray-400 font-medium text-lg">
              За вказаними фільтрами нічого не знайдено.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
