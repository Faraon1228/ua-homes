import React, { useEffect, useRef, useState } from "../react-shim.js";

function getApiUrl(path) {
  const configured = (window.UA_HOMES_API || "").trim().replace(/\/+$/, "");
  const local = ["localhost", "127.0.0.1", "0.0.0.0"].includes(
    window.location.hostname,
  );
  const base = configured || (local ? "http://127.0.0.1:5050" : window.location.origin);
  return `${base}/api${path.startsWith("/") ? path : `/${path}`}`;
}

function createClientToken(prefix) {
  const value =
    window.crypto?.randomUUID?.() ||
    `${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;
  return `${prefix}-${value}`;
}

function getReporterSessionId() {
  const key = "uaDim.reporterSessionId";
  const stored = window.sessionStorage.getItem(key);
  if (stored) return stored;
  const generated = createClientToken("reporter");
  window.sessionStorage.setItem(key, generated);
  return generated;
}

function verificationLabel(status) {
  return {
    verified: "Перевірене оголошення",
    pending: "Перевірка оголошення триває",
    rejected: "Перевірку оголошення не підтверджено",
    unverified: "Оголошення ще не перевірене",
  }[status] || "Статус перевірки не вказано";
}

function sellerLabel(type) {
  return {
    owner: "Власник",
    intermediary: "Посередник",
    agency: "Агентство",
    developer: "Забудовник",
  }[type] || "Тип продавця не вказано";
}

function historyValue(field, value) {
  if (value === null || value === undefined || value === "") return "Не вказано";
  if (field === "price") {
    const number = Number(value);
    return Number.isFinite(number) ? `$${number.toLocaleString("uk-UA")}` : String(value);
  }
  if (field === "area") return `${Number(value).toLocaleString("uk-UA")} м²`;
  if (field === "listing_verification_status") return verificationLabel(value);
  return String(value);
}

const HISTORY_LABELS = {
  price: "Ціна",
  title: "Назва",
  description: "Опис",
  area: "Площа",
  listing_verification_status: "Перевірка оголошення",
};

export default function TrustDialog({ property, authToken, onClose }) {
  const dialogRef = useRef(null);
  const closeButtonRef = useRef(null);
  const [trustData, setTrustData] = useState(null);
  const [trustLoading, setTrustLoading] = useState(true);
  const [trustError, setTrustError] = useState("");
  const [showReportForm, setShowReportForm] = useState(false);
  const [reportReason, setReportReason] = useState("fraud_scam");
  const [reportDetails, setReportDetails] = useState("");
  const [reportStatus, setReportStatus] = useState("");
  const [reportError, setReportError] = useState("");
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState(() =>
    createClientToken("report"),
  );

  useEffect(() => {
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    const keydown = (event) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [
        ...dialogRef.current.querySelectorAll(
          'button:not([disabled]),a[href],select:not([disabled]),textarea:not([disabled]),input:not([disabled]),[tabindex]:not([tabindex="-1"])',
        ),
      ].filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", keydown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", keydown);
      previousFocus?.focus?.();
    };
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    fetch(getApiUrl(`/listings/${property.id}/trust`), {
      headers: authToken
        ? { Authorization: ["Bearer", authToken].join(" ") }
        : {},
      signal: controller.signal,
    })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) {
          throw new Error(result.error || "Не вдалося завантажити дані довіри");
        }
        return result;
      })
      .then(setTrustData)
      .catch((error) => {
        if (error.name !== "AbortError") setTrustError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setTrustLoading(false);
      });
    return () => controller.abort();
  }, [authToken, property.id]);

  const submitReport = async (event) => {
    event.preventDefault();
    const details = reportDetails.trim();
    if (details.length < 10) {
      setReportError("Опишіть проблему щонайменше 10 символами.");
      return;
    }
    setReportSubmitting(true);
    setReportError("");
    setReportStatus("");
    try {
      const response = await fetch(getApiUrl(`/listings/${property.id}/reports`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken
            ? { Authorization: ["Bearer", authToken].join(" ") }
            : {}),
        },
        body: JSON.stringify({
          reason_code: reportReason,
          details,
          reporter_session_id: getReporterSessionId(),
          idempotency_key: idempotencyKey,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Не вдалося надіслати скаргу");
      setReportStatus(
        result.duplicate
          ? "Цю скаргу вже отримано."
          : "Скаргу надіслано команді модерації.",
      );
      setReportDetails("");
      setIdempotencyKey(createClientToken("report"));
    } catch (error) {
      setReportError(error.message || "Не вдалося надіслати скаргу");
    } finally {
      setReportSubmitting(false);
    }
  };

  const verificationStatus =
    trustData?.listing_verification_status ||
    property.listingVerificationStatus ||
    "unverified";
  const verifiedListing = trustData
    ? trustData.verified_listing === true
    : property.verifiedListing === true;
  const history = Array.isArray(trustData?.history) ? trustData.history : [];
  const statistics = trustData?.price_statistics;

  return (
    <div
      className="fixed inset-0 z-[120] flex items-end justify-center bg-slate-950/65 backdrop-blur-sm sm:items-center sm:p-6"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="trust-dialog-title"
        className="max-h-[92svh] w-full overflow-y-auto rounded-t-[30px] bg-white p-5 shadow-2xl sm:max-w-2xl sm:rounded-[30px] sm:p-6"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-black uppercase tracking-[0.2em] text-blue-700">
              Довіра й безпека
            </p>
            <h2 id="trust-dialog-title" className="mt-1 truncate text-2xl font-black">
              {property.title}
            </h2>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Закрити інформацію про довіру"
            className="rounded-2xl border border-slate-200 px-3 py-2 font-bold"
          >
            ✕
          </button>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <div className={`rounded-2xl border p-4 ${verifiedListing ? "border-emerald-200 bg-emerald-50" : "border-slate-200 bg-slate-50"}`}>
            <p className="text-xs font-black uppercase text-slate-500">Оголошення</p>
            <p className="mt-1 font-black">{verificationLabel(verificationStatus)}</p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-black uppercase text-slate-500">Тип продавця</p>
            <p className="mt-1 font-black">
              {sellerLabel(trustData?.seller_type || property.sellerType)}
            </p>
          </div>
        </div>

        {trustLoading ? (
          <p role="status" className="mt-5 rounded-2xl bg-slate-50 p-4">
            Завантажуємо статистику та історію…
          </p>
        ) : trustError ? (
          <p role="alert" className="mt-5 rounded-2xl bg-rose-50 p-4 text-rose-700">
            {trustError}
          </p>
        ) : (
          <>
            <div className="mt-5 rounded-2xl border border-blue-100 bg-blue-50 p-4">
              <p className="text-xs font-black uppercase text-blue-700">Статистика ціни</p>
              {statistics?.status === "ok" ? (
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="block text-slate-500">Медіанна ціна</span>
                    <b>${Number(statistics.median_price).toLocaleString("uk-UA")}</b>
                  </div>
                  <div>
                    <span className="block text-slate-500">Медіана за м²</span>
                    <b>${Number(statistics.median_price_per_sqm).toLocaleString("uk-UA")} / м²</b>
                  </div>
                  <p className="col-span-2 text-xs text-slate-600">
                    Вибірка: {statistics.sample_size} активних порівнюваних оголошень у цьому районі.
                  </p>
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-700">
                  Недостатньо даних: знайдено {statistics?.sample_size || 0} порівнюваних оголошень.
                </p>
              )}
            </div>
            <div className="mt-5">
              <p className="text-xs font-black uppercase text-slate-500">Історія змін</p>
              {history.length ? (
                <ol className="mt-3 space-y-3">
                  {history.map((item, index) => (
                    <li key={`${item.field_name}-${item.created_at}-${index}`} className="rounded-2xl border border-slate-200 p-3 text-sm">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <b>{HISTORY_LABELS[item.field_name] || "Зміна оголошення"}</b>
                        <time className="text-xs text-slate-500">
                          {new Intl.DateTimeFormat("uk-UA", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          }).format(new Date(item.created_at))}
                        </time>
                      </div>
                      <p className="mt-1 text-slate-600">
                        {historyValue(item.field_name, item.old_value)} →{" "}
                        <strong>{historyValue(item.field_name, item.new_value)}</strong>
                      </p>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="mt-2 text-sm text-slate-500">Історія ще не накопичена.</p>
              )}
            </div>
          </>
        )}

        <div className="mt-5 border-t border-slate-200 pt-5">
          {!showReportForm ? (
            <button
              type="button"
              onClick={() => setShowReportForm(true)}
              className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm font-black text-rose-700"
            >
              Повідомити про шахрайство
            </button>
          ) : (
            <form onSubmit={submitReport} className="rounded-2xl border border-rose-200 bg-rose-50 p-4">
              <label className="block text-xs font-black uppercase" htmlFor="report-reason">
                Причина
              </label>
              <select id="report-reason" value={reportReason} onChange={(event) => setReportReason(event.target.value)} className="mt-1 w-full rounded-xl border p-3">
                <option value="fraud_scam">Підозра на шахрайство</option>
                <option value="duplicate_listing">Дублікат оголошення</option>
                <option value="misleading_price">Неправдива ціна або опис</option>
                <option value="sold_or_unavailable">Об'єкт уже недоступний</option>
                <option value="spam">Спам</option>
                <option value="other">Інша причина</option>
              </select>
              <textarea value={reportDetails} onChange={(event) => setReportDetails(event.target.value)} minLength={10} maxLength={1000} required rows={4} className="mt-3 w-full rounded-xl border p-3" placeholder="Опишіть конкретні ознаки проблеми…" />
              {reportError ? <p role="alert" className="mt-2 text-rose-700">{reportError}</p> : null}
              {reportStatus ? <p role="status" className="mt-2 text-emerald-700">{reportStatus}</p> : null}
              <div className="mt-3 flex gap-2">
                <button type="submit" disabled={reportSubmitting} className="rounded-xl bg-rose-600 px-4 py-2 text-white">
                  {reportSubmitting ? "Надсилаємо…" : "Надіслати скаргу"}
                </button>
                <button type="button" onClick={() => setShowReportForm(false)} className="rounded-xl border bg-white px-4 py-2">
                  Скасувати
                </button>
              </div>
            </form>
          )}
        </div>
      </section>
    </div>
  );
}
