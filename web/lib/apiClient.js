export class ApiError extends Error {
  constructor(message, status, payload = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export function getApiBaseUrl() {
  if (typeof window === "undefined") return "/api";
  const configured = (window.UA_HOMES_API || "").trim();
  if (configured) return configured.replace(/\/+$/, "");
  const hostname = window.location.hostname || "";
  if (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "0.0.0.0") {
    return "http://127.0.0.1:5050";
  }
  return window.location.origin;
}

export function buildApiUrl(path, query) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${getApiBaseUrl()}/api${normalizedPath}`;
  if (!query) return url;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    params.set(key, String(value));
  });
  const serialized = params.toString();
  return serialized ? `${url}?${serialized}` : url;
}

async function parseJson(response) {
  const raw = await response.text();
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function apiRequest(
  path,
  {
    method = "GET",
    body,
    query,
    signal,
    token,
    cache,
    headers: customHeaders,
    onUnauthorized,
    errorMessage,
  } = {}
) {
  const headers = { ...customHeaders };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(buildApiUrl(path, query), {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      cache,
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new ApiError(errorMessage || "Мережева помилка. Перевірте з'єднання.", 0);
  }

  const payload = await parseJson(response);
  if (!response.ok) {
    if (response.status === 401) onUnauthorized?.();
    throw new ApiError(
      payload?.error || errorMessage || `Помилка запиту (${response.status})`,
      response.status,
      payload
    );
  }
  return payload;
}

export function createLatestRequest() {
  let sequence = 0;
  let controller = null;
  return {
    begin() {
      controller?.abort();
      controller = new AbortController();
      sequence += 1;
      return { id: sequence, signal: controller.signal };
    },
    isLatest(id) {
      return id === sequence;
    },
    abort() {
      controller?.abort();
    },
  };
}
