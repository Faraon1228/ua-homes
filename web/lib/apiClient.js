import {
  buildCanonicalApiUrl,
  DEFAULT_TIMEOUT_MS,
  getConfiguredApiBaseUrl,
  parseJsonResponse,
} from "./apiClientPolicy.js";

export class ApiError extends Error {
  constructor(message, status, payload = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export function getApiBaseUrl() {
  return getConfiguredApiBaseUrl();
}

export function buildApiUrl(path, query) {
  return buildCanonicalApiUrl(path, query);
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
    timeout = DEFAULT_TIMEOUT_MS,
    isForm = false,
  } = {},
) {
  const headers = { ...customHeaders };
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  const controller = new AbortController();
  const abortFromCaller = () => controller.abort();
  signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeoutId = timeout > 0 ? setTimeout(() => controller.abort(), timeout) : null;

  let response;
  try {
    response = await fetch(buildApiUrl(path, query), {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      signal: controller.signal,
      cache,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error?.name === "AbortError" && timeoutId) {
      throw new ApiError("Час очікування запиту вичерпано.", 408);
    }
    throw new ApiError(errorMessage || "Мережева помилка. Перевірте з'єднання.", 0);
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
    signal?.removeEventListener("abort", abortFromCaller);
  }

  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    if (response.status === 401) onUnauthorized?.();
    throw new ApiError(
      payload?.error || errorMessage || `Помилка запиту (${response.status})`,
      response.status,
      payload,
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
