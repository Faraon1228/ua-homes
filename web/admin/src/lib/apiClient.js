import {
  buildCanonicalApiUrl,
  DEFAULT_TIMEOUT_MS,
  parseJsonResponse,
  SAFE_METHODS,
} from "../../../lib/apiClientPolicy.js";

const BASE_PATH = "/api/admin";

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
export function setCsrfToken(token) {
  csrfToken = typeof token === "string" ? token : "";
}

function buildAdminUrl(path, query) {
  return buildCanonicalApiUrl(`${BASE_PATH.slice("/api".length)}${path}`, query);
}

async function request(
  path,
  { method = "GET", body, query, signal, isForm = false, timeout = DEFAULT_TIMEOUT_MS } = {},
) {
  const url = buildAdminUrl(path, query);
  const headers = {};
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method) && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  const controller = new AbortController();
  const abortFromCaller = () => controller.abort();
  signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeoutId = timeout > 0 ? setTimeout(() => controller.abort(), timeout) : null;

  let response;
  try {
    response = await fetch(url, {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error?.name === "AbortError" && timeoutId) {
      throw new ApiError("Час очікування запиту вичерпано.", 408, null);
    }
    throw new ApiError("Мережева помилка. Перевірте з'єднання.", 0, null);
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
    signal?.removeEventListener("abort", abortFromCaller);
  }

  const payload = await parseJsonResponse(response);
  if (payload && typeof payload.csrf_token === "string") setCsrfToken(payload.csrf_token);
  if (!response.ok) {
    if (response.status === 401 && unauthorizedHandler) unauthorizedHandler();
    const message = payload?.error || `Помилка запиту (${response.status})`;
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
  upload: (path, formData, signal) =>
    request(path, { method: "POST", body: formData, isForm: true, signal }),
};

export function downloadFile(path, query) {
  const url = buildAdminUrl(path, query);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
