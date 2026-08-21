import * as Sentry from "@sentry/browser";

const dsn = __SENTRY_DSN__;
const environment = __SENTRY_ENVIRONMENT__;
const release = __SENTRY_RELEASE__;
const tracesSampleRate = Number(__SENTRY_TRACES_SAMPLE_RATE__);
const project = __SENTRY_PROJECT__;
const REDACTED = "[Filtered]";
const sensitiveKey = /(?:^|_)(?:authorization|cookie|csrf|password|secret|token|phone|email|message|upload|attachment|address|contact|location|user)(?:_|$)/i;
const privateValue = /(?:bearer\s+[\w.-]+|[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:\+?\d[\d ()-]{8,}\d)|(?:password|token|secret|authorization)=?[^\s&]*)/i;
const expectedError = /(?:aborterror|failed to fetch|networkerror|load failed|network request failed|offline|unauthorized|forbidden|validation|rate.?limit|too many requests|помилка запиту \(4\d\d\))/i;

function scrub(value, key = "") {
  if (sensitiveKey.test(key)) return REDACTED;
  if (Array.isArray(value)) return value.map((item) => scrub(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([childKey, item]) => [childKey, scrub(item, childKey)]));
  }
  if (typeof value === "string" && privateValue.test(value)) return REDACTED;
  return value;
}

function safeUrl(raw) {
  if (!raw) return raw;
  try {
    const url = new URL(raw, window.location.origin);
    return `${url.origin}${url.pathname}`;
  } catch (_) {
    return REDACTED;
  }
}

function eventText(event) {
  const exceptions = event.exception?.values || [];
  return [event.message, ...exceptions.flatMap((value) => [value.type, value.value])]
    .filter(Boolean)
    .join(" ");
}

function beforeSend(event, hint) {
  const original = hint?.originalException;
  const status = Number(original?.status || original?.statusCode || event.tags?.["http.status_code"] || 0);
  if ((status >= 400 && status < 500) || !navigator.onLine || expectedError.test(eventText(event))) return null;

  delete event.user;
  event.message = scrub(event.message);
  if (event.exception?.values) {
    event.exception.values = event.exception.values.map((value) => ({
      ...value,
      value: scrub(value.value),
    }));
  }
  if (event.request) {
    event.request.url = safeUrl(event.request.url);
    event.request.query_string = "";
    event.request.cookies = REDACTED;
    event.request.data = scrub(event.request.data);
    event.request.headers = scrub(event.request.headers);
  }
  event.contexts = scrub(event.contexts);
  event.extra = scrub(event.extra);
  event.tags = scrub(event.tags);
  if (event.breadcrumbs) {
    event.breadcrumbs = event.breadcrumbs
      .filter((item) => !/(?:fetch|xhr|console|input|upload|auth)/i.test(item.category || ""))
      .map((item) => ({ ...item, message: scrub(item.message), data: scrub(item.data) }));
  }
  return event;
}

const configured = typeof dsn === "string" && dsn.length > 0 && !dsn.startsWith("__");
window.uaMonitoringEnabled = configured;
window.uaSentryCaptureException = () => {};
window.uaSentryAddBreadcrumb = () => {};

if (configured) {
  const sampleRate = Number.isFinite(tracesSampleRate) && tracesSampleRate >= 0 && tracesSampleRate <= 1
    ? tracesSampleRate
    : 0.01;
  Sentry.init({
    dsn,
    environment: environment && !environment.startsWith("__") ? environment : "production",
    release: release && !release.startsWith("__") ? release : undefined,
    sendDefaultPii: false,
    tracesSampleRate: sampleRate,
    integrations: (defaults) => [
      ...defaults,
      Sentry.browserTracingIntegration({ traceFetch: false, traceXHR: false }),
    ],
    beforeSend,
    maxBreadcrumbs: 50,
    ignoreErrors: [expectedError],
  });
  Sentry.setTag("surface", project);
  window.uaSentryCaptureException = (error, context = {}) => {
    if (expectedError.test(String(error?.message || error || ""))) return;
    Sentry.captureException(error, { contexts: { app: scrub(context) } });
  };
  window.uaSentryAddBreadcrumb = (category, message) => {
    if (privateValue.test(String(message || ""))) return;
    Sentry.addBreadcrumb({ category, message: String(message || "").slice(0, 200), level: "info" });
  };
}
