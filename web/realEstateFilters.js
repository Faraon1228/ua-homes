export const DEFAULT_SORT = "price-desc";
export const EOSELYA_SORT = "price-asc";

export const STORAGE_KEYS = [
  "re.cityFilter",
  "re.onlyEOselya",
  "re.minPrice",
  "re.maxPrice",
  "re.minRooms",
  "re.maxRooms",
  "re.minArea",
  "re.maxArea",
  "re.sortBy",
];

export function resolveSortByForEOselya(previousSort, onlyEOselya) {
  const isPriceSort = previousSort === "price-asc" || previousSort === "price-desc";
  if (!isPriceSort) {
    return previousSort;
  }
  return onlyEOselya ? EOSELYA_SORT : DEFAULT_SORT;
}

export function filterAndSortProperties(properties, filters) {
  const {
    cityFilter = "Всі",
    onlyEOselya = false,
    minPrice = "",
    maxPrice = "",
    minRooms = "",
    maxRooms = "",
    minArea = "",
    maxArea = "",
    sortBy = DEFAULT_SORT,
  } = filters;

  const filtered = properties.filter((item) => {
    const matchCity = cityFilter === "Всі" || item.city === cityFilter;
    const matchEOselya = !onlyEOselya || item.eOselya;

    const matchMinPrice = minPrice === "" || item.price >= Number(minPrice);
    const matchMaxPrice = maxPrice === "" || item.price <= Number(maxPrice);

    const matchMinRooms = minRooms === "" || item.rooms >= Number(minRooms);
    const matchMaxRooms = maxRooms === "" || item.rooms <= Number(maxRooms);

    const matchMinArea = minArea === "" || item.area >= Number(minArea);
    const matchMaxArea = maxArea === "" || item.area <= Number(maxArea);

    return (
      matchCity &&
      matchEOselya &&
      matchMinPrice &&
      matchMaxPrice &&
      matchMinRooms &&
      matchMaxRooms &&
      matchMinArea &&
      matchMaxArea
    );
  });

  return filtered.sort((a, b) => {
    if (sortBy === "price-asc") return a.price - b.price;
    if (sortBy === "price-desc") return b.price - a.price;
    if (sortBy === "area-desc") return b.area - a.area;
    if (sortBy === "area-asc") return a.area - b.area;
    return 0;
  });
}
