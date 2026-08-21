// Centralized same-origin API client for the UA-Dim staff admin panel.
//
// Auth model (see backend/admin_routes.py): login sets an httpOnly session
// cookie (ua_dim_staff_session) plus an httpOnly double-submit CSRF cookie
// (ua_dim_staff_csrf) that JavaScript cannot read directly. The backend
// mirrors the same CSRF value back as `csrf_token` in the JSON body of both
// `/auth/login` and `/auth/session`, so we cache that value in memory (never
// localStorage) and echo it back as the `X-CSRF-Token` header on every
// mutating request; the server compares it against the httpOnly cookie it
// receives automatically via `credentials: "same-origin"`.
const BASE_PATH = "/api/admin";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload || null;
  }
}

let unauthorizedHandler = null;
export function onUnauthorized(handler) {
  unauthorizedHandler = handler;
}

let csrfToken = "";
/** Cache the CSRF token returned by /auth/login or /auth/session responses. */
export function setCsrfToken(token) {
  csrfToken = typeof token === "string" ? token : "";
}

function buildQuery(query) {
  if (!query) return "";
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    params.set(key, String(value));
  });
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

async function request(path, { method = "GET", body, query, signal, isForm = false } = {}) {
  const url = `${BASE_PATH}${path}${buildQuery(query)}`;
  const headers = {};
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method) && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }

  let response;
  try {
    response = await fetch(url, {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    throw new ApiError("Мережева помилка. Перевірте з'єднання.", 0, null);
  }

  const raw = await response.text();
  let payload = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = null;
    }
  }

  // Both /auth/login and /auth/session refresh and return the current CSRF
  // token on every call — keep our in-memory copy in sync automatically.
  if (payload && typeof payload.csrf_token === "string") {
    setCsrfToken(payload.csrf_token);
  }

  if (!response.ok) {
    if (response.status === 401 && unauthorizedHandler) {
      unauthorizedHandler();
    }
    const message = (payload && payload.error) || `Помилка запиту (${response.status})`;
    throw new ApiError(message, response.status, payload);
  }
  return payload;
}

export const api = {
  get: (path, query, signal) => request(path, { method: "GET", query, signal }),
  post: (path, body, signal) => request(path, { method: "POST", body: body ?? {}, signal }),
  put: (path, body, signal) => request(path, { method: "PUT", body: body ?? {}, signal }),
  patch: (path, body, signal) => request(path, { method: "PATCH", body: body ?? {}, signal }),
  del: (path, body, signal) => request(path, { method: "DELETE", body, signal }),
  upload: (path, formData, signal) => request(path, { method: "POST", body: formData, isForm: true, signal }),
};

/** Trigger a credentialed same-origin file download (CSV export etc.). */
export function downloadFile(path, query) {
  const url = `${BASE_PATH}${path}${buildQuery(query)}`;
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
