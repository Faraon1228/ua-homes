import { apiRequest } from "./apiClient.js";

export function buildCatalogQuery(filters, { limit, offset, append }) {
  const query = {
    status: "published",
    limit,
    offset,
    sort: filters.sortBy,
    includeFacets: append ? undefined : 1,
    city: filters.cityFilter === "Всі" ? undefined : filters.cityFilter,
    type: filters.propertyTypeFilter === "Всі" ? undefined : filters.propertyTypeFilter,
    eOselya: filters.onlyEOselya ? 1 : undefined,
    minPrice: filters.minPrice,
    maxPrice: filters.maxPrice,
    minRooms: filters.minRooms,
    maxRooms: filters.maxRooms,
    minArea: filters.minArea,
    maxArea: filters.maxArea,
    search: filters.keywordSearch.trim() || undefined,
  };
  if (filters.showFavoritesOnly) query.ids = filters.favoriteIds.join(",");
  return query;
}

export function fetchCatalogListings(filters, options) {
  return apiRequest("/listings", {
    query: buildCatalogQuery(filters, options),
    signal: options.signal,
    cache: options.fresh ? "no-store" : "default",
    errorMessage: "Не вдалося завантажити оголошення",
  });
}
