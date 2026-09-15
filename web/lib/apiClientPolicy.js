export const API_PREFIX = "/api";
export const DEFAULT_TIMEOUT_MS = 15000;
export const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function normalizeApiBaseUrl(value) {
  const normalized = String(value || "").trim().replace(/\/+$/, "");
  if (!normalized || normalized === API_PREFIX) return "";
  return normalized.endsWith(API_PREFIX)
    ? normalized.slice(0, -API_PREFIX.length).replace(/\/+$/, "")
    : normalized;
}

export function getConfiguredApiBaseUrl() {
  if (typeof window === "undefined") return "";
  const configured = normalizeApiBaseUrl(window.UA_HOMES_API);
  if (configured) return configured;
  const hostname = window.location.hostname || "";
  if (["localhost", "127.0.0.1", "0.0.0.0"].includes(hostname)) {
    return "http://127.0.0.1:5050";
  }
  return normalizeApiBaseUrl(window.location.origin);
}

export function buildCanonicalApiUrl(path, query, baseUrl = getConfiguredApiBaseUrl()) {
  const normalizedPath = String(path || "").startsWith("/")
    ? String(path)
    : `/${path}`;
  const prefix = baseUrl ? `${baseUrl}${API_PREFIX}` : API_PREFIX;
  const url = `${prefix}${normalizedPath}`;
  if (!query) return url;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    params.set(key, String(value));
  });
  const serialized = params.toString();
  return serialized ? `${url}?${serialized}` : url;
}

export async function parseJsonResponse(response) {
  const raw = await response.text();
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
