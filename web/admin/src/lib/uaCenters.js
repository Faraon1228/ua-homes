// Loads the shared UA city/district reference dataset used for the
// listing form's location autocomplete (same file the public site's
// market-upgrade.js reads, so we do not duplicate or fork this data).
let cachePromise = null;

export function loadUaCenters() {
  if (!cachePromise) {
    cachePromise = fetch("./ua-centers.json", { credentials: "same-origin" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data || !Array.isArray(data.regions) || typeof data.regionData !== "object") {
          return { regions: [], regionData: {}, allCenters: [] };
        }
        return data;
      })
      .catch(() => ({ regions: [], regionData: {}, allCenters: [] }));
  }
  return cachePromise;
}
