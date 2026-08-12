export const DEFAULT_SORT = "price-desc";
export const EOSELYA_SORT = "price-asc";

export const STORAGE_KEYS = [
  "re.cityFilter",
  "re.propertyType",
  "re.onlyEOselya",
  "re.minPrice",
  "re.maxPrice",
  "re.minRooms",
  "re.maxRooms",
  "re.minArea",
  "re.maxArea",
  "re.sortBy",
  "re.showFavoritesOnly",
  "re.favoriteIds",
  "re.keywordSearch",
];

export function normalizePropertyType(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["квартира", "квартири", "apartment", "apartments", "flat", "flats"].includes(normalized)) {
    return "квартира";
  }
  if (["будинок", "будинки", "house", "houses", "villa"].includes(normalized)) {
    return "будинок";
  }
  if (["земля", "земельна ділянка", "земельні ділянки", "land", "plot", "plots"].includes(normalized)) {
    return "земля";
  }
  if (["комерція", "комерційне приміщення", "комерційні приміщення", "commercial", "commercial-space", "office", "retail"].includes(normalized)) {
    return "комерція";
  }
  return "";
}

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
    propertyType = "Всі",
    onlyEOselya = false,
    minPrice = "",
    maxPrice = "",
    minRooms = "",
    maxRooms = "",
    minArea = "",
    maxArea = "",
    sortBy = DEFAULT_SORT,
    keywordSearch = "",
  } = filters;

  const keyword = keywordSearch.trim().toLowerCase();
  const keywordTerms = keyword ? keyword.split(/\s+/).filter(Boolean) : [];

  const filtered = properties.filter((item) => {
    const matchCity = cityFilter === "Всі" || item.city === cityFilter;
    const normalizedPropertyType = normalizePropertyType(item.propertyType);
    const matchPropertyType = propertyType === "Всі" || normalizedPropertyType === propertyType;
    const matchEOselya = !onlyEOselya || item.eOselya;

    const matchMinPrice = minPrice === "" || item.price >= Number(minPrice);
    const matchMaxPrice = maxPrice === "" || item.price <= Number(maxPrice);

    const matchMinRooms = minRooms === "" || item.rooms >= Number(minRooms);
    const matchMaxRooms = maxRooms === "" || item.rooms <= Number(maxRooms);

    const matchMinArea = minArea === "" || item.area >= Number(minArea);
    const matchMaxArea = maxArea === "" || item.area <= Number(maxArea);
    const searchableText = `${item.title} ${item.city} ${item.district}`.toLowerCase();
    const matchKeyword =
      !keywordTerms.length || keywordTerms.every((term) => searchableText.includes(term));

    return (
      matchCity &&
      matchPropertyType &&
      matchEOselya &&
      matchMinPrice &&
      matchMaxPrice &&
      matchMinRooms &&
      matchMaxRooms &&
      matchMinArea &&
      matchMaxArea &&
      matchKeyword
    );
  });

  return filtered.sort((a, b) => {
    if (sortBy === "relevance") {
      const score = (item) => {
        if (!keywordTerms.length) return 0;
        const text = `${item.title} ${item.city} ${item.district}`.toLowerCase();
        let value = 0;
        if (text.includes(keyword)) value += 10;
        keywordTerms.forEach((term) => {
          if (text.includes(term)) value += 3;
          if (item.title.toLowerCase().includes(term)) value += 2;
          if (item.district.toLowerCase().includes(term)) value += 1;
          if (item.city.toLowerCase().includes(term)) value += 1;
        });
        return value;
      };
      const scoreDiff = score(b) - score(a);
      if (scoreDiff !== 0) return scoreDiff;
      return a.price - b.price;
    }
    if (sortBy === "price-asc") return a.price - b.price;
    if (sortBy === "price-desc") return b.price - a.price;
    if (sortBy === "area-desc") return b.area - a.area;
    if (sortBy === "area-asc") return a.area - b.area;
    return 0;
  });
}
