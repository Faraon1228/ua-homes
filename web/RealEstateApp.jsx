import React, { useEffect, useMemo, useRef, useState } from "./react-shim";
import {
  DEFAULT_SORT,
  STORAGE_KEYS,
  filterAndSortProperties,
  normalizePropertyType,
  resolveSortByForEOselya,
} from "./realEstateFilters";

const MOCK_PROPERTIES = [
  {
    id: 1,
    title: "Сучасна 2-кімнатна квартира, ЖК 'Грінвіль'",
    city: "Київ",
    district: "Печерський",
    price: 125000,
    rooms: 2,
    area: 68,
    eOselya: true,
    propertyType: "квартира",
    images: [
      "https://images.unsplash.com/photo-1560185007-c5ca9d2c014d?auto=format&fit=crop&w=1200&q=80",
      "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=1200&q=80",
    ],
  },
  {
    id: 2,
    title: "Видова смарт-квартира біля метро",
    city: "Київ",
    district: "Голосіївський",
    price: 48000,
    rooms: 1,
    area: 32,
    eOselya: true,
    propertyType: "квартира",
    images: [
      "https://images.unsplash.com/photo-1493809842364-78817add7ffb?auto=format&fit=crop&w=1200&q=80",
      "https://images.unsplash.com/photo-1484154218962-a197022b5858?auto=format&fit=crop&w=1200&q=80",
    ],
  },
  {
    id: 3,
    title: "Простора 3-к квартира для родини",
    city: "Львів",
    district: "Франківський",
    price: 95000,
    rooms: 3,
    area: 85,
    eOselya: false,
    propertyType: "будинок",
    images: [
      "https://images.unsplash.com/photo-1484154218962-a197022b5858?auto=format&fit=crop&w=1200&q=80",
      "https://images.unsplash.com/photo-1493809842364-78817add7ffb?auto=format&fit=crop&w=1200&q=80",
    ],
  },
];

const FALLBACK_IMAGE =
  "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1200' height='675' viewBox='0 0 1200 675'%3E%3Crect width='1200' height='675' fill='%23e2e8f0'/%3E%3Cpath d='M0 500h1200v175H0z' fill='%23cbd5e1'/%3E%3Ccircle cx='360' cy='260' r='70' fill='%23cbd5e1'/%3E%3Cpath d='M250 445l125-115 90 78 72-60 155 132H250z' fill='%2394a3b8'/%3E%3Ctext x='600' y='565' text-anchor='middle' font-family='Arial,sans-serif' font-size='28' fill='%23475569'%3EUA-Dim%3C/text%3E%3C/svg%3E";

const KEYWORD_SEARCH_KEY = "re.keywordSearch";
const SAVED_SEARCHES_KEY = "re.savedSearches";
const MAX_SAVED_SEARCHES = 10;
const RESULTS_VIEW_MODE_KEY = "ua_homes_view_mode_v1";
const CATALOG_PAGE_SIZE = 24;
const PWA_DISMISS_KEY = "uaDim.pwaDismissedUntil";
const PWA_INSTALLED_KEY = "uaDim.pwaInstalled";
const PWA_SESSION_HIDDEN_KEY = "uaDim.pwaHiddenForSession";
const PWA_DISMISS_DURATION_MS = 30 * 24 * 60 * 60 * 1000;

const QUICK_SCENARIOS = [
  {
    label: "Квартири",
    value: "квартира",
    filters: { cityFilter: "Всі", propertyTypeFilter: "квартира" },
  },
  {
    label: "Будинки",
    value: "будинок",
    filters: { cityFilter: "Всі", propertyTypeFilter: "будинок" },
  },
  {
    label: "Земельні ділянки",
    value: "земля",
    filters: { cityFilter: "Всі", propertyTypeFilter: "земля" },
  },
  {
    label: "Комерційні приміщення",
    value: "комерція",
    filters: { cityFilter: "Всі", propertyTypeFilter: "комерція" },
  },
];

const PROPERTY_TYPE_OPTIONS = [
  { value: "Всі", label: "Усі типи" },
  { value: "квартира", label: "Квартири" },
  { value: "будинок", label: "Будинки" },
  { value: "земля", label: "Земельні ділянки" },
  { value: "комерція", label: "Комерційні приміщення" },
];

const KEYWORD_SUGGESTIONS = [
  "ЖК",
  "метро",
  "центр",
  "з ремонтом",
  "тераса",
  "єОселя",
  "без комісії",
  "новобудова",
];

const SMART_SEARCH_PATH = "smart-search.html";
const SELLER_CABINET_PATH = "/seller";

function searchFiltersToAlertPayload(name, filters) {
  return {
    name,
    city: filters.cityFilter && filters.cityFilter !== "Всі" ? filters.cityFilter : null,
    type: filters.propertyType && filters.propertyType !== "Всі" ? filters.propertyType : null,
    eOselya: Boolean(filters.onlyEOselya),
    minPrice: filters.minPrice || null,
    maxPrice: filters.maxPrice || null,
    minRooms: filters.minRooms || null,
    maxRooms: filters.maxRooms || null,
    minArea: filters.minArea || null,
    maxArea: filters.maxArea || null,
    keywordSearch: filters.keywordSearch || null,
    sortBy: filters.sortBy || DEFAULT_SORT,
    channels: ["email"],
  };
}

function alertToSavedSearch(alert) {
  const filters = alert?.filters || {};
  return {
    id: `alert_${alert.id}`,
    serverId: alert.id,
    name: alert.name || "Збережений пошук",
    filters: {
      cityFilter: filters.city || "Всі",
      propertyType: filters.type || "Всі",
      onlyEOselya: Boolean(filters.eOselya),
      minPrice: filters.minPrice == null ? "" : String(filters.minPrice),
      maxPrice: filters.maxPrice == null ? "" : String(filters.maxPrice),
      minRooms: filters.minRooms == null ? "" : String(filters.minRooms),
      maxRooms: filters.maxRooms == null ? "" : String(filters.maxRooms),
      minArea: filters.minArea == null ? "" : String(filters.minArea),
      maxArea: filters.maxArea == null ? "" : String(filters.maxArea),
      sortBy: filters.sortBy || DEFAULT_SORT,
      keywordSearch: filters.keywordSearch || "",
    },
    isActive: Boolean(alert.is_active),
    lastSentAt: alert.last_sent_at || null,
    createdAt: alert.created_at ? Date.parse(alert.created_at) : Date.now(),
  };
}

function isLocalPreview() {
  return typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname);
}

function getSellerCabinetHref() {
  return isLocalPreview() ? "/real-estate-demo.html?seller=1" : SELLER_CABINET_PATH;
}

function getCatalogHref() {
  return isLocalPreview() ? "/real-estate-demo.html" : "/";
}

const INITIAL_LISTING_IMAGE_FIELDS = ["", "", ""];

// Ідентифікатори мають збігатися з ACCOUNT_TYPES у backend/app.py.
const ACCOUNT_TYPE_OPTIONS = [
  { id: "owner", label: "🏠 Власник", hint: "Продаю або здаю власне житло" },
  { id: "realtor", label: "🤝 Ріелтор", hint: "Працюю з клієнтами та об'єктами" },
  { id: "developer", label: "🏗️ Забудовник", hint: "Публікую новобудови та проєкти" },
];

function accountTypeOf(user) {
  if (user?.account_type === "developer") return "developer";
  if (user?.account_type === "realtor") return "realtor";
  return "owner";
}

function formatPlanQuota(usage) {
  if (!usage) return null;
  if (usage.listings_limit === null || usage.listings_limit === undefined) {
    return `${usage.listings_used} оголошень · без ліміту`;
  }
  return `${usage.listings_used} / ${usage.listings_limit} оголошень`;
}

function createInitialListingForm(initialValues = {}) {
  return {
    title: "",
    city: "Київ",
    district: "",
    propertyType: "квартира",
    conditionType: "вторинка",
    listingType: "sale",
    price: "",
    rooms: "",
    area: "",
    floor: "1",
    totalFloors: "1",
    yearBuilt: "",
    eOselya: false,
    description: "",
    images: [...INITIAL_LISTING_IMAGE_FIELDS],
    videos: [],
    ...initialValues,
  };
}

function normalizeImageSrc(src) {
  if (!src) return "";
  return src;
}

function getCloudinaryImageUrl(url, width) {
  if (!url || !url.includes("res.cloudinary.com/") || !url.includes("/image/upload/")) return "";
  return url.replace("/image/upload/", `/image/upload/f_auto,q_auto,c_fill,w_${width}/`);
}

function getFileContentType(file) {
  if (!file) return "";
  if (file.type && /^(image|video)\//.test(file.type)) return file.type;

  const fileName = (file.name || "").toLowerCase();
  const extension = fileName.match(/\.([a-z0-9]+)$/)?.[1] || "";
  const extensionMap = {
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    png: "image/png",
    webp: "image/webp",
    avif: "image/avif",
    heic: "image/heic",
    heif: "image/heif",
    gif: "image/gif",
    bmp: "image/bmp",
    tif: "image/tiff",
    tiff: "image/tiff",
    mp4: "video/mp4",
    mov: "video/quicktime",
    webm: "video/webm",
    m4v: "video/x-m4v",
  };

  return extensionMap[extension] || "";
}

function mapListingToProperty(listing) {
  const images = Array.isArray(listing?.images)
    ? listing.images.filter(Boolean)
    : [];
  const videos = Array.isArray(listing?.videos)
    ? listing.videos.filter(Boolean)
    : [];
  const latitude =
    listing?.latitude === null || listing?.latitude === undefined || listing?.latitude === ""
      ? null
      : Number(listing.latitude);
  const longitude =
    listing?.longitude === null || listing?.longitude === undefined || listing?.longitude === ""
      ? null
      : Number(listing.longitude);

  const normalizedPropertyType = normalizePropertyType(listing?.property_type || listing?.propertyType || "");

  return {
    id: listing?.id ?? 0,
    title: listing?.title || "Оголошення без назви",
    city: listing?.city || "",
    district: listing?.district || "",
    price: Number(listing?.price || 0),
    rooms: Number(listing?.rooms || 0),
    area: Number(listing?.area || 0),
    eOselya: Boolean(listing?.e_oselya ?? listing?.eOselya),
    propertyType: normalizedPropertyType || listing?.property_type || listing?.propertyType || "квартира",
    images,
    videos,
    imageCount: Number(listing?.image_count ?? images.length),
    videoCount: Number(listing?.video_count ?? videos.length),
    description: listing?.description || "",
    status: listing?.status || "published",
    latitude: Number.isFinite(latitude) ? latitude : null,
    longitude: Number.isFinite(longitude) ? longitude : null,
    moderationUpdatedAt: listing?.moderation_updated_at || listing?.moderationUpdatedAt || null,
    publishedAt: listing?.published_at || listing?.publishedAt || null,
    createdAt: listing?.created_at || listing?.createdAt || null,
    verifiedOwner: Boolean(listing?.verified_owner ?? listing?.verifiedOwner),
    ownerVerificationStatus:
      listing?.owner_verification_status || listing?.ownerVerificationStatus || "unverified",
    listingVerificationStatus:
      listing?.listing_verification_status || listing?.listingVerificationStatus || "unverified",
    verifiedListing: Boolean(listing?.verified_listing ?? listing?.verifiedListing),
    sellerType: listing?.seller_type || listing?.sellerType || "unknown",
  };
}

function isPositiveNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0;
}

function formatListingPrice(value) {
  return isPositiveNumber(value) ? `$${Number(value).toLocaleString("uk-UA")}` : "Ціну не вказано";
}

function formatPricePerSquareMeter(price, area) {
  if (!isPositiveNumber(price) || !isPositiveNumber(area)) return null;
  const value = Math.round(Number(price) / Number(area));
  return Number.isFinite(value) && value > 0 ? `$${value.toLocaleString("uk-UA")} / м²` : null;
}

function formatListingAddress(property) {
  const city = String(property?.city || "").trim();
  const district = String(property?.district || "").trim();
  const parts = [];
  if (city) parts.push(`м. ${city}`);
  if (district) parts.push(/район/i.test(district) ? district : `${district} район`);
  return parts.length ? parts.join(", ") : "Адресу не вказано";
}

function getListingDateMeta(property) {
  const candidates = [
    { value: property?.moderationUpdatedAt, label: "Оновлено" },
    { value: property?.publishedAt, label: "Опубліковано" },
    { value: property?.createdAt, label: "Створено" },
  ];
  const selected = candidates.find((candidate) => {
    if (!candidate.value) return false;
    return !Number.isNaN(new Date(candidate.value).getTime());
  });
  if (!selected) return null;
  return {
    label: selected.label,
    value: new Intl.DateTimeFormat("uk-UA", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(new Date(selected.value)),
  };
}

function isVerifiedSeller(property) {
  return property?.verifiedOwner === true && property?.ownerVerificationStatus === "verified";
}

function getSellerTypeLabel(sellerType) {
  return {
    owner: "Власник",
    intermediary: "Посередник",
    agency: "Агентство",
    developer: "Забудовник",
  }[sellerType] || "Тип продавця не вказано";
}

function getListingVerificationLabel(status) {
  return {
    verified: "Перевірене оголошення",
    pending: "Перевірка оголошення триває",
    rejected: "Перевірку оголошення не підтверджено",
    unverified: "Оголошення ще не перевірене",
  }[status] || "Статус перевірки не вказано";
}

function createClientToken(prefix) {
  const value =
    window.crypto && typeof window.crypto.randomUUID === "function"
      ? window.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;
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

function formatTrustHistoryValue(fieldName, value) {
  if (value === null || value === undefined || value === "") return "Не вказано";
  if (fieldName === "price") {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? `$${numericValue.toLocaleString("uk-UA")}` : String(value);
  }
  if (fieldName === "area") return `${Number(value).toLocaleString("uk-UA")} м²`;
  if (fieldName === "status") {
    return { published: "Опубліковано", pending: "На модерації", draft: "Чернетка", rejected: "Відхилено" }[value] || value;
  }
  if (fieldName === "listing_status") {
    return { active: "Активне", sold: "Продано", removed: "Знято" }[value] || value;
  }
  if (fieldName === "listing_verification_status") return getListingVerificationLabel(value);
  return String(value);
}

function getPreferredScrollBehavior() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

function useAccessibleDialog(isOpen, onClose, dialogRef, initialFocusRef) {
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return undefined;

    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusFrame = window.requestAnimationFrame(() => {
      initialFocusRef.current?.focus();
    });

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;

      const focusable = [
        ...dialogRef.current.querySelectorAll(
          'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
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

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      window.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus?.();
    };
  }, [dialogRef, initialFocusRef, isOpen]);
}

function TrustDialog({ property, authToken, onClose }) {
  const dialogRef = useRef(null);
  const closeButtonRef = useRef(null);
  const previousFocusRef = useRef(null);
  const [trustData, setTrustData] = useState(null);
  const [trustLoading, setTrustLoading] = useState(true);
  const [trustError, setTrustError] = useState("");
  const [showReportForm, setShowReportForm] = useState(false);
  const [reportReason, setReportReason] = useState("fraud_scam");
  const [reportDetails, setReportDetails] = useState("");
  const [reportStatus, setReportStatus] = useState("");
  const [reportError, setReportError] = useState("");
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState(() => createClientToken("report"));

  useEffect(() => {
    previousFocusRef.current = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [
        ...dialogRef.current.querySelectorAll(
          'button:not([disabled]),a[href],select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
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

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus?.();
    };
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    setTrustLoading(true);
    setTrustError("");
    fetch(getApiUrl(`/listings/${property.id}/trust`), {
      headers: authToken ? { Authorization: ["Bearer", authToken].join(" ") } : {},
      signal: controller.signal,
    })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Не вдалося завантажити дані довіри");
        return result;
      })
      .then(setTrustData)
      .catch((error) => {
        if (error.name !== "AbortError") setTrustError(error.message || "Не вдалося завантажити дані довіри");
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
          ...(authToken ? { Authorization: ["Bearer", authToken].join(" ") } : {}),
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
          ? "Цю скаргу вже отримано. Повторно надсилати її не потрібно."
          : "Скаргу надіслано команді модерації."
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
    trustData?.listing_verification_status || property.listingVerificationStatus || "unverified";
  const verifiedListing = trustData
    ? trustData.verified_listing === true
    : property.verifiedListing === true;
  const sellerType = trustData?.seller_type || property.sellerType || "unknown";
  const statistics = trustData?.price_statistics;
  const history = Array.isArray(trustData?.history) ? trustData.history : [];
  const historyLabels = {
    price: "Ціна",
    status: "Статус публікації",
    listing_status: "Статус об'єкта",
    property_type: "Тип нерухомості",
    rooms: "Кількість кімнат",
    area: "Площа",
    listing_verification_status: "Перевірка оголошення",
  };

  return (
    <div
      className="fixed inset-0 z-[120] flex items-end justify-center bg-slate-950/65 p-0 backdrop-blur-sm sm:items-center sm:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="trust-dialog-title"
        aria-describedby="trust-dialog-description"
        className="max-h-[92svh] w-full overflow-y-auto rounded-t-[30px] bg-white p-5 shadow-2xl sm:max-w-2xl sm:rounded-[30px] sm:p-6"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-black uppercase tracking-[0.2em] text-blue-700">Довіра й безпека</p>
            <h2 id="trust-dialog-title" className="mt-1 truncate text-2xl font-black text-slate-900">
              {property.title}
            </h2>
            <p id="trust-dialog-description" className="mt-1 text-sm text-slate-600">
              Перевірка оголошення, тип продавця, статистика ціни та історія змін.
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Закрити інформацію про довіру"
            className="shrink-0 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            ✕
          </button>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <div className={`rounded-2xl border p-4 ${verifiedListing ? "border-emerald-200 bg-emerald-50" : "border-slate-200 bg-slate-50"}`}>
            <p className="text-xs font-black uppercase tracking-wide text-slate-500">Оголошення</p>
            <p className={`mt-1 font-black ${verifiedListing ? "text-emerald-800" : "text-slate-700"}`}>
              {getListingVerificationLabel(verificationStatus)}
            </p>
            <p className="mt-1 text-xs text-slate-500">Цей статус окремий від перевірки продавця.</p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-black uppercase tracking-wide text-slate-500">Тип продавця</p>
            <p className="mt-1 font-black text-slate-900">{getSellerTypeLabel(sellerType)}</p>
            <p className="mt-1 text-xs text-slate-500">За нормалізованим типом акаунта.</p>
          </div>
        </div>

        {trustLoading ? (
          <p role="status" aria-live="polite" className="mt-5 rounded-2xl bg-slate-50 p-4 text-sm font-semibold text-slate-600">Завантажуємо статистику та історію…</p>
        ) : trustError ? (
          <p role="alert" className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">
            {trustError}
          </p>
        ) : (
          <>
            <div className="mt-5 rounded-2xl border border-blue-100 bg-blue-50 p-4">
              <p className="text-xs font-black uppercase tracking-wide text-blue-700">Статистика ціни</p>
              {statistics?.status === "ok" ? (
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="block text-slate-500">Медіанна ціна</span>
                    <b className="text-slate-900">${Number(statistics.median_price).toLocaleString("uk-UA")}</b>
                  </div>
                  <div>
                    <span className="block text-slate-500">Медіана за м²</span>
                    <b className="text-slate-900">${Number(statistics.median_price_per_sqm).toLocaleString("uk-UA")} / м²</b>
                  </div>
                  <p className="col-span-2 text-xs text-slate-600">
                    Вибірка: {statistics.sample_size} активних порівнюваних оголошень у цьому районі.
                  </p>
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-600">
                  Недостатньо даних: знайдено {statistics?.sample_size || 0} порівнюваних активних оголошень, потрібно щонайменше 3.
                </p>
              )}
            </div>

            <div className="mt-5">
              <p className="text-xs font-black uppercase tracking-wide text-slate-500">Історія змін</p>
              {history.length ? (
                <ol className="mt-3 space-y-3">
                  {history.map((item, index) => (
                    <li
                      key={`${item.field_name}-${item.created_at}-${index}`}
                      className="rounded-2xl border border-slate-200 bg-white p-3 text-sm"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <b className="text-slate-900">{historyLabels[item.field_name] || "Зміна оголошення"}</b>
                        <time className="text-xs text-slate-500">
                          {new Intl.DateTimeFormat("uk-UA", { day: "numeric", month: "short", year: "numeric" }).format(
                            new Date(item.created_at)
                          )}
                        </time>
                      </div>
                      <p className="mt-1 text-slate-600">
                        {formatTrustHistoryValue(item.field_name, item.old_value)} →{" "}
                        <strong>{formatTrustHistoryValue(item.field_name, item.new_value)}</strong>
                      </p>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="mt-2 text-sm text-slate-500">Історія ще не накопичена. Ретроспективні зміни не генеруються.</p>
              )}
            </div>
          </>
        )}

        <div className="mt-5 border-t border-slate-200 pt-5">
          {!showReportForm ? (
            <button
              type="button"
              onClick={() => setShowReportForm(true)}
              className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm font-black text-rose-700 transition hover:bg-rose-100"
            >
              Повідомити про шахрайство
            </button>
          ) : (
            <form
              onSubmit={submitReport}
              aria-busy={reportSubmitting}
              className="rounded-2xl border border-rose-200 bg-rose-50 p-4"
            >
              <h3 className="font-black text-rose-900">Скарга на оголошення</h3>
              <p id="report-help" className="mt-1 text-xs text-rose-700">Скарга потрапить у backend модерації; контактні дані публічно не показуються.</p>
              <label className="mt-4 block text-xs font-black uppercase tracking-wide text-slate-600" htmlFor="report-reason">
                Причина
              </label>
              <select
                id="report-reason"
                value={reportReason}
                onChange={(event) => setReportReason(event.target.value)}
                className="mt-1 w-full rounded-xl border border-rose-200 bg-white p-3 text-sm"
              >
                <option value="fraud_scam">Підозра на шахрайство</option>
                <option value="duplicate_listing">Дублікат оголошення</option>
                <option value="misleading_price">Неправдива ціна або опис</option>
                <option value="sold_or_unavailable">Об'єкт уже недоступний</option>
                <option value="spam">Спам</option>
                <option value="other">Інша причина</option>
              </select>
              <label className="mt-3 block text-xs font-black uppercase tracking-wide text-slate-600" htmlFor="report-details">
                Деталі
              </label>
              <textarea
                id="report-details"
                value={reportDetails}
                onChange={(event) => setReportDetails(event.target.value)}
                minLength={10}
                maxLength={1000}
                required
                rows={4}
                placeholder="Опишіть конкретні ознаки проблеми…"
                aria-describedby={`report-help${reportError ? " report-error" : ""}${reportStatus ? " report-status" : ""}`}
                className="mt-1 w-full rounded-xl border border-rose-200 bg-white p-3 text-sm"
              />
              <div className="mt-2 text-sm">
                {reportError ? <p id="report-error" role="alert" className="font-semibold text-rose-700">{reportError}</p> : null}
                {reportStatus ? <p id="report-status" role="status" aria-live="polite" className="font-semibold text-emerald-700">{reportStatus}</p> : null}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="submit"
                  disabled={reportSubmitting}
                  className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-black text-white disabled:opacity-60"
                >
                  {reportSubmitting ? "Надсилаємо…" : "Надіслати скаргу"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowReportForm(false);
                    setReportError("");
                  }}
                  className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700"
                >
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

let leafletLoader = null;

function ensureLeafletLoaded() {
  if (window.L?.map) return Promise.resolve(window.L);
  if (leafletLoader) return leafletLoader;

  leafletLoader = new Promise((resolve, reject) => {
    if (!document.getElementById("uah-leaflet-css")) {
      const link = document.createElement("link");
      link.id = "uah-leaflet-css";
      link.rel = "stylesheet";
      link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(link);
    }

    const existingScript = document.getElementById("uah-leaflet-js");
    if (existingScript) {
      existingScript.addEventListener("load", () => resolve(window.L), { once: true });
      existingScript.addEventListener("error", () => reject(new Error("Не вдалося завантажити карту")), {
        once: true,
      });
      return;
    }

    const script = document.createElement("script");
    script.id = "uah-leaflet-js";
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.async = true;
    script.onload = () => resolve(window.L);
    script.onerror = () => reject(new Error("Не вдалося завантажити карту"));
    document.head.appendChild(script);
  });

  return leafletLoader;
}

function hasMapCoordinates(property) {
  const latitude = Number(property?.latitude);
  const longitude = Number(property?.longitude);
  return (
    Number.isFinite(latitude) &&
    Number.isFinite(longitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180 &&
    !(latitude === 0 && longitude === 0)
  );
}

function ListingsMapView({ properties, onShowList }) {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const markersLayerRef = useRef(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState("");
  const mappedProperties = useMemo(() => properties.filter(hasMapCoordinates), [properties]);
  const missingCoordinatesCount = properties.length - mappedProperties.length;

  useEffect(() => {
    let cancelled = false;

    ensureLeafletLoaded()
      .then((Leaflet) => {
        if (cancelled || !mapContainerRef.current || mapRef.current) return;
        const map = Leaflet.map(mapContainerRef.current, { zoomControl: true }).setView([49.0, 31.2], 6);
        Leaflet.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 18,
          attribution: "&copy; OpenStreetMap",
        }).addTo(map);
        mapRef.current = map;
        markersLayerRef.current = Leaflet.layerGroup().addTo(map);
        setMapReady(true);
        window.requestAnimationFrame(() => map.invalidateSize());
      })
      .catch((error) => {
        if (!cancelled) setMapError(error.message || "Не вдалося завантажити карту");
      });

    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
      markersLayerRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!mapReady || !mapRef.current || !markersLayerRef.current || !window.L) return;

    const Leaflet = window.L;
    const markersLayer = markersLayerRef.current;
    markersLayer.clearLayers();
    const bounds = [];

    mappedProperties.forEach((property) => {
      const point = [Number(property.latitude), Number(property.longitude)];
      const marker = Leaflet.marker(point, {
        title: property.title,
        alt: `${property.title}, ${property.city}, ${property.district}`,
        keyboard: false,
      });
      const popup = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = property.title;
      const details = document.createElement("p");
      details.style.margin = "6px 0 0";
      details.textContent = `$${property.price.toLocaleString("uk-UA")} · ${property.city}, ${property.district}`;
      popup.append(title, details);
      marker.bindPopup(popup);
      markersLayer.addLayer(marker);
      bounds.push(point);
    });

    if (bounds.length) {
      mapRef.current.fitBounds(bounds, { padding: [32, 32], maxZoom: 14 });
    } else {
      mapRef.current.setView([49.0, 31.2], 6);
    }
    window.requestAnimationFrame(() => mapRef.current?.invalidateSize());
  }, [mapReady, mappedProperties]);

  return (
    <div
      id="listings-map"
      aria-busy={!mapReady && !mapError}
      className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm"
    >
      <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-black text-slate-900">
            На карті {mappedProperties.length} з {properties.length} об&apos;єктів
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {!properties.length
              ? "Немає результатів для відображення."
              : missingCoordinatesCount
              ? `${missingCoordinatesCount} без координат залишаються доступними у списку.`
              : "Усі результати мають координати."}
          </p>
        </div>
        {missingCoordinatesCount ? (
          <button
            type="button"
            onClick={onShowList}
            className="self-start rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-bold text-blue-700 transition hover:bg-blue-100 sm:self-auto"
          >
            Показати весь список
          </button>
        ) : null}
      </div>
      <p id="map-access-help" className="sr-only">
        Оголошення на карті доступні як посилання нижче. Усі результати також доступні в режимі списку.
      </p>
      <ul className="sr-only">
        {mappedProperties.map((property) => (
          <li key={`map-access-${property.id}`}>
            <a href={`/listing/${property.id}`}>
              {property.title}, {property.city}, {property.district}
            </a>
          </li>
        ))}
      </ul>
      {mapError ? (
        <div role="alert" className="px-5 py-16 text-center">
          <p className="font-bold text-rose-700">{mapError}</p>
          <p className="mt-2 text-sm text-slate-500">Результати залишаються доступними у режимі списку.</p>
          <button
            type="button"
            onClick={onShowList}
            className="mt-4 rounded-xl bg-slate-900 px-4 py-2 text-sm font-bold text-white"
          >
            Повернутися до списку
          </button>
        </div>
      ) : (
        <div className="relative">
          <div
            ref={mapContainerRef}
            className="h-[420px] w-full sm:h-[520px]"
            role="region"
            aria-label={`Карта результатів: координати мають ${mappedProperties.length} із ${properties.length}`}
            aria-describedby="map-access-help"
          />
          {!mapReady ? (
            <div className="absolute inset-0 grid place-items-center bg-slate-50">
              <p role="status" aria-live="polite" className="text-sm font-semibold text-slate-600">Завантажуємо карту…</p>
            </div>
          ) : null}

        </div>
      )}
    </div>
  );
}

function mapListingToForm(listing) {
  const images = Array.isArray(listing?.images) ? listing.images.filter(Boolean).slice(0, 8) : [];
  while (images.length < INITIAL_LISTING_IMAGE_FIELDS.length) {
    images.push("");
  }

  return {
    title: listing?.title || "",
    city: listing?.city || "Київ",
    district: listing?.district || "",
    propertyType: listing?.property_type || listing?.propertyType || "квартира",
    conditionType: listing?.condition_type || listing?.conditionType || "вторинка",
    listingType: listing?.listing_type || listing?.listingType || "sale",
    price: listing?.price != null ? String(listing.price) : "",
    rooms: listing?.rooms != null ? String(listing.rooms) : "",
    area: listing?.area != null ? String(listing.area) : "",
    floor: listing?.floor != null ? String(listing.floor) : "1",
    totalFloors: listing?.total_floors != null ? String(listing.total_floors) : "1",
    yearBuilt: listing?.year_built != null ? String(listing.year_built) : "",
    eOselya: Boolean(listing?.e_oselya ?? listing?.eOselya),
    description: listing?.description || "",
    images,
    videos: Array.isArray(listing?.videos) ? listing.videos.filter(Boolean).slice(0, 2) : [],
  };
}

function getListingStatusLabel(listing) {
  if (listing?.status === "published" && listing?.listing_status === "active") return "Активне";
  if (listing?.status === "published") return "Опубліковано";
  if (listing?.moderation_status === "approved") return "Підтверджено";
  if (listing?.moderation_status === "changes_requested") return "Потрібні правки";
  if (listing?.moderation_status === "rejected" || listing?.status === "rejected") return "Відхилено";
  return "На модерації";
}

function getListingCompleteness(listing) {
  const images = Array.isArray(listing?.images) ? listing.images.filter(Boolean) : [];
  const imageCount = Number(listing?.image_count ?? listing?.imageCount ?? images.length);
  const checks = [
    { id: "photos", label: "3+ фото", points: 30, complete: imageCount >= 3 },
    { id: "description", label: "Повний опис", points: 20, complete: String(listing?.description || "").trim().length >= 100 },
    { id: "phone", label: "Телефон", points: 20, complete: Boolean(listing?.verified_phone || listing?.phone_verified) },
    { id: "tour", label: "Фото або відеотур", points: 15, complete: Boolean(listing?.has_photo_tour || listing?.has_video_tour) },
    { id: "owner", label: "Власник або документи", points: 15, complete: Boolean(listing?.verified_owner || listing?.verified_docs) },
  ];
  const score = checks.reduce((total, item) => total + (item.complete ? item.points : 0), 0);
  return { score, checks, imagesCount: imageCount };
}

function getListingPipeline(listing) {
  const rejected = listing?.moderation_status === "rejected";
  let activeStep = 0;
  if (listing?.moderation_status === "pending_review") activeStep = 1;
  if (listing?.status === "published" || listing?.moderation_status === "approved") activeStep = 2;
  if (listing?.status === "archived" || ["sold", "removed"].includes(listing?.listing_status)) activeStep = 3;
  return {
    activeStep,
    rejected,
    steps: ["Чернетка", "Перевірка", "На сайті", "Завершено"],
  };
}

function getStored(key, fallback) {
  if (typeof window === "undefined") return fallback;
  const value = window.localStorage.getItem(key);
  return value ?? fallback;
}

function hasActivePwaDismissal() {
  if (typeof window === "undefined") return false;
  const dismissedUntil = Number(window.localStorage.getItem(PWA_DISMISS_KEY));
  if (Number.isFinite(dismissedUntil) && dismissedUntil > Date.now()) return true;

  if (window.localStorage.getItem("uaDim.pwaDismissed") === "true") {
    window.localStorage.removeItem("uaDim.pwaDismissed");
    window.localStorage.setItem(PWA_DISMISS_KEY, String(Date.now() + PWA_DISMISS_DURATION_MS));
    return true;
  }
  return false;
}

function isPwaRunningStandalone() {
  if (typeof window === "undefined") return false;
  return (
    window.navigator.standalone === true ||
    window.matchMedia?.("(display-mode: standalone)")?.matches === true
  );
}

function safeParseJSON(value, fallback) {
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function getStoredJSON(key, fallback) {
  if (typeof window === "undefined") return fallback;
  try {
    const value = window.localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
}

function formatCurrency(value) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return "0 ₴";
  return `${numericValue.toLocaleString("uk-UA", { maximumFractionDigits: 0 })} ₴`;
}

function getApiBaseUrl() {
  if (typeof window === "undefined") return "/api";
  const configured = (window.UA_HOMES_API || "").trim();
  if (configured) return configured.replace(/\/+$/, "");
  const hostname = window.location.hostname || "";
  if (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "0.0.0.0") {
    return "http://127.0.0.1:5050";
  }
  return window.location.origin;
}

function getApiUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getApiBaseUrl()}/api${normalizedPath}`;
}

function allowMockCatalogFallback() {
  if (typeof window === "undefined") return true;
  return window.location.protocol === "file:";
}

function describeSearchState(filters, keywordSearch) {
  const parts = [];
  if (filters.cityFilter && filters.cityFilter !== "Всі") {
    parts.push(filters.cityFilter);
  } else {
    parts.push("Вся Україна");
  }
  if (filters.propertyType && filters.propertyType !== "Всі") {
    const selectedType = PROPERTY_TYPE_OPTIONS.find((option) => option.value === filters.propertyType);
    parts.push(selectedType?.label || filters.propertyType);
  }
  if (filters.onlyEOselya) parts.push("єОселя");
  if (filters.minRooms || filters.maxRooms) {
    parts.push(`${filters.minRooms || "1"}-${filters.maxRooms || "∞"} кімн.`);
  }
  if (filters.minPrice || filters.maxPrice) {
    parts.push(`$${filters.minPrice || "0"}-${filters.maxPrice || "∞"}`);
  }
  if (filters.minArea || filters.maxArea) {
    parts.push(`${filters.minArea || "0"}-${filters.maxArea || "∞"} м²`);
  }
  if (keywordSearch.trim()) parts.push(`"${keywordSearch.trim()}"`);
  return parts.length ? parts.join(" · ") : "Спробуйте швидкий сценарій або ключове слово.";
}

function SmartSearchPage({
  keywordInputRef,
  keywordDraft,
  setKeywordDraft,
  applyKeywordSearch,
  clearKeywordSearch,
  searchSummary,
  oneClickChips,
  activeFilters,
  clearActiveFilter,
  visibleProperties,
  filteredProperties,
  totalProperties,
  favoriteIds,
  toggleFavorite,
  showFavoritesOnly,
  setShowFavoritesOnly,
  saveCurrentSearch,
  resetFilters,
  onOpenTrust,
  trustDialog,
}) {
  const previewProperties = visibleProperties.slice(0, 6);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-50 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-4">
          <a
            href="real-estate-demo.html"
            className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-bold text-slate-700 transition hover:bg-slate-100"
          >
            ← Повернутися
          </a>
          <div className="text-center">
            <div className="text-lg font-black tracking-tight text-transparent bg-gradient-to-r from-slate-950 via-blue-700 to-cyan-500 bg-clip-text drop-shadow-[0_0_12px_rgba(59,130,246,0.45)]">
              UA-DIM
            </div>
            <div className="text-xs font-semibold text-blue-700">Розумний пошук</div>
          </div>
          <a
            href="real-estate-demo.html"
            className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700"
          >
            Повний каталог
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8">
        <div className="grid gap-6 lg:grid-cols-12">
          <section className="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm lg:col-span-8">
            <p className="text-xs font-black uppercase tracking-[0.28em] text-blue-600">РОЗУМНИЙ ПОШУК</p>
            <h1 className="mt-3 text-4xl font-black tracking-tight text-slate-900 sm:text-5xl">UA-DIM</h1>
            <p className="mt-4 max-w-2xl text-base leading-relaxed text-slate-600">
              Швидкий пошук по тексту, району, ЖК чи метро. Зберігайте запити, перемикайте сценарії та одразу
              дивіться релевантні результати.
            </p>
            <div className="mt-6 rounded-[28px] border border-blue-100 bg-blue-50 p-4">
              <label htmlFor="smart-search-query" className="mb-2 block text-xs font-black uppercase tracking-wide text-blue-800">
                Ключові слова
              </label>
              <div className="flex flex-col gap-3 sm:flex-row">
                <input
                  id="smart-search-query"
                  ref={keywordInputRef}
                  type="text"
                  value={keywordDraft}
                  onChange={(e) => setKeywordDraft(e.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      applyKeywordSearch();
                    }
                  }}
                  placeholder="ЖК, метро, район, ремонт..."
                  className="flex-1 rounded-2xl border border-blue-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                />
                <button
                  type="button"
                  onClick={applyKeywordSearch}
                  className="rounded-2xl bg-blue-600 px-5 py-3 text-sm font-bold text-white transition hover:bg-blue-700"
                >
                  Шукати
                </button>
              </div>
              <p className="mt-3 text-sm text-slate-700">{searchSummary}</p>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {oneClickChips.slice(0, 6).map((chip) => (
                <button
                  key={chip.label}
                  type="button"
                  onClick={chip.action}
                  className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                >
                  {chip.label}
                </button>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={saveCurrentSearch}
                className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700"
              >
                Зберегти запит
              </button>
              <button
                type="button"
                onClick={resetFilters}
                className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700 transition hover:bg-slate-50"
              >
                Скинути
              </button>
              <button
                type="button"
                onClick={() => setShowFavoritesOnly((current) => !current)}
                className={`rounded-2xl px-4 py-2 text-sm font-bold transition ${
                  showFavoritesOnly
                    ? "bg-rose-600 text-white hover:bg-rose-700"
                    : "border border-rose-200 bg-white text-rose-700 hover:bg-rose-50"
                }`}
              >
                {showFavoritesOnly ? "Лише обрані" : "Показати обрані"}
              </button>
              <button
                type="button"
                onClick={clearKeywordSearch}
                className="rounded-2xl border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-bold text-blue-700 transition hover:bg-blue-100"
              >
                Очистити текст
              </button>
            </div>
          </section>

          <aside className="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm lg:col-span-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-black uppercase tracking-wide text-slate-500">Поточний стан</p>
                <p className="mt-1 text-2xl font-black text-slate-900">Пошук</p>
              </div>
              <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700">
                {totalProperties} знайдено
              </span>
            </div>

            <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-black uppercase tracking-wide text-slate-500">Фільтри</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {activeFilters.length ? (
                  activeFilters.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => clearActiveFilter(item.key)}
                      className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-blue-200 hover:bg-blue-50"
                    >
                      {item.label}
                    </button>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">Активних фільтрів немає.</p>
                )}
              </div>
            </div>

            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-4">
              <p className="text-xs font-black uppercase tracking-wide text-rose-700">Обрані</p>
              <p className="mt-1 text-sm text-slate-600">
                {favoriteIds.length ? `Збережено ${favoriteIds.length} об'єктів.` : "Додайте об'єкти в обране."}
              </p>
            </div>
          </aside>
        </div>

        <div className="mt-8 flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-black uppercase tracking-wide text-slate-500">Релевантні результати</p>
            <h2 className="mt-1 text-2xl font-black text-slate-900">
              {visibleProperties.length ? `Показано ${previewProperties.length} з ${totalProperties}` : "Нічого не знайдено"}
            </h2>
          </div>
          <a
            href="real-estate-demo.html"
            className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700"
          >
            Відкрити повний каталог
          </a>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
          {previewProperties.map((property, cardIndex) => (
            <ListingCard
              key={property.id}
              property={property}
              favorite={favoriteIds.includes(property.id)}
              onToggleFavorite={toggleFavorite}
              onOpenTrust={onOpenTrust}
              priority={false}
            />
          ))}
        </div>
      </main>
      {trustDialog}
    </div>
  );
}

function PhotoGallery({ images, title, href, priority = false }) {
  const [index, setIndex] = useState(0);
  const failedImagesRef = useRef(new Set());
  const items = Array.isArray(images) ? images.map(normalizeImageSrc).filter(Boolean) : [];
  const isFallback = !items.length;

  const prev = (e) => {
    e.stopPropagation();
    setIndex((current) => (current - 1 + items.length) % items.length);
  };

  const next = (e) => {
    e.stopPropagation();
    setIndex((current) => (current + 1) % items.length);
  };

  // Generate WebP/AVIF variants from original URL
  // If S3 upload was optimized, URL format: https://bucket/listings/123/abc/photo-medium.webp
  // Fallback to original if optimization not available
  const getImageVariants = (url) => {
    if (!url) return { original: url, webp: null, avif: null };
    
    // If already optimized (S3 URL with size suffix), extract base and create variants
    const urlObj = new URL(url, window.location.origin);
    const pathname = urlObj.pathname;
    
    // Check if it's an S3 URL with optimization
    if (pathname.includes('listings/') && (pathname.includes('-medium') || pathname.includes('-large') || pathname.includes('-thumbnail'))) {
      // Already optimized, just return the WebP version
      return {
        original: url,
        webp: url.endsWith('.webp') ? url : url.replace(/\.(jpg|png)$/, '-medium.webp'),
        avif: url.endsWith('.avif') ? url : url.replace(/\.(jpg|png)$/, '-medium.avif')
      };
    }
    
    // Original image (fallback if optimization not available)
    return { original: url, webp: null, avif: null };
  };

  const currentImage = items[index] || FALLBACK_IMAGE;
  const variants = getImageVariants(currentImage);
  const cloudinarySources = [480, 768, 1200]
    .map((width) => {
      const url = getCloudinaryImageUrl(currentImage, width);
      return url ? `${url} ${width}w` : "";
    })
    .filter(Boolean)
    .join(", ");
  const optimizedOriginal = getCloudinaryImageUrl(currentImage, 1200) || variants.original;
  const picture = (
    <picture className="block h-full w-full">
      {variants.avif && (
        <source srcSet={variants.avif} type="image/avif" />
      )}
      {variants.webp && (
        <source srcSet={variants.webp} type="image/webp" />
      )}
      <img
        src={optimizedOriginal}
        srcSet={cloudinarySources || undefined}
        sizes={cloudinarySources ? "(max-width: 767px) calc(100vw - 36px), 402px" : undefined}
        alt={isFallback ? `Фото для оголошення «${title}» відсутнє` : `Фото оголошення «${title}»`}
        width="1200"
        height="900"
        loading={priority ? "eager" : "lazy"}
        fetchPriority={priority ? "high" : "auto"}
        decoding={priority ? "sync" : "async"}
        className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.02]"
        onError={(event) => {
          if (event.currentTarget.getAttribute("src") === FALLBACK_IMAGE) return;
          failedImagesRef.current.add(currentImage);
          const nextIndex = items.findIndex((item) => !failedImagesRef.current.has(item));
          if (nextIndex >= 0) {
            setIndex(nextIndex);
            return;
          }
          event.currentTarget.setAttribute("src", FALLBACK_IMAGE);
        }}
      />
    </picture>
  );

  return (
    <div className="relative aspect-[4/3] overflow-hidden bg-slate-200">
      {href ? (
        <a href={href} className="block h-full w-full" aria-label={`Відкрити оголошення «${title}»`}>
          {picture}
        </a>
      ) : (
        picture
      )}
      
      {items.length > 1 && (
        <>
          <button
            type="button"
            onClick={prev}
            className="absolute left-3 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-black/70 p-0 text-white hover:bg-black/85"
            aria-label="Попереднє фото"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={next}
            className="absolute right-3 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-black/70 p-0 text-white hover:bg-black/85"
            aria-label="Наступне фото"
          >
            ›
          </button>
        </>
      )}
    </div>
  );
}

function ListingCard({ property, favorite, onToggleFavorite, onOpenTrust, priority = false }) {
  const href = property?.id ? `/listing/${property.id}` : null;
  const pricePerSquareMeter = formatPricePerSquareMeter(property?.price, property?.area);
  const dateMeta = getListingDateMeta(property);
  const verifiedSeller = isVerifiedSeller(property);

  return (
    <article
      data-role="listing-card"
      className="group min-w-0 overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm transition hover:-translate-y-1 hover:shadow-xl"
    >
      <div className="relative">
        <PhotoGallery images={property.images} title={property.title} href={href} priority={priority} />
        <div className="pointer-events-none absolute left-3 top-3 flex max-w-[calc(100%-5rem)] flex-wrap gap-2">
          {property.eOselya ? (
            <span className="rounded-full bg-blue-600 px-3 py-1.5 text-[10px] font-black uppercase tracking-wider text-white shadow-md">
              єОселя
            </span>
          ) : null}
          {verifiedSeller ? (
            <span className="rounded-full bg-emerald-700 px-3 py-1.5 text-[10px] font-black uppercase tracking-wide text-white shadow-md">
              ✓ Перевірений продавець
            </span>
          ) : null}
          {property.verifiedListing ? (
            <span className="rounded-full bg-teal-700 px-3 py-1.5 text-[10px] font-black uppercase tracking-wide text-white shadow-md">
              ✓ Перевірене оголошення
            </span>
          ) : null}
          {property.videos?.length ? (
            <span className="rounded-full bg-slate-900 px-3 py-1.5 text-[10px] font-black uppercase tracking-wide text-white shadow-md">
              ▶ Відео
            </span>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => onToggleFavorite(property)}
          className="absolute right-3 top-3 flex h-11 w-11 items-center justify-center rounded-full bg-white/95 text-lg shadow-lg backdrop-blur transition hover:bg-white"
          aria-label={favorite ? `Прибрати ${property.title} з обраного` : `Додати ${property.title} в обране`}
          aria-pressed={favorite}
        >
          {favorite ? "❤️" : "🤍"}
        </button>
      </div>

      <div className="p-5">
        <div className="flex flex-col gap-1">
          <p className={`text-2xl font-black tracking-tight ${isPositiveNumber(property.price) ? "text-blue-700" : "text-slate-500"}`}>
            {formatListingPrice(property.price)}
          </p>
          <p className="text-sm font-bold text-slate-500">
            {pricePerSquareMeter || "Ціна за м² недоступна"}
          </p>
        </div>

        <h3 className="mt-4 line-clamp-2 text-xl font-black leading-snug text-slate-900">
          {href ? (
            <a href={href} className="inline-flex min-h-[44px] items-center transition hover:text-blue-700">
              {property.title}
            </a>
          ) : (
            property.title
          )}
        </h3>

        <p className="mt-3 flex items-start gap-2 text-sm font-semibold leading-relaxed text-slate-600">
          <span aria-hidden="true">📍</span>
          <span>{formatListingAddress(property)}</span>
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          {isPositiveNumber(property.rooms) ? (
            <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-bold text-slate-700">
              {property.rooms} кімн.
            </span>
          ) : null}
          {isPositiveNumber(property.area) ? (
            <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-bold text-slate-700">
              {property.area} м²
            </span>
          ) : null}
          <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-bold capitalize text-slate-700">
            {property.propertyType}
          </span>
        </div>

        <div className="mt-5 flex flex-col gap-1.5 border-t border-slate-100 pt-4 text-xs">
          <span className="font-semibold text-slate-500">
            {dateMeta ? `${dateMeta.label} ${dateMeta.value}` : "Дата не вказана"}
          </span>
          <span className={`font-bold ${verifiedSeller ? "text-emerald-700" : "text-slate-400"}`}>
            {verifiedSeller ? "Продавця підтверджено" : "Статус продавця не підтверджено"}
          </span>
          <span className="font-bold text-slate-600">{getSellerTypeLabel(property.sellerType)}</span>
        </div>

        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {property?.id && onOpenTrust ? (
            <button
              type="button"
              onClick={(event) => onOpenTrust(property, event.currentTarget)}
              className="inline-flex min-h-[44px] items-center justify-center rounded-2xl border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-black text-blue-700 transition hover:bg-blue-100"
            >
              Довіра й безпека
            </button>
          ) : null}
          {href ? (
            <a
              href={href}
              className="inline-flex min-h-[44px] items-center justify-center rounded-2xl bg-slate-900 px-4 py-2.5 text-sm font-black text-white transition hover:bg-blue-700"
            >
              Переглянути
            </a>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export default function RealEstateApp() {
  const sellerCabinetMode =
    typeof window !== "undefined" &&
    (/^\/seller\/?$/.test(window.location.pathname) ||
      new URLSearchParams(window.location.search).get("seller") === "1");
  const keywordInputRef = useRef(null);
  const mobileFiltersTriggerRef = useRef(null);
  const mobileFiltersDrawerRef = useRef(null);
  const mobileFiltersCloseRef = useRef(null);
  const eOselyaDialogRef = useRef(null);
  const eOselyaCloseRef = useRef(null);
  const planDialogRef = useRef(null);
  const planCloseRef = useRef(null);
  const listingDialogRef = useRef(null);
  const listingCloseRef = useRef(null);
  const deleteDialogRef = useRef(null);
  const deleteCancelRef = useRef(null);
  const [cityFilter, setCityFilter] = useState(() => getStored("re.cityFilter", "Всі"));
  const [propertyTypeFilter, setPropertyTypeFilter] = useState(() => getStored("re.propertyType", "Всі"));
  const [onlyEOselya, setOnlyEOselya] = useState(
    () => getStored("re.onlyEOselya", "false") === "true"
  );
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(
    () => getStored("re.showFavoritesOnly", "false") === "true"
  );
  const [minPrice, setMinPrice] = useState(() => getStored("re.minPrice", ""));
  const [maxPrice, setMaxPrice] = useState(() => getStored("re.maxPrice", ""));
  const [minRooms, setMinRooms] = useState(() => getStored("re.minRooms", ""));
  const [maxRooms, setMaxRooms] = useState(() => getStored("re.maxRooms", ""));
  const [minArea, setMinArea] = useState(() => getStored("re.minArea", ""));
  const [maxArea, setMaxArea] = useState(() => getStored("re.maxArea", ""));
  const [sortBy, setSortBy] = useState(() => getStored("re.sortBy", DEFAULT_SORT));
  const [keywordDraft, setKeywordDraft] = useState(() => getStored(KEYWORD_SEARCH_KEY, ""));
  const [keywordSearch, setKeywordSearch] = useState(() => getStored(KEYWORD_SEARCH_KEY, ""));
  const [savedSearches, setSavedSearches] = useState(() =>
    safeParseJSON(getStored(SAVED_SEARCHES_KEY, "[]"), [])
  );
  const [favoriteIds, setFavoriteIds] = useState(() => {
    try {
      const raw = getStored("re.favoriteIds", "[]");
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });
  const [authToken, setAuthToken] = useState(() => getStored("uaDim.authToken", ""));
  const [currentUser, setCurrentUser] = useState(() => getStoredJSON("uaDim.currentUser", null));
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({ name: "", email: "", password: "", accountType: "owner" });
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authSuccess, setAuthSuccess] = useState("");
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotLoading, setForgotLoading] = useState(false);
  const [forgotDone, setForgotDone] = useState(false);
  const [forgotError, setForgotError] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [resetPasswordConfirmation, setResetPasswordConfirmation] = useState("");
  const [resetLoading, setResetLoading] = useState(false);
  const [resetError, setResetError] = useState("");
  const [resetDone, setResetDone] = useState(false);
  const resetTokenRef = React.useRef(null);
  const [accountTypeSwitching, setAccountTypeSwitching] = useState(false);
  const [planLimitPrompt, setPlanLimitPrompt] = useState(null);
  const [showCreateListingModal, setShowCreateListingModal] = useState(false);
  const [showEOselyaCalculator, setShowEOselyaCalculator] = useState(false);
  const [eOselyaCalcPrice, setEOselyaCalcPrice] = useState("");
  const [editingListingId, setEditingListingId] = useState(null);
  const [listingForm, setListingForm] = useState(() => createInitialListingForm());
  const [listingSubmitting, setListingSubmitting] = useState(false);
  const [listingMessage, setListingMessage] = useState("");
  const [myListings, setMyListings] = useState([]);
  const [myListingsLoading, setMyListingsLoading] = useState(false);
  const [myListingsFilter, setMyListingsFilter] = useState("all");
  const [inquiries, setInquiries] = useState([]);
  const [inquiriesLoading, setInquiriesLoading] = useState(false);
  const [inquiryMessage, setInquiryMessage] = useState("");
  const [accountSyncMessage, setAccountSyncMessage] = useState("");
  const [selectedListingFiles, setSelectedListingFiles] = useState([]);
  const [selectedListingFilePreviews, setSelectedListingFilePreviews] = useState([]);
  const [selectedListingVideoFiles, setSelectedListingVideoFiles] = useState([]);
  const [selectedListingVideoPreviews, setSelectedListingVideoPreviews] = useState([]);
  const [mediaUploadStatus, setMediaUploadStatus] = useState("");
  const [deleteCandidate, setDeleteCandidate] = useState(null);
  const [publishSuccess, setPublishSuccess] = useState(null);
  const [liveCatalogListings, setLiveCatalogListings] = useState([]);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogLoadingMore, setCatalogLoadingMore] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [catalogTotal, setCatalogTotal] = useState(0);
  const [catalogHasMore, setCatalogHasMore] = useState(false);
  const [catalogCities, setCatalogCities] = useState([]);
  const catalogRequestRef = useRef(0);
  const [trustListing, setTrustListing] = useState(null);
  const [pwaInstallPrompt, setPwaInstallPrompt] = useState(null);
  const [pwaInstallDismissed, setPwaInstallDismissed] = useState(() => hasActivePwaDismissal());
  const [pwaHiddenForSession, setPwaHiddenForSession] = useState(
    () => typeof window !== "undefined" && window.sessionStorage.getItem(PWA_SESSION_HIDDEN_KEY) === "true"
  );
  const [pwaOfferEligible, setPwaOfferEligible] = useState(false);
  const [pwaInstalled, setPwaInstalled] = useState(
    () => getStored(PWA_INSTALLED_KEY, "false") === "true" || isPwaRunningStandalone()
  );
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [resultsView, setResultsView] = useState(() =>
    getStored(RESULTS_VIEW_MODE_KEY, "list") === "map" ? "map" : "list"
  );
  const isIosSafari = useMemo(() => {
    if (typeof window === "undefined") return false;
    const ua = window.navigator.userAgent;
    const isIos = /iphone|ipad|ipod/i.test(ua);
    const isSafari = /safari/i.test(ua) && !/chrome|crios|fxios/i.test(ua);
    const isStandalone = window.navigator.standalone === true;
    return isIos && isSafari && !isStandalone;
  }, []);
  const isMobileDevice = useMemo(() => {
    if (typeof window === "undefined") return false;
    const ua = window.navigator.userAgent || "";
    return /android|iphone|ipad|ipod|mobile/i.test(ua);
  }, []);
  const canPromptPwaInstall = Boolean(pwaInstallPrompt && !isIosSafari);
  const closeTrustDialog = () => setTrustListing(null);
  const openTrustDialog = (property) => setTrustListing(property);
  const trustDialog = trustListing ? (
    <TrustDialog property={trustListing} authToken={authToken} onClose={closeTrustDialog} />
  ) : null;

  const closeMobileFilters = (restoreFocus = true) => {
    setShowMobileFilters(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => mobileFiltersTriggerRef.current?.focus());
    }
  };

  const closeEOselyaCalculator = () => {
    setShowEOselyaCalculator(false);
    window.requestAnimationFrame(() => mobileFiltersTriggerRef.current?.focus());
  };

  useEffect(() => {
    window.localStorage.setItem(RESULTS_VIEW_MODE_KEY, resultsView);
  }, [resultsView]);

  useEffect(() => {
    if (!showMobileFilters) return undefined;

    const previousOverflow = document.body.style.overflow;
    const desktopMedia = window.matchMedia("(min-width: 1024px)");
    document.body.style.overflow = "hidden";
    mobileFiltersCloseRef.current?.focus();

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMobileFilters();
        return;
      }
      if (event.key !== "Tab" || !mobileFiltersDrawerRef.current) return;

      const focusable = [
        ...mobileFiltersDrawerRef.current.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
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
    const handleDesktop = (event) => {
      if (event.matches) closeMobileFilters(false);
    };

    window.addEventListener("keydown", handleKeyDown);
    desktopMedia.addEventListener?.("change", handleDesktop);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
      desktopMedia.removeEventListener?.("change", handleDesktop);
    };
  }, [showMobileFilters]);

  const catalogProperties = useMemo(() => {
    if (catalogLoaded) return liveCatalogListings;
    if (allowMockCatalogFallback() && !catalogError) return MOCK_PROPERTIES;
    return [];
  }, [catalogError, catalogLoaded, liveCatalogListings]);

  const cities = useMemo(
    () => [
      "Всі",
      ...Array.from(
        new Set([...catalogCities, ...catalogProperties.map((property) => property.city)].filter(Boolean))
      ).sort((left, right) => left.localeCompare(right, "uk")),
    ],
    [catalogCities, catalogProperties]
  );
  const activeMyListingsCount = useMemo(
    () => myListings.filter((item) => item.status === "published" && item.listing_status === "active").length,
    [myListings]
  );
  const myListingPhotoCount = useMemo(
    () => myListings.reduce(
      (total, item) => total + Number(item.image_count ?? (Array.isArray(item.images) ? item.images.filter(Boolean).length : 0)),
      0
    ),
    [myListings]
  );
  const myListingCounts = useMemo(
    () => ({
      all: myListings.length,
      active: activeMyListingsCount,
      review: myListings.filter((item) =>
        ["pending_review", "in_review", "changes_requested", "rejected"].includes(item.moderation_status)
      ).length,
      draft: myListings.filter((item) => item.status === "draft").length,
      archived: myListings.filter(
        (item) => item.status === "archived" || ["sold", "removed"].includes(item.listing_status)
      ).length,
    }),
    [activeMyListingsCount, myListings]
  );
  const visibleMyListings = useMemo(() => {
    if (myListingsFilter === "active") {
      return myListings.filter((item) => item.status === "published" && item.listing_status === "active");
    }
    if (myListingsFilter === "review") {
      return myListings.filter((item) =>
        ["pending_review", "in_review", "changes_requested", "rejected"].includes(item.moderation_status)
      );
    }
    if (myListingsFilter === "draft") {
      return myListings.filter((item) => item.status === "draft");
    }
    if (myListingsFilter === "archived") {
      return myListings.filter((item) => item.status === "archived" || ["sold", "removed"].includes(item.listing_status));
    }
    return myListings;
  }, [myListings, myListingsFilter]);
  const isRealtorCabinet = accountTypeOf(currentUser) === "realtor";
  const isDeveloperCabinet = accountTypeOf(currentUser) === "developer";
  const planUsage = currentUser?.usage || null;
  const planName =
    currentUser?.plan?.name ||
    (isDeveloperCabinet ? "Забудовник Базовий" : isRealtorCabinet ? "Ріелтор Free" : "Базовий");
  const planIsFree =
    !currentUser?.plan_id ||
    currentUser.plan_id === "free" ||
    currentUser.plan_id === "realtor_free" ||
    currentUser.plan_id === "developer_free";
  const planQuota = formatPlanQuota(planUsage);
  const planLimitReached = planUsage ? planUsage.listings_remaining === 0 : false;
  const cabinet = {
    badge: isDeveloperCabinet ? "Забудовник" : isRealtorCabinet ? "Ріелтор" : "Власник",
  };

  const openPlansModal = (audience) => {
    const target = audience || (isDeveloperCabinet ? "developer" : isRealtorCabinet ? "realtor" : "owner");
    if (window.uaPremium?.open) {
      window.uaPremium.open(target);
    } else {
      window.location.href = "premium.html";
    }
  };

  const switchAccountType = async () => {
    if (!authToken || accountTypeSwitching) return;
    const nextType = isDeveloperCabinet ? "owner" : isRealtorCabinet ? "developer" : "realtor";
    setAccountTypeSwitching(true);
    setAuthError("");
    setAuthSuccess("");
    try {
      const response = await fetch(getApiUrl("/auth/me"), {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
        body: JSON.stringify({ accountType: nextType }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Не вдалося змінити тип кабінету");
      setCurrentUser(result.user || null);
      setAuthSuccess(
        nextType === "realtor"
          ? "Увімкнено кабінет ріелтора"
          : nextType === "developer"
            ? "Увімкнено кабінет забудовника"
            : "Увімкнено кабінет власника"
      );
    } catch (error) {
      setAuthError(error.message || "Не вдалося змінити тип кабінету");
    } finally {
      setAccountTypeSwitching(false);
    }
  };


  useEffect(() => {
    setSortBy((prev) => resolveSortByForEOselya(prev, onlyEOselya));
  }, [onlyEOselya]);

  useEffect(() => {
    setKeywordDraft(keywordSearch);
    window.localStorage.setItem(KEYWORD_SEARCH_KEY, keywordSearch);
  }, [keywordSearch]);

  const searchFilters = useMemo(
    () => ({
      cityFilter,
      propertyType: propertyTypeFilter,
      onlyEOselya,
      minPrice,
      maxPrice,
      minRooms,
      maxRooms,
      minArea,
      maxArea,
      sortBy,
      keywordSearch,
    }),
    [cityFilter, propertyTypeFilter, onlyEOselya, minPrice, maxPrice, minRooms, maxRooms, minArea, maxArea, sortBy, keywordSearch]
  );

  const loadCatalogListings = async (fresh = false, append = false) => {
    const requestId = ++catalogRequestRef.current;
    if (append) {
      setCatalogLoadingMore(true);
    } else {
      setCatalogLoading(true);
    }
    setCatalogError("");
    try {
      const params = new URLSearchParams({
        status: "published",
        limit: String(CATALOG_PAGE_SIZE),
        offset: String(append ? liveCatalogListings.length : 0),
        sort: sortBy || DEFAULT_SORT,
      });
      if (!append) params.set("includeFacets", "1");
      if (cityFilter !== "Всі") params.set("city", cityFilter);
      if (propertyTypeFilter !== "Всі") params.set("type", propertyTypeFilter);
      if (onlyEOselya) params.set("eOselya", "1");
      if (minPrice !== "") params.set("minPrice", minPrice);
      if (maxPrice !== "") params.set("maxPrice", maxPrice);
      if (minRooms !== "") params.set("minRooms", minRooms);
      if (maxRooms !== "") params.set("maxRooms", maxRooms);
      if (minArea !== "") params.set("minArea", minArea);
      if (maxArea !== "") params.set("maxArea", maxArea);
      if (keywordSearch.trim()) params.set("search", keywordSearch.trim());
      if (showFavoritesOnly) {
        if (!favoriteIds.length) {
          if (requestId !== catalogRequestRef.current) return;
          setLiveCatalogListings([]);
          setCatalogLoaded(true);
          setCatalogTotal(0);
          setCatalogHasMore(false);
          return;
        }
        params.set("ids", favoriteIds.join(","));
      }

      const response = await fetch(getApiUrl(`/listings?${params.toString()}`), {
        cache: fresh ? "no-store" : "default",
      });
      if (!response.ok) throw new Error("Не вдалося завантажити оголошення");
      const data = await response.json();
      if (requestId !== catalogRequestRef.current) return;
      const rows = Array.isArray(data.listings) ? data.listings : [];
      const mapped = rows.map(mapListingToProperty);
      setLiveCatalogListings((current) => {
        if (!append) return mapped;
        const knownIds = new Set(current.map((property) => property.id));
        return [...current, ...mapped.filter((property) => !knownIds.has(property.id))];
      });
      setCatalogLoaded(true);
      setCatalogTotal(Number(data.total) || 0);
      setCatalogHasMore(Boolean(data.has_more));
      if (Array.isArray(data.facets?.cities)) setCatalogCities(data.facets.cities);
    } catch (error) {
      if (requestId !== catalogRequestRef.current) return;
      setCatalogError(error.message || "Не вдалося завантажити оголошення");
      if (!append) {
        setLiveCatalogListings([]);
        setCatalogLoaded(false);
        setCatalogTotal(0);
        setCatalogHasMore(false);
      }
    } finally {
      if (requestId === catalogRequestRef.current) {
        setCatalogLoading(false);
        setCatalogLoadingMore(false);
        window.dispatchEvent(new Event("uah:catalog-settled"));
      }
    }
  };

  const mergeListingIntoCatalog = (listing) => {
    if (!listing?.id) return;
    const mappedListing = mapListingToProperty(listing);
    setLiveCatalogListings((current) => {
      const next = current.filter((item) => item.id !== mappedListing.id);
      return [mappedListing, ...next];
    });
  };

  useEffect(() => {
    if (sellerCabinetMode) {
      setCatalogLoading(false);
      return;
    }
    const timeout = window.setTimeout(() => loadCatalogListings(), 250);
    return () => window.clearTimeout(timeout);
  }, [
    sellerCabinetMode,
    cityFilter,
    propertyTypeFilter,
    onlyEOselya,
    minPrice,
    maxPrice,
    minRooms,
    maxRooms,
    minArea,
    maxArea,
    sortBy,
    keywordSearch,
    showFavoritesOnly,
    showFavoritesOnly ? favoriteIds.join(",") : "",
  ]);

  useEffect(() => {
    const handleInstallPrompt = (e) => {
      e.preventDefault();
      window.__UA_DEFERRED_INSTALL_PROMPT__ = null;
      if (!pwaInstalled) setPwaInstallPrompt(e);
    };
    const handleInstalled = () => {
      setPwaInstalled(true);
      setPwaInstallPrompt(null);
      setPwaHiddenForSession(true);
      window.localStorage.setItem(PWA_INSTALLED_KEY, "true");
      window.sessionStorage.setItem(PWA_SESSION_HIDDEN_KEY, "true");
    };
    const deferredInstallPrompt = window.__UA_DEFERRED_INSTALL_PROMPT__;
    if (deferredInstallPrompt) {
      window.__UA_DEFERRED_INSTALL_PROMPT__ = null;
      if (!pwaInstalled) setPwaInstallPrompt(deferredInstallPrompt);
    }
    window.addEventListener("beforeinstallprompt", handleInstallPrompt);
    window.addEventListener("appinstalled", handleInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", handleInstallPrompt);
      window.removeEventListener("appinstalled", handleInstalled);
    };
  }, [pwaInstalled]);

  useEffect(() => {
    const markOfferEligible = () => setPwaOfferEligible(true);
    const handleScroll = () => {
      if (window.scrollY < Math.max(320, window.innerHeight * 0.55)) return;
      markOfferEligible();
      window.removeEventListener("scroll", handleScroll);
    };
    window.addEventListener("uah:meaningful-interaction", markOfferEligible);
    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => {
      window.removeEventListener("uah:meaningful-interaction", markOfferEligible);
      window.removeEventListener("scroll", handleScroll);
    };
  }, []);

  useEffect(() => {
    window.localStorage.setItem("re.cityFilter", cityFilter);
    window.localStorage.setItem("re.propertyType", propertyTypeFilter);
    window.localStorage.setItem("re.onlyEOselya", String(onlyEOselya));
    window.localStorage.setItem("re.showFavoritesOnly", String(showFavoritesOnly));
    window.localStorage.setItem("re.minPrice", minPrice);
    window.localStorage.setItem("re.maxPrice", maxPrice);
    window.localStorage.setItem("re.minRooms", minRooms);
    window.localStorage.setItem("re.maxRooms", maxRooms);
    window.localStorage.setItem("re.minArea", minArea);
    window.localStorage.setItem("re.maxArea", maxArea);
    window.localStorage.setItem("re.sortBy", sortBy);
    window.localStorage.setItem("re.favoriteIds", JSON.stringify(favoriteIds));
    window.localStorage.setItem(SAVED_SEARCHES_KEY, JSON.stringify(savedSearches.slice(0, MAX_SAVED_SEARCHES)));
  }, [
    cityFilter,
    propertyTypeFilter,
    onlyEOselya,
    showFavoritesOnly,
    minPrice,
    maxPrice,
    minRooms,
    maxRooms,
    minArea,
    maxArea,
    sortBy,
    favoriteIds,
    savedSearches,
  ]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (authToken) {
      window.localStorage.setItem("uaDim.authToken", authToken);
    } else {
      window.localStorage.removeItem("uaDim.authToken");
    }
    if (currentUser) {
      window.localStorage.setItem("uaDim.currentUser", JSON.stringify(currentUser));
    } else {
      window.localStorage.removeItem("uaDim.currentUser");
    }
  }, [authToken, currentUser]);

  useEffect(() => {
    const authCta = document.getElementById("header-auth-cta");
    const brandLink = document.getElementById("header-brand-link");
    if (brandLink) brandLink.setAttribute("href", getCatalogHref());
    if (!authCta) return undefined;

    const mobileLabel = authCta.querySelector("[data-header-auth-mobile]");
    const desktopLabel = authCta.querySelector("[data-header-auth-desktop]");
    if (sellerCabinetMode) {
      if (mobileLabel) mobileLabel.textContent = "Каталог";
      if (desktopLabel) desktopLabel.textContent = "До каталогу";
      authCta.setAttribute("href", getCatalogHref());
      authCta.setAttribute("aria-label", "Повернутися до каталогу житла");
      return undefined;
    }

    const accessibleLabel = currentUser ? "Відкрити кабінет продавця" : "Увійти або зареєструватися";

    if (mobileLabel) mobileLabel.textContent = currentUser ? "Кабінет" : "Увійти";
    if (desktopLabel) desktopLabel.textContent = currentUser ? "Кабінет продавця" : "Увійти / Зареєструватися";
    authCta.setAttribute("href", getSellerCabinetHref());
    authCta.setAttribute("aria-label", accessibleLabel);
    return undefined;
  }, [currentUser, sellerCabinetMode]);

  // URL fragments stay client-side, keeping reset tokens out of server and CDN logs.
  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const token = params.get("reset_token");
    if (!token) return;
    if (!sellerCabinetMode) {
      window.location.replace(`${getSellerCabinetHref()}${window.location.hash}`);
      return;
    }
    resetTokenRef.current = token;
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}#auth`
    );
    setAuthMode("reset");
    setResetPassword("");
    setResetPasswordConfirmation("");
    setResetError("");
    setResetDone(false);
    const authSection = document.getElementById("auth");
    if (authSection) {
      window.requestAnimationFrame(() => {
        authSection.scrollIntoView({ behavior: getPreferredScrollBehavior(), block: "start" });
        window.requestAnimationFrame(() => {
          document.getElementById("auth-reset-password")?.focus({ preventScroll: true });
        });
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sellerCabinetMode]);

  const loadMyListings = async () => {
    if (!authToken) {
      setMyListings([]);
      return;
    }
    setMyListingsLoading(true);
    try {
      const response = await fetch(getApiUrl("/listings?mine=1&status=all&limit=100&sort=newest"), {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) throw new Error("Не вдалося завантажити оголошення");
      const data = await response.json();
      const rows = Array.isArray(data.listings) ? data.listings : [];
      setMyListings(rows);
    } catch (error) {
      setListingMessage(error.message || "Не вдалося завантажити оголошення");
    } finally {
      setMyListingsLoading(false);
    }
  };

  const loadInquiries = async () => {
    if (!authToken) {
      setInquiries([]);
      return;
    }
    setInquiriesLoading(true);
    try {
      const response = await fetch(getApiUrl("/inquiries"), {
        headers: { Authorization: ["Bearer", authToken].join(" ") },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не вдалося завантажити заявки");
      setInquiries(Array.isArray(data.inquiries) ? data.inquiries : []);
    } catch (error) {
      setInquiryMessage(error.message || "Не вдалося завантажити заявки");
    } finally {
      setInquiriesLoading(false);
    }
  };

  const syncAccountData = async () => {
    if (!authToken) return;
    setAccountSyncMessage("Синхронізуємо обране та пошуки…");
    const authHeaders = { Authorization: ["Bearer", authToken].join(" ") };
    try {
      const localFavoriteIds = favoriteIds.filter((id) => Number.isInteger(Number(id)));
      const localSearches = savedSearches.filter((entry) => !entry.serverId).slice(0, MAX_SAVED_SEARCHES);

      const favoriteSyncResponse = await fetch(getApiUrl("/favorites/sync"), {
        method: "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ listing_ids: localFavoriteIds }),
      });
      const favoriteSyncData = await favoriteSyncResponse.json();
      if (!favoriteSyncResponse.ok) {
        throw new Error(favoriteSyncData.error || "Не вдалося синхронізувати обране");
      }

      for (const entry of localSearches) {
        const response = await fetch(getApiUrl("/alerts"), {
          method: "POST",
          headers: { ...authHeaders, "Content-Type": "application/json" },
          body: JSON.stringify(searchFiltersToAlertPayload(entry.name, entry.filters || {})),
        });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || "Не вдалося синхронізувати збережені пошуки");
        }
      }

      const alertsResponse = await fetch(getApiUrl("/alerts"), { headers: authHeaders });
      const alertsData = await alertsResponse.json();
      if (!alertsResponse.ok) throw new Error(alertsData.error || "Не вдалося завантажити пошуки");

      setFavoriteIds(Array.isArray(favoriteSyncData.listing_ids) ? favoriteSyncData.listing_ids : []);
      setSavedSearches(
        (Array.isArray(alertsData.alerts) ? alertsData.alerts : [])
          .map(alertToSavedSearch)
          .slice(0, MAX_SAVED_SEARCHES)
      );
      setAccountSyncMessage("Обране, пошуки та email-сповіщення синхронізовано.");
    } catch (error) {
      setAccountSyncMessage(error.message || "Не вдалося синхронізувати дані акаунта");
    }
  };

  const updateInquiry = async (inquiry, status) => {
    if (!authToken) return;
    let responseMessage = "";
    if (status === "responded") {
      responseMessage = window.prompt("Коротка відповідь покупцю")?.trim() || "";
      if (!responseMessage) return;
    }
    setInquiryMessage("");
    try {
      const response = await fetch(getApiUrl(`/inquiries/${inquiry.id}`), {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: ["Bearer", authToken].join(" "),
        },
        body: JSON.stringify({ status, response_message: responseMessage }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не вдалося оновити заявку");
      setInquiries((current) =>
        current.map((item) =>
          item.id === inquiry.id
            ? {
                ...item,
                status: data.status,
                response_message: responseMessage || item.response_message,
                responded_at: data.responded_at || item.responded_at,
              }
            : item
        )
      );
      setInquiryMessage(status === "responded" ? "Відповідь збережено." : "Статус заявки оновлено.");
    } catch (error) {
      setInquiryMessage(error.message || "Не вдалося оновити заявку");
    }
  };

  const refreshProfile = async () => {
    if (!authToken) return;
    try {
      const response = await fetch(getApiUrl("/auth/me"), {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) return;
      const data = await response.json();
      if (data.user) setCurrentUser(data.user);
    } catch (_error) {
      // Профіль лишається з локального кешу — не блокуємо кабінет.
    }
  };

  useEffect(() => {
    if (!authToken) {
      setMyListings([]);
      setInquiries([]);
      return;
    }
    loadMyListings();
    loadInquiries();
    syncAccountData();
    refreshProfile();
  }, [authToken, currentUser?.id]);

  const filteredProperties = useMemo(
    () =>
      catalogLoaded
        ? catalogProperties
        : filterAndSortProperties(catalogProperties, searchFilters),
    [catalogLoaded, catalogProperties, searchFilters]
  );
  const favoriteProperties = useMemo(
    () => catalogProperties.filter((property) => favoriteIds.includes(property.id)),
    [catalogProperties, favoriteIds]
  );
  const compareProperties = useMemo(() => favoriteProperties.slice(0, 3), [favoriteProperties]);
  const bestValueId = useMemo(() => {
    if (!compareProperties.length) return null;
    return compareProperties.reduce((best, item) => {
      if (!best) return item.id;
      const bestItem = compareProperties.find((candidate) => candidate.id === best);
      const bestScore = Number(bestItem?.price || 0) / Math.max(Number(bestItem?.area || 1), 1);
      const currentScore = Number(item.price || 0) / Math.max(Number(item.area || 1), 1);
      return currentScore < bestScore ? item.id : best;
    }, null);
  }, [compareProperties]);
  const compareSummary = useMemo(() => {
    if (!compareProperties.length) {
      return "Додайте кілька обраних об'єктів, щоб порівняти їх тут.";
    }
    return `Порівнюємо ${compareProperties.length} обраних об'єктів. Кращий value позначено окремо.`;
  }, [compareProperties]);
  const visibleProperties = useMemo(
    () =>
      catalogLoaded || !showFavoritesOnly
        ? filteredProperties
        : filteredProperties.filter((property) => favoriteIds.includes(property.id)),
    [catalogLoaded, filteredProperties, favoriteIds, showFavoritesOnly]
  );
  const favoriteStats = useMemo(() => {
    if (!favoriteProperties.length) return { count: 0, avgPrice: 0, verifiedCount: 0 };
    const totalPrice = favoriteProperties.reduce((sum, item) => sum + item.price, 0);
    return {
      count: favoriteProperties.length,
      avgPrice: Math.round(totalPrice / favoriteProperties.length),
      verifiedCount: favoriteProperties.filter((item) => item.eOselya).length,
    };
  }, [favoriteProperties]);
  const searchSummary = useMemo(
    () => describeSearchState(searchFilters, keywordSearch),
    [searchFilters, keywordSearch]
  );
  const smartSearchMode =
    typeof window !== "undefined" && window.location.pathname.endsWith(SMART_SEARCH_PATH);
  const eOselyaCalcPresets = [500000, 1000000, 2500000, 5000000];
  const eOselyaCalcValue = useMemo(() => {
    const price = Number(String(eOselyaCalcPrice).replace(/[^\d.]/g, ""));
    if (!Number.isFinite(price) || price <= 0) return null;
    return {
      threePercent: price * 0.03,
      sevenPercent: price * 0.07,
    };
  }, [eOselyaCalcPrice]);
  const activatePanel = (panelId) => {
    if (typeof document === "undefined") return;
    const targetId = panelId === "profile" ? "auth" : panelId;
    const target = document.getElementById(targetId);
    if (target) {
      target.scrollIntoView({ behavior: getPreferredScrollBehavior(), block: "start" });
    }
  };
  const openSellerCabinet = (focusMyListings = false) => {
    if (typeof window === "undefined") return;
    if (!sellerCabinetMode) {
      window.location.assign(getSellerCabinetHref());
      return;
    }
    const cabinet = document.getElementById("auth");
    if (!cabinet) return;
    const destination = focusMyListings ? document.getElementById("my-listings") : cabinet;
    if (!destination) return;
    const destinationHash = focusMyListings ? "my-listings" : "auth";
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${destinationHash}`);
    window.requestAnimationFrame(() => {
      destination.scrollIntoView({ behavior: getPreferredScrollBehavior(), block: "start" });
      window.requestAnimationFrame(() => {
        destination.focus({ preventScroll: true });
      });
    });
  };
  const activeFilters = useMemo(() => {
    const items = [];
    if (cityFilter !== "Всі") items.push({ key: "cityFilter", label: `Місто: ${cityFilter}` });
    if (propertyTypeFilter !== "Всі") {
      const selectedType = PROPERTY_TYPE_OPTIONS.find((option) => option.value === propertyTypeFilter);
      items.push({ key: "propertyType", label: `Тип: ${selectedType?.label || propertyTypeFilter}` });
    }
    if (onlyEOselya) items.push({ key: "onlyEOselya", label: "єОселя" });
    if (minPrice || maxPrice) {
      items.push({ key: "price", label: `Ціна: $${minPrice || "0"}-${maxPrice || "∞"}` });
    }
    if (minRooms || maxRooms) {
      items.push({ key: "rooms", label: `Кімнати: ${minRooms || "1"}-${maxRooms || "∞"}` });
    }
    if (minArea || maxArea) {
      items.push({ key: "area", label: `Площа: ${minArea || "0"}-${maxArea || "∞"} м²` });
    }
    if (keywordSearch.trim()) items.push({ key: "keywordSearch", label: `Пошук: "${keywordSearch.trim()}"` });
    return items;
  }, [cityFilter, propertyTypeFilter, onlyEOselya, minPrice, maxPrice, minRooms, maxRooms, minArea, maxArea, keywordSearch]);

  const toggleFavorite = async (property) => {
    const wasFavorite = favoriteIds.includes(property.id);
    setFavoriteIds((current) =>
      wasFavorite ? current.filter((id) => id !== property.id) : [...current, property.id]
    );
    if (!authToken) return;
    try {
      const response = await fetch(getApiUrl(`/favorites/${property.id}`), {
        method: wasFavorite ? "DELETE" : "PUT",
        headers: { Authorization: ["Bearer", authToken].join(" ") },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не вдалося оновити обране");
      setAccountSyncMessage("Обране синхронізовано з акаунтом.");
    } catch (error) {
      setFavoriteIds((current) =>
        wasFavorite
          ? current.includes(property.id) ? current : [...current, property.id]
          : current.filter((id) => id !== property.id)
      );
      setAccountSyncMessage(error.message || "Не вдалося оновити обране");
    }
  };

  const resetFilters = () => {
    setCityFilter("Всі");
    setPropertyTypeFilter("Всі");
    setOnlyEOselya(false);
    setShowFavoritesOnly(false);
    setMinPrice("");
    setMaxPrice("");
    setMinRooms("");
    setMaxRooms("");
    setMinArea("");
    setMaxArea("");
    setSortBy(DEFAULT_SORT);
  };

  const oneClickChips = useMemo(
    () => [
      { label: "Київ", action: () => setCityFilter("Київ") },
      { label: "Львів", action: () => setCityFilter("Львів") },
      { label: "єОселя", action: () => setOnlyEOselya((current) => !current) },
      { label: "1-2 кімн.", action: () => { setMinRooms("1"); setMaxRooms("2"); } },
      { label: "до $100k", action: () => { setMinPrice(""); setMaxPrice("100000"); } },
      { label: "35+ м²", action: () => { setMinArea("35"); setMaxArea(""); } },
      { label: "Релевантні", action: () => setSortBy("relevance") },
      { label: "Скинути все", action: resetFilters },
    ],
    [resetFilters]
  );

  const clearSavedFilters = () => {
    STORAGE_KEYS.forEach((key) => window.localStorage.removeItem(key));
    window.localStorage.removeItem("re.showFavoritesOnly");
    window.localStorage.removeItem("re.favoriteIds");
    window.localStorage.removeItem(SAVED_SEARCHES_KEY);
    window.localStorage.removeItem(KEYWORD_SEARCH_KEY);
    resetFilters();
    setFavoriteIds([]);
    setKeywordDraft("");
    setKeywordSearch("");
    setSavedSearches([]);
  };

  const applyScenario = (scenario) => {
    const { filters } = scenario;
    if ("cityFilter" in filters) setCityFilter(filters.cityFilter);
    if ("propertyTypeFilter" in filters) setPropertyTypeFilter(filters.propertyTypeFilter);
    if ("onlyEOselya" in filters) setOnlyEOselya(filters.onlyEOselya);
    if ("minPrice" in filters) setMinPrice(filters.minPrice);
    if ("maxPrice" in filters) setMaxPrice(filters.maxPrice);
    if ("minRooms" in filters) setMinRooms(filters.minRooms);
    if ("maxRooms" in filters) setMaxRooms(filters.maxRooms);
    if ("minArea" in filters) setMinArea(filters.minArea);
    if ("maxArea" in filters) setMaxArea(filters.maxArea);
    if ("sortBy" in filters) setSortBy(filters.sortBy);
    if ("keywordSearch" in filters) {
      setKeywordDraft(filters.keywordSearch);
      setKeywordSearch(filters.keywordSearch);
    }
    activatePanel("search");
  };

  const saveCurrentSearch = async () => {
    const defaultName = `${cityFilter || "Всі"} · ${onlyEOselya ? "єОселя" : "всі"} · ${
      new Date().toLocaleDateString("uk-UA")
    }`;
    const name = (window.prompt("Назва для збереженого пошуку:", defaultName) || "").trim();
    if (!name) return;
    const entry = {
      id: `search_${Date.now()}`,
      name,
      filters: { ...searchFilters },
      isActive: Boolean(authToken),
      createdAt: Date.now(),
    };
    setSavedSearches((current) => [entry, ...current].slice(0, MAX_SAVED_SEARCHES));
    if (!authToken) {
      setAccountSyncMessage("Пошук збережено на цьому пристрої. Увійдіть, щоб синхронізувати його.");
      return;
    }
    try {
      const response = await fetch(getApiUrl("/alerts"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: ["Bearer", authToken].join(" "),
        },
        body: JSON.stringify(searchFiltersToAlertPayload(name, searchFilters)),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не вдалося зберегти пошук");
      setSavedSearches((current) =>
        current
          .filter((item) => item.id === entry.id || item.serverId !== data.id)
          .map((item) =>
            item.id === entry.id
              ? { ...item, id: `alert_${data.id}`, serverId: data.id, isActive: true }
              : item
          )
      );
      setAccountSyncMessage("Пошук збережено. Email-сповіщення активні.");
    } catch (error) {
      setAccountSyncMessage(error.message || "Пошук збережено лише на цьому пристрої");
    }
  };

  const deleteSavedSearch = async (entry) => {
    const previous = savedSearches;
    setSavedSearches((current) => current.filter((item) => item.id !== entry.id));
    if (!authToken || !entry.serverId) return;
    try {
      const response = await fetch(getApiUrl(`/alerts/${entry.serverId}`), {
        method: "DELETE",
        headers: { Authorization: ["Bearer", authToken].join(" ") },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не вдалося видалити пошук");
      setAccountSyncMessage("Збережений пошук видалено.");
    } catch (error) {
      setSavedSearches(previous);
      setAccountSyncMessage(error.message || "Не вдалося видалити пошук");
    }
  };

  const toggleSavedSearchAlert = async (entry) => {
    if (!authToken || !entry.serverId) {
      setAccountSyncMessage("Увійдіть, щоб керувати сповіщеннями.");
      return;
    }
    const nextActive = !entry.isActive;
    setSavedSearches((current) =>
      current.map((item) => item.id === entry.id ? { ...item, isActive: nextActive } : item)
    );
    try {
      const response = await fetch(getApiUrl(`/alerts/${entry.serverId}`), {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: ["Bearer", authToken].join(" "),
        },
        body: JSON.stringify({ is_active: nextActive }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не вдалося змінити сповіщення");
      setAccountSyncMessage(nextActive ? "Email-сповіщення увімкнено." : "Email-сповіщення призупинено.");
    } catch (error) {
      setSavedSearches((current) =>
        current.map((item) => item.id === entry.id ? { ...item, isActive: entry.isActive } : item)
      );
      setAccountSyncMessage(error.message || "Не вдалося змінити сповіщення");
    }
  };

  const applyKeywordSearch = () => {
    setKeywordSearch(keywordDraft.trim());
  };

  const dismissPwaOffer = () => {
    setPwaInstallDismissed(true);
    setPwaHiddenForSession(true);
    window.localStorage.setItem(PWA_DISMISS_KEY, String(Date.now() + PWA_DISMISS_DURATION_MS));
    window.sessionStorage.setItem(PWA_SESSION_HIDDEN_KEY, "true");
  };

  const hidePwaOfferForSession = () => {
    setPwaHiddenForSession(true);
    window.sessionStorage.setItem(PWA_SESSION_HIDDEN_KEY, "true");
  };

  const clearKeywordSearch = () => {
    setKeywordDraft("");
    setKeywordSearch("");
  };

  const openSavedSearch = (entry) => {
    const next = entry.filters || {};
    if ("cityFilter" in next) setCityFilter(next.cityFilter);
    if ("propertyType" in next) setPropertyTypeFilter(next.propertyType);
    if ("onlyEOselya" in next) setOnlyEOselya(next.onlyEOselya);
    if ("minPrice" in next) setMinPrice(next.minPrice);
    if ("maxPrice" in next) setMaxPrice(next.maxPrice);
    if ("minRooms" in next) setMinRooms(next.minRooms);
    if ("maxRooms" in next) setMaxRooms(next.maxRooms);
    if ("minArea" in next) setMinArea(next.minArea);
    if ("maxArea" in next) setMaxArea(next.maxArea);
    if ("sortBy" in next) setSortBy(next.sortBy);
    if ("keywordSearch" in next) {
      setKeywordDraft(next.keywordSearch || "");
      setKeywordSearch(next.keywordSearch || "");
    }
    activatePanel("search");
  };

  const clearActiveFilter = (key) => {
    if (key === "cityFilter") setCityFilter("Всі");
    if (key === "propertyType") setPropertyTypeFilter("Всі");
    if (key === "onlyEOselya") setOnlyEOselya(false);
    if (key === "price") {
      setMinPrice("");
      setMaxPrice("");
    }
    if (key === "rooms") {
      setMinRooms("");
      setMaxRooms("");
    }
    if (key === "area") {
      setMinArea("");
      setMaxArea("");
    }
    if (key === "keywordSearch") {
      setKeywordDraft("");
      setKeywordSearch("");
    }
  };

  const updateAuthForm = (field, value) => {
    setAuthForm((current) => ({ ...current, [field]: value }));
  };

  const handleAuthSubmit = async (event) => {
    event.preventDefault();
    setAuthLoading(true);
    setAuthError("");
    setAuthSuccess("");
    try {
      const response = await fetch(getApiUrl(authMode === "login" ? "/auth/login" : "/auth/register"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          authMode === "login"
            ? {
                email: authForm.email.trim(),
                password: authForm.password,
              }
            : {
                name: authForm.name.trim(),
                email: authForm.email.trim(),
                password: authForm.password,
                accountType: authForm.accountType,
              }
        ),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || "Не вдалося виконати дію");
      }
      setAuthToken(result.token || "");
      setCurrentUser(result.user || null);
      setAuthSuccess(authMode === "login" ? "Увійшли в профіль" : "Обліковий запис створено");
      setAuthForm({ name: "", email: "", password: "", accountType: authForm.accountType });
    } catch (error) {
      setAuthError(error.message || "Не вдалося виконати дію");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleForgotSubmit = async (event) => {
    event.preventDefault();
    setForgotLoading(true);
    setForgotDone(false);
    setForgotError("");
    try {
      const response = await fetch(getApiUrl("/auth/forgot-password"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: forgotEmail.trim() }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          response.status === 503
            ? "Відновлення пароля тимчасово недоступне. Спробуйте пізніше."
            : result.error || "Не вдалося надіслати запит. Спробуйте ще раз."
        );
      }
      setForgotDone(true);
    } catch (error) {
      setForgotError(error.message || "Не вдалося надіслати запит. Спробуйте ще раз.");
    } finally {
      setForgotLoading(false);
    }
  };

  const handleResetSubmit = async (event) => {
    event.preventDefault();
    if (resetPassword !== resetPasswordConfirmation) {
      setResetError("Паролі не збігаються.");
      return;
    }
    setResetLoading(true);
    setResetError("");
    try {
      const token = resetTokenRef.current;
      const response = await fetch(getApiUrl("/auth/reset-password"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password: resetPassword }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(result.error || "Не вдалося скинути пароль.");
      }
      resetTokenRef.current = null;
      setResetDone(true);
      setResetPassword("");
      setResetPasswordConfirmation("");
    } catch (error) {
      setResetError(error.message || "Не вдалося скинути пароль.");
    } finally {
      setResetLoading(false);
    }
  };

  const logoutProfile = () => {
    setAuthToken("");
    setCurrentUser(null);
    setFavoriteIds([]);
    setSavedSearches([]);
    window.localStorage.removeItem("re.favoriteIds");
    window.localStorage.removeItem(SAVED_SEARCHES_KEY);
    setAuthSuccess("Ви вийшли з профілю");
    setAccountSyncMessage("");
    setMyListings([]);
    setListingMessage("");
    setEditingListingId(null);
    setListingForm(createInitialListingForm());
    setSelectedListingFiles([]);
    setSelectedListingFilePreviews([]);
    setSelectedListingVideoFiles([]);
    setSelectedListingVideoPreviews([]);
    setMediaUploadStatus("");
  };

  const closeListingModal = () => {
    if (listingSubmitting) return;
    setShowCreateListingModal(false);
    setEditingListingId(null);
    setListingForm(createInitialListingForm());
    setSelectedListingFiles([]);
    setSelectedListingFilePreviews([]);
    setSelectedListingVideoFiles([]);
    setSelectedListingVideoPreviews([]);
    setMediaUploadStatus("");
  };

  const openCreateListingModal = () => {
    if (!currentUser) {
      setAuthMode("register");
      setAuthSuccess("Створіть профіль продавця, а потім додайте дані й фото оголошення.");
      activatePanel("profile");
      return;
    }
    setEditingListingId(null);
    const developerDefaults = isDeveloperCabinet
      ? {
          conditionType: "нова будова",
          propertyType: "квартира",
          listingType: "sale",
          description: "Оголошення новобудови від забудовника",
        }
      : {};
    setListingForm(createInitialListingForm(developerDefaults));
    setSelectedListingFiles([]);
    setSelectedListingFilePreviews([]);
    setSelectedListingVideoFiles([]);
    setSelectedListingVideoPreviews([]);
    setMediaUploadStatus("");
    setListingMessage("");
    setShowCreateListingModal(true);
  };

  const openEditListingModal = (listing) => {
    setEditingListingId(listing.id);
    setListingForm(mapListingToForm(listing));
    setSelectedListingFiles([]);
    setSelectedListingFilePreviews([]);
    setSelectedListingVideoFiles([]);
    setSelectedListingVideoPreviews([]);
    setMediaUploadStatus("");
    setListingMessage("");
    setShowCreateListingModal(true);
  };

  const updateListingField = (field, value) => {
    setListingForm((current) => ({ ...current, [field]: value }));
  };

  const updateListingImage = (index, value) => {
    setListingForm((current) => {
      const images = [...current.images];
      images[index] = value;
      return { ...current, images };
    });
  };

  const addListingImageField = () => {
    setListingForm((current) => ({ ...current, images: [...current.images, ""] }));
  };

  const removeListingImageField = (index) => {
    setListingForm((current) => ({
      ...current,
      images: current.images.filter((_, itemIndex) => itemIndex !== index),
    }));
  };

  const handleListingFileSelection = (event, mediaType = "image") => {
    const maxFiles = mediaType === "video" ? 2 : 8;
    const maxBytes = mediaType === "video" ? 100 * 1024 * 1024 : 10 * 1024 * 1024;
    const selectedFiles = Array.from(event.target.files || []);
    const acceptedFiles = selectedFiles.filter((file) => {
      const contentType = getFileContentType(file);
      return contentType.startsWith(`${mediaType}/`) && file.size <= maxBytes;
    });
    const rejectedCount = selectedFiles.length - acceptedFiles.length;
    if (mediaType === "video") {
      setSelectedListingVideoFiles((previous) => [...previous, ...acceptedFiles].slice(0, maxFiles));
    } else {
      setSelectedListingFiles((previous) => [...previous, ...acceptedFiles].slice(0, maxFiles));
    }
    setListingMessage(
      rejectedCount
        ? `Пропущено ${rejectedCount} файл(и): перевірте формат і розмір.`
        : ""
    );
    event.target.value = "";
  };

  const removeSelectedListingFile = (index) => {
    setSelectedListingFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const removeSelectedListingVideo = (index) => {
    setSelectedListingVideoFiles((previous) => previous.filter((_, itemIndex) => itemIndex !== index));
  };

  const removeExistingListingVideo = (index) => {
    setListingForm((current) => ({
      ...current,
      videos: current.videos.filter((_, itemIndex) => itemIndex !== index),
    }));
  };

  useEffect(() => {
    if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
      setSelectedListingFilePreviews([]);
      return undefined;
    }

    const previews = selectedListingFiles.map((file) => ({
      id: `${file.name}-${file.size}-${file.lastModified}`,
      name: file.name,
      src: URL.createObjectURL(file),
    }));

    setSelectedListingFilePreviews(previews);

    return () => {
      previews.forEach((preview) => URL.revokeObjectURL(preview.src));
    };
  }, [selectedListingFiles]);

  useEffect(() => {
    if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
      setSelectedListingVideoPreviews([]);
      return undefined;
    }

    const previews = selectedListingVideoFiles.map((file) => ({
      id: `${file.name}-${file.size}-${file.lastModified}`,
      name: file.name,
      src: URL.createObjectURL(file),
    }));
    setSelectedListingVideoPreviews(previews);
    return () => previews.forEach((preview) => URL.revokeObjectURL(preview.src));
  }, [selectedListingVideoFiles]);

  const uploadListingFilesToStorage = async (files, mediaType) => {
    if (!files.length) return [];

    const uploadedUrls = [];
    for (const [index, file] of files.entries()) {
        setMediaUploadStatus(
          `Завантаження ${mediaType === "video" ? "відео" : "фото"} ${index + 1} з ${files.length}…`
        );
        const contentType = getFileContentType(file);
        const presignResponse = await fetch(getApiUrl("/media/presigned-url"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${authToken}`,
          },
          body: JSON.stringify({ filename: file.name, contentType, size: file.size }),
        });

        if (!presignResponse.ok) {
          const presignPayload = await presignResponse.json().catch(() => ({}));
          throw new Error(presignPayload.error || "Не вдалося підготувати медіафайл для завантаження");
        }

        const presigned = await presignResponse.json();
        let finalUrl = "";

        if (presigned?.storage === "cloudinary" && presigned?.method === "POST") {
          const formData = new FormData();
          formData.append("file", file);
          formData.append("resource_type", presigned.resourceType || "image");
          if (presigned.publicId) formData.append("public_id", presigned.publicId);
          if (presigned.uploadPreset) formData.append("upload_preset", presigned.uploadPreset);
          if (presigned.apiKey) formData.append("api_key", presigned.apiKey);
          if (presigned.timestamp) formData.append("timestamp", String(presigned.timestamp));
          if (presigned.signature) formData.append("signature", presigned.signature);

          const uploadResponse = await fetch(presigned.uploadUrl, { method: "POST", body: formData });
          if (!uploadResponse.ok) {
            const uploadText = await uploadResponse.text();
            throw new Error(uploadText || "Не вдалося відправити медіафайл у хмарне сховище");
          }

          const uploadResult = await uploadResponse.json().catch(() => ({}));
          finalUrl = uploadResult.secure_url || uploadResult.url || "";
          if (!finalUrl) {
            throw new Error("Сховище не повернуло URL медіафайла");
          }

          const confirmResponse = await fetch(getApiUrl("/media/confirm-upload"), {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${authToken}`,
            },
            body: JSON.stringify({
              url: finalUrl,
              publicId: uploadResult.public_id || presigned.publicId,
              resourceType: presigned.resourceType || mediaType,
            }),
          });

          if (!confirmResponse.ok) {
            const confirmPayload = await confirmResponse.json().catch(() => ({}));
            throw new Error(confirmPayload.error || "Не вдалося підтвердити медіафайл");
          }

          const confirmPayload = await confirmResponse.json().catch(() => ({}));
          finalUrl = confirmPayload.url || finalUrl;
        } else if (presigned?.method === "PUT") {
          const uploadResponse = await fetch(presigned.uploadUrl, {
            method: "PUT",
            headers: presigned.headers || { "Content-Type": contentType },
            body: file,
          });

          if (!uploadResponse.ok) {
            const uploadText = await uploadResponse.text();
            throw new Error(uploadText || "Не вдалося відправити медіафайл у сховище");
          }

          const confirmResponse = await fetch(getApiUrl("/media/confirm-upload"), {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${authToken}`,
            },
            body: JSON.stringify({
              key: presigned.key,
              etag: uploadResponse.headers.get("etag") || "",
              resourceType: mediaType,
            }),
          });

          if (!confirmResponse.ok) {
            const confirmPayload = await confirmResponse.json().catch(() => ({}));
            throw new Error(confirmPayload.error || "Не вдалося підтвердити медіафайл");
          }

          const confirmPayload = await confirmResponse.json().catch(() => ({}));
          finalUrl = confirmPayload.url || "";
        } else {
          throw new Error("Сховище не підтримує пряме завантаження медіафайлів");
        }

        if (!finalUrl) throw new Error("Сховище не повернуло URL медіафайла");
        uploadedUrls.push(finalUrl);
    }

    return uploadedUrls;
  };

  const handleCreateListing = async (event) => {
    event.preventDefault();
    if (!authToken) {
      setListingMessage("Спочатку увійдіть у профіль");
      return;
    }
    setListingSubmitting(true);
    setListingMessage("");
    const isEditing = Boolean(editingListingId);
    setMediaUploadStatus(
      isEditing ? "Зміни зберігаються…" : "Оголошення завантажується… Не закривайте сторінку."
    );
    try {
      const imageUrls = listingForm.images.filter(Boolean).slice(0, 8);
      const uploadedStorageUrls = selectedListingFiles.length
        ? await uploadListingFilesToStorage(selectedListingFiles, "image")
        : [];
      const videoUrls = listingForm.videos.filter(Boolean).slice(0, 2);
      const uploadedVideoUrls = selectedListingVideoFiles.length
        ? await uploadListingFilesToStorage(selectedListingVideoFiles, "video")
        : [];
      const payload = {
        title: listingForm.title.trim(),
        city: listingForm.city.trim(),
        district: listingForm.district.trim(),
        propertyType: listingForm.propertyType,
        conditionType: listingForm.conditionType,
        listingType: listingForm.listingType,
        price: Number(listingForm.price),
        rooms: Number(listingForm.rooms),
        area: Number(listingForm.area),
        floor: Number(listingForm.floor) || 1,
        totalFloors: Number(listingForm.totalFloors) || 1,
        yearBuilt: listingForm.yearBuilt ? Number(listingForm.yearBuilt) : undefined,
        eOselya: Boolean(listingForm.eOselya),
        description: listingForm.description.trim(),
        listingStatus: "active",
        source: isDeveloperCabinet ? "developer" : isRealtorCabinet ? "agent" : "owner",
        publishNow: true,
        images: [...uploadedStorageUrls, ...imageUrls].slice(0, 8),
        videos: [...uploadedVideoUrls, ...videoUrls].slice(0, 2),
      };

      setMediaUploadStatus(isEditing ? "Оновлюємо оголошення…" : "Надсилаємо оголошення…");
      const response = await fetch(getApiUrl(isEditing ? `/listings/${editingListingId}` : "/listings"), {
        method: isEditing ? "PATCH" : "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (response.status === 402 || result.code === "plan_limit_reached") {
        setShowCreateListingModal(false);
        setPlanLimitPrompt({
          message: result.error || "Ліміт оголошень за вашим тарифом вичерпано.",
          usage: result.usage || null,
          planName: result.plan?.name || planName,
        });
        if (result.usage) {
          setCurrentUser((prev) => (prev ? { ...prev, usage: result.usage } : prev));
        }
        return;
      }
      if (!response.ok) {
        throw new Error(result.error || "Не вдалося створити оголошення");
      }
      if (result.listing?.status === "published") {
        mergeListingIntoCatalog(result.listing);
      }
      setPublishSuccess({
        id: result.listing?.id,
        title: result.listing?.title || payload.title,
        isEditing,
        isPublished: result.listing?.status === "published",
      });
      setMyListingsFilter("all");
      setListingMessage(
        `${
          isEditing
            ? result.listing?.status === "published"
              ? "Оголошення оновлено та залишено опублікованим."
              : "Зміни збережено й надіслано на модерацію."
            : `Оголошення створено${result.listing?.status === "published" ? " і вже опубліковане" : " і надіслане на модерацію"}.`
        }${result.media_cleanup_pending ? " Частину видалених медіафайлів не вдалося очистити зі сховища." : ""}`
      );
      setEditingListingId(null);
      setListingForm(createInitialListingForm());
      setSelectedListingFiles([]);
      setSelectedListingFilePreviews([]);
      setSelectedListingVideoFiles([]);
      setSelectedListingVideoPreviews([]);
      setMediaUploadStatus("");
      setShowCreateListingModal(false);
      await Promise.all([loadMyListings(), loadCatalogListings(true)]);
      openSellerCabinet(true);
    } catch (error) {
      setListingMessage(error.message || "Не вдалося зберегти оголошення");
    } finally {
      setMediaUploadStatus("");
      setListingSubmitting(false);
    }
  };

  const requestDeleteListing = (listing) => {
    if (!listing?.id) return;
    if (showCreateListingModal) closeListingModal();
    setDeleteCandidate(listing);
  };

  const handleDeleteListing = async () => {
    if (!authToken || !deleteCandidate?.id) {
      return;
    }

    setListingSubmitting(true);
    setListingMessage("");
    try {
      const listingId = deleteCandidate.id;
      const response = await fetch(getApiUrl(`/listings/${listingId}`), {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || "Не вдалося видалити оголошення");
      }

      setDeleteCandidate(null);
      setMyListings((current) => current.filter((listing) => listing.id !== listingId));
      setLiveCatalogListings((current) => current.filter((listing) => listing.id !== listingId));
      setPublishSuccess((current) => (current?.id === listingId ? null : current));
      setListingMessage(
        `Оголошення видалено.${
          result.media_cleanup_pending ? " Частину медіафайлів не вдалося очистити зі сховища." : ""
        }`
      );
      await Promise.all([loadMyListings(), loadCatalogListings(true)]);
    } catch (error) {
      setListingMessage(error.message || "Не вдалося видалити оголошення");
    } finally {
      setListingSubmitting(false);
    }
  };

  useAccessibleDialog(
    showEOselyaCalculator,
    closeEOselyaCalculator,
    eOselyaDialogRef,
    eOselyaCloseRef
  );
  useAccessibleDialog(planLimitPrompt !== null, () => setPlanLimitPrompt(null), planDialogRef, planCloseRef);
  useAccessibleDialog(showCreateListingModal, closeListingModal, listingDialogRef, listingCloseRef);
  useAccessibleDialog(deleteCandidate !== null, () => setDeleteCandidate(null), deleteDialogRef, deleteCancelRef);

  useEffect(() => {
    if (smartSearchMode) return undefined;
    const heroInput = document.getElementById("hero-property-search");
    keywordInputRef.current = heroInput;
    const handleHeroSearch = (event) => {
      const query = String(event.detail?.query || "").trim();
      setKeywordDraft(query);
      setKeywordSearch(query);
      window.__UA_PENDING_HERO_SEARCH__ = null;
      window.requestAnimationFrame(() => {
        const results = document.getElementById("results");
        results?.scrollIntoView({ behavior: getPreferredScrollBehavior(), block: "start" });
        results?.focus({ preventScroll: true });
      });
    };
    window.addEventListener("uah:hero-search", handleHeroSearch);
    if (window.__UA_PENDING_HERO_SEARCH__) {
      handleHeroSearch({ detail: window.__UA_PENDING_HERO_SEARCH__ });
    }
    return () => window.removeEventListener("uah:hero-search", handleHeroSearch);
  }, [smartSearchMode]);

  useEffect(() => {
    if (smartSearchMode) return;
    const heroInput = document.getElementById("hero-property-search");
    if (heroInput && document.activeElement !== heroInput && heroInput.value !== keywordDraft) {
      heroInput.value = keywordDraft;
    }
  }, [keywordDraft, smartSearchMode]);

  if (smartSearchMode) {
    return React.createElement(SmartSearchPage, {
      keywordInputRef,
      keywordDraft,
      setKeywordDraft,
      applyKeywordSearch,
      clearKeywordSearch,
      searchSummary,
      oneClickChips,
      activeFilters,
      clearActiveFilter,
      visibleProperties,
      filteredProperties,
      totalProperties: catalogLoaded ? catalogTotal : filteredProperties.length,
      favoriteIds,
      toggleFavorite,
      showFavoritesOnly,
      setShowFavoritesOnly,
      saveCurrentSearch,
      resetFilters,
      onOpenTrust: openTrustDialog,
      trustDialog,
    });
  }

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key !== "/") return;
      const target = event.target;
      if (
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable
      ) {
        return;
      }
      event.preventDefault();
      keywordInputRef.current?.focus();
      keywordInputRef.current?.select?.();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    const handleAddHash = () => {
      if (window.location.hash !== "#add") return;
      if (!sellerCabinetMode) {
        window.location.assign(`${getSellerCabinetHref()}#add`);
        return;
      }
      const anchor = document.getElementById("add");
      if (anchor) {
        const top = anchor.getBoundingClientRect().top + window.scrollY - 96;
        window.scrollTo({ top: Math.max(top, 0), behavior: getPreferredScrollBehavior() });
      }
      if (!currentUser) {
        setAuthMode("register");
        return;
      }
      openCreateListingModal();
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    };

    handleAddHash();
    window.addEventListener("hashchange", handleAddHash);
    return () => window.removeEventListener("hashchange", handleAddHash);
  }, [currentUser, sellerCabinetMode]);

  return (
    <div className="bg-slate-50 text-slate-900">
      {showEOselyaCalculator ? (
       <div
         className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/70 px-4 py-6 backdrop-blur-sm"
         onClick={closeEOselyaCalculator}
       >
         <div
           ref={eOselyaDialogRef}
           role="dialog"
           aria-modal="true"
           aria-labelledby="eoselya-dialog-title"
           aria-describedby="eoselya-dialog-description"
           className="w-full max-w-lg rounded-[28px] border border-slate-200 bg-white p-5 shadow-2xl shadow-slate-950/20"
           onClick={(event) => event.stopPropagation()}
         >
           <div className="flex items-start justify-between gap-3">
             <div>
               <p className="text-[11px] font-black uppercase tracking-[0.28em] text-blue-700">Калькулятор єОселя</p>
               <h2 id="eoselya-dialog-title" className="mt-1 text-2xl font-black text-slate-900">Розрахунок комісії</h2>
             </div>
             <button
               ref={eOselyaCloseRef}
               type="button"
               onClick={closeEOselyaCalculator}
               aria-label="Закрити калькулятор єОселя"
               className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
             >
               ✕ Закрити
             </button>
           </div>

           <div className="mt-4 rounded-2xl border border-blue-100 bg-blue-50 p-4">
             <label htmlFor="eoselya-property-price" className="block text-xs font-black uppercase tracking-wide text-blue-700">Вартість об’єкта, ₴</label>
             <input
               id="eoselya-property-price"
               type="number"
               min="0"
               inputMode="numeric"
               value={eOselyaCalcPrice}
               onChange={(event) => setEOselyaCalcPrice(event.target.value)}
               placeholder="Наприклад, 1250000"
               className="mt-2 w-full rounded-2xl border border-blue-200 bg-white px-4 py-3 text-sm font-semibold text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
             />
             <div className="mt-3 flex flex-wrap gap-2">
               {eOselyaCalcPresets.map((preset) => (
                 <button
                   key={preset}
                   type="button"
                   onClick={() => setEOselyaCalcPrice(String(preset))}
                   className="rounded-full border border-blue-200 bg-white px-3 py-1.5 text-xs font-semibold text-blue-700 transition hover:bg-blue-100"
                 >
                   ₴{preset.toLocaleString("uk-UA")}
                 </button>
               ))}
             </div>
           </div>

           <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
             <p className="text-[11px] font-black uppercase tracking-wide text-slate-500">Формула розрахунку</p>
             <p className="mt-2 text-sm text-slate-600">
               Комісія = вартість об’єкта × 3% або × 7% залежно від тарифу єОселя.
             </p>
             <p className="mt-3 text-sm font-black text-slate-900">
               {eOselyaCalcValue
                 ? `${formatCurrency(eOselyaCalcValue.threePercent)} / ${formatCurrency(eOselyaCalcValue.sevenPercent)}`
                 : "Введіть суму, щоб побачити розрахунок"}
             </p>
           </div>

           <div className="mt-4 grid gap-3 sm:grid-cols-2">
             <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
               <p className="text-[11px] font-black uppercase tracking-wide text-slate-500">3%</p>
               <p className="mt-2 text-2xl font-black text-slate-900">
                 {eOselyaCalcValue ? formatCurrency(eOselyaCalcValue.threePercent) : "—"}
               </p>
               <p className="mt-1 text-sm text-slate-600">Комісія за ставкою 3%</p>
             </div>
             <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
               <p className="text-[11px] font-black uppercase tracking-wide text-slate-500">7%</p>
               <p className="mt-2 text-2xl font-black text-slate-900">
                 {eOselyaCalcValue ? formatCurrency(eOselyaCalcValue.sevenPercent) : "—"}
               </p>
               <p className="mt-1 text-sm text-slate-600">Комісія за ставкою 7%</p>
             </div>
           </div>

           <p id="eoselya-dialog-description" className="mt-4 text-sm text-slate-600">
             Введіть вартість об’єкта, щоб миттєво побачити розмір комісії для єОселя за тарифами 3% або 7%.
           </p>
         </div>
       </div>
      ) : null}

      <section className={`mx-auto px-4 pb-12 ${sellerCabinetMode ? "max-w-6xl pt-8 sm:pt-12" : "max-w-7xl"}`}>
       {sellerCabinetMode ? (
         <div className="mb-6 overflow-hidden rounded-[32px] bg-[radial-gradient(circle_at_top_right,rgba(59,130,246,.35),transparent_38%),linear-gradient(135deg,#0f172a,#1e3a8a)] p-6 text-white shadow-2xl shadow-slate-900/15 sm:p-8">
           <p className="text-xs font-black uppercase tracking-[0.24em] text-blue-200">Простір продавця</p>
           <h1 className="mt-2 max-w-3xl text-3xl font-black leading-tight sm:text-5xl">
             Керуйте оголошеннями без зайвих кроків
           </h1>
           <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-200 sm:text-base">
             Публікуйте житло, додавайте фото та змінюйте дані в одному зрозумілому кабінеті.
           </p>
         </div>
       ) : null}
       {!sellerCabinetMode ? (
       <div className="mb-4 rounded-[24px] border border-blue-200 bg-white p-3 shadow-sm lg:hidden">
         <button
           ref={mobileFiltersTriggerRef}
           type="button"
           onClick={() => setShowMobileFilters(true)}
           aria-controls="search"
           aria-expanded={showMobileFilters}
           className="flex w-full items-center justify-between gap-3 rounded-2xl bg-slate-900 px-4 py-3 text-left text-white transition hover:bg-blue-700"
         >
           <span>
             <span className="block text-sm font-black">Розширені фільтри</span>
             <span className="mt-0.5 block text-xs font-medium text-slate-300">
               {activeFilters.length ? `${activeFilters.length} активних умов` : "Місто, тип, ціна, кімнати й площа"}
             </span>
           </span>
           <span className="shrink-0 rounded-full bg-white/15 px-3 py-1 text-xs font-black">
             {visibleProperties.length}
           </span>
         </button>
       </div>
       ) : null}

       <div className={sellerCabinetMode ? "block" : "grid gap-6 lg:grid-cols-12"}>
          <aside
            id="add"
            className={
              sellerCabinetMode
                ? "mx-auto min-w-0 max-w-5xl"
                : "order-2 min-w-0 space-y-6 self-start lg:order-1 lg:col-span-4 lg:sticky lg:top-24"
            }
          >
            {sellerCabinetMode ? (
            <div
              id="auth"
              tabIndex={-1}
              aria-labelledby="seller-cabinet-title"
              className="scroll-mt-28 rounded-[32px] border border-slate-200 bg-white p-5 shadow-xl shadow-slate-900/5 sm:p-7"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-slate-950 text-sm font-black text-white">
                    UA
                  </span>
                  <div className="min-w-0">
                    <p className="text-xs font-black uppercase tracking-wide text-blue-700">Кабінет продавця</p>
                  <h2 id="seller-cabinet-title" className="mt-1 text-xl font-black text-slate-900">
                      {currentUser ? currentUser.name : "Публікуйте житло самостійно"}
                  </h2>
                  </div>
                </div>
                <span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${currentUser ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-700"}`}>
                  {currentUser ? cabinet.badge : "Потрібен вхід"}
                </span>
              </div>

              <p className="mt-2 text-sm text-slate-600">
                {currentUser
                  ? `${planName}${planQuota ? ` · ${planQuota}` : ""}`
                  : "Увійдіть або створіть профіль, щоб додати фото, опублікувати й редагувати оголошення."}
              </p>

              {authError ? <div id="auth-error" role="alert" className="mt-3 rounded-2xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{authError}</div> : null}
              {authSuccess ? <div id="auth-success" role="status" aria-live="polite" className="mt-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{authSuccess}</div> : null}
              {listingMessage && !showCreateListingModal ? <div id="listing-message" role="status" aria-live="polite" className="mt-3 rounded-2xl border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800">{listingMessage}</div> : null}

              {!currentUser ? (
                authMode === "forgot" ? (
                  <div className="mt-4 space-y-3">
                    {forgotDone ? (
                      <div role="status" aria-live="polite" className="rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
                        Якщо акаунт існує, ми надіслали посилання для відновлення пароля на вашу адресу.
                      </div>
                    ) : (
                      <form
                        onSubmit={handleForgotSubmit}
                        aria-describedby={forgotError ? "auth-forgot-error" : undefined}
                        aria-busy={forgotLoading}
                        className="space-y-3"
                      >
                        {forgotError ? <div id="auth-forgot-error" role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{forgotError}</div> : null}
                        <div>
                          <label htmlFor="auth-forgot-email" className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-600">
                            Email
                          </label>
                          <input
                            id="auth-forgot-email"
                            type="email"
                            autoComplete="email"
                            required
                            value={forgotEmail}
                            onChange={(event) => setForgotEmail(event.target.value)}
                            placeholder="name@example.com"
                            className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                          />
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="submit"
                            disabled={forgotLoading}
                            className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-70"
                          >
                            {forgotLoading ? "Зачекайте..." : "Надіслати посилання"}
                          </button>
                          <button
                            type="button"
                            onClick={() => { setAuthMode("login"); setForgotError(""); setForgotEmail(""); setForgotDone(false); }}
                            className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
                          >
                            ← Назад до входу
                          </button>
                        </div>
                      </form>
                    )}
                    {forgotDone ? (
                      <button
                        type="button"
                        onClick={() => { setAuthMode("login"); setForgotEmail(""); setForgotDone(false); setForgotError(""); }}
                        className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
                      >
                        ← Повернутися до входу
                      </button>
                    ) : null}
                  </div>
                ) : authMode === "reset" ? (
                  <div className="mt-4 space-y-3">
                    {resetDone ? (
                      <>
                        <div role="status" aria-live="polite" className="rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
                          Пароль успішно оновлено. Тепер можна увійти.
                        </div>
                        <button
                          type="button"
                          onClick={() => { setAuthMode("login"); setResetDone(false); setResetError(""); }}
                          className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700"
                        >
                          Увійти
                        </button>
                      </>
                    ) : (
                      <form
                        onSubmit={handleResetSubmit}
                        aria-describedby={resetError ? "auth-reset-error" : undefined}
                        aria-busy={resetLoading}
                        className="space-y-3"
                      >
                        {resetError ? <div id="auth-reset-error" role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{resetError}</div> : null}
                        <div>
                          <label htmlFor="auth-reset-password" className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-600">
                            Новий пароль
                          </label>
                          <input
                            id="auth-reset-password"
                            type="password"
                            autoComplete="new-password"
                            required
                            minLength={8}
                            value={resetPassword}
                            onChange={(event) => setResetPassword(event.target.value)}
                            placeholder="Щонайменше 8 символів"
                            className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                            aria-describedby={resetError ? "auth-reset-error" : undefined}
                          />
                        </div>
                        <div>
                          <label htmlFor="auth-reset-password-confirmation" className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-600">
                            Підтвердіть новий пароль
                          </label>
                          <input
                            id="auth-reset-password-confirmation"
                            type="password"
                            autoComplete="new-password"
                            required
                            minLength={8}
                            value={resetPasswordConfirmation}
                            onChange={(event) => setResetPasswordConfirmation(event.target.value)}
                            className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                            aria-describedby={resetError ? "auth-reset-error" : undefined}
                          />
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="submit"
                            disabled={resetLoading}
                            className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-70"
                          >
                            {resetLoading ? "Зачекайте..." : "Зберегти новий пароль"}
                          </button>
                          <button
                            type="button"
                            onClick={() => { setAuthMode("login"); setResetError(""); setResetPassword(""); setResetPasswordConfirmation(""); resetTokenRef.current = null; }}
                            className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
                          >
                            Скасувати
                          </button>
                        </div>
                      </form>
                    )}
                  </div>
                ) : (
                <form
                  onSubmit={handleAuthSubmit}
                  aria-describedby={`${authError ? "auth-error " : ""}${authSuccess ? "auth-success" : ""}`.trim() || undefined}
                  aria-busy={authLoading}
                  className="mt-4 space-y-3"
                >
                  {authMode === "register" ? (
                    <div className="space-y-2">
                      <p className="text-xs font-black uppercase tracking-wide text-slate-500">Тип кабінету</p>
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                        {ACCOUNT_TYPE_OPTIONS.map((option) => (
                          <button
                            key={option.id}
                            type="button"
                            onClick={() => updateAuthForm("accountType", option.id)}
                            aria-pressed={authForm.accountType === option.id}
                            className={`rounded-2xl border p-3 text-left transition ${
                              authForm.accountType === option.id
                                ? "border-blue-600 bg-blue-50 text-blue-900"
                                : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                            }`}
                          >
                            <span className="block text-sm font-bold">{option.label}</span>
                            <span className="mt-0.5 block text-[11px] text-slate-500">{option.hint}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {authMode === "register" ? (
                    <div>
                      <label htmlFor="auth-name" className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-600">
                        Ваше ім&apos;я
                      </label>
                      <input
                        id="auth-name"
                        type="text"
                        autoComplete="name"
                        value={authForm.name}
                        onChange={(event) => updateAuthForm("name", event.target.value)}
                        placeholder="Наприклад, Олена"
                        className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                      />
                    </div>
                  ) : null}
                  <div>
                    <label htmlFor="auth-email" className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-600">
                      Email
                    </label>
                    <input
                      id="auth-email"
                      type="email"
                      autoComplete="email"
                      value={authForm.email}
                      onChange={(event) => updateAuthForm("email", event.target.value)}
                      placeholder="name@example.com"
                      className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                    />
                  </div>
                  <div>
                    <label htmlFor="auth-password" className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-600">
                      Пароль
                    </label>
                    <input
                      id="auth-password"
                      type="password"
                      autoComplete={authMode === "login" ? "current-password" : "new-password"}
                      value={authForm.password}
                      onChange={(event) => updateAuthForm("password", event.target.value)}
                      placeholder="Щонайменше 8 символів"
                      className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="submit"
                      disabled={authLoading}
                      className="inline-flex min-h-12 items-center justify-center rounded-2xl bg-blue-600 px-5 text-sm font-black text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-70"
                    >
                      {authLoading ? "Зачекайте..." : authMode === "login" ? "Увійти" : "Зареєструватися"}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setAuthMode((current) => (current === "login" ? "register" : "login")); setAuthError(""); setAuthSuccess(""); }}
                      className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-slate-200 bg-white px-5 text-sm font-bold text-slate-700 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                    >
                      {authMode === "login" ? "Створити акаунт" : "Уже є акаунт"}
                    </button>
                    {authMode === "login" ? (
                      <button
                        type="button"
                        onClick={() => { setAuthMode("forgot"); setAuthError(""); setAuthSuccess(""); setForgotError(""); setForgotEmail(authForm.email); setForgotDone(false); }}
                        className="inline-flex min-h-12 items-center justify-center rounded-2xl px-4 text-sm font-bold text-slate-600 transition hover:bg-slate-100 hover:text-blue-700"
                      >
                        Забули пароль?
                      </button>
                    ) : null}
                  </div>
                </form>
                )
              ) : (
                <div className="mt-4 space-y-4">
                  <section className="rounded-[28px] bg-[linear-gradient(135deg,#0f172a,#1e3a8a)] p-5 text-white shadow-xl shadow-slate-900/10 sm:p-6">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-300">{currentUser.email}</p>
                        <p className="mt-1 text-xs text-slate-400">{cabinet.badge} · {planName}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => (planLimitReached ? openPlansModal() : openCreateListingModal())}
                        className="inline-flex min-h-12 w-full items-center justify-center rounded-2xl bg-white px-5 text-sm font-black text-slate-950 shadow-lg transition hover:bg-blue-50 sm:w-auto"
                      >
                        {planLimitReached
                          ? "Оновити тариф"
                          : isDeveloperCabinet
                            ? "Додати новобудову"
                            : "Створити оголошення"}
                      </button>
                    </div>
                    <dl className="mt-5 grid grid-cols-3 gap-2 sm:gap-3">
                      {[
                        ["Активні", activeMyListingsCount],
                        ["Усього", myListings.length],
                        ["Фото", myListingPhotoCount],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-2xl border border-white/10 bg-white/10 px-3 py-3">
                          <dt className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</dt>
                          <dd className="mt-1 text-xl font-black text-white">{value}</dd>
                        </div>
                      ))}
                    </dl>
                  </section>

                  {planLimitReached ? (
                    <p role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">
                      Ліміт публікацій вичерпано. Оновіть тариф, щоб додати ще оголошення.
                    </p>
                  ) : null}

                  <details className="group rounded-2xl border border-slate-200 bg-slate-50">
                    <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-black text-slate-900">
                      Профіль і тариф
                      <span aria-hidden="true" className="text-slate-500 transition group-open:rotate-180">⌄</span>
                    </summary>
                    <div className="border-t border-slate-200 p-4">
                      <dl className="grid gap-3 text-sm sm:grid-cols-2">
                        <div>
                          <dt className="text-xs font-bold uppercase tracking-wide text-slate-500">Тип профілю</dt>
                          <dd className="mt-1 font-semibold text-slate-900">{cabinet.badge}</dd>
                        </div>
                        <div>
                          <dt className="text-xs font-bold uppercase tracking-wide text-slate-500">Тариф</dt>
                          <dd className="mt-1 font-semibold text-slate-900">{planName}</dd>
                          {planQuota ? <dd className="mt-1 text-xs text-slate-600">{planQuota}</dd> : null}
                        </div>
                      </dl>
                      {isRealtorCabinet ? (
                        <p className="mt-3 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
                          Агентство: {currentUser.agency_slug || "профіль ще не підключено"}.
                        </p>
                      ) : null}
                      {isDeveloperCabinet ? (
                        <p className="mt-3 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
                          Новобудови публікуються як окремий формат оголошень.
                        </p>
                      ) : null}
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => openPlansModal()}
                          className="inline-flex min-h-11 items-center justify-center rounded-xl bg-blue-600 px-4 text-xs font-black text-white transition hover:bg-blue-700"
                        >
                          {planIsFree ? "Обрати тариф" : "Змінити тариф"}
                        </button>
                        <button
                          type="button"
                          onClick={switchAccountType}
                          disabled={accountTypeSwitching}
                          className="inline-flex min-h-11 items-center justify-center rounded-xl border border-slate-200 bg-white px-4 text-xs font-bold text-slate-700 transition hover:border-blue-200 hover:bg-blue-50 disabled:opacity-60"
                        >
                          {accountTypeSwitching
                            ? "Перемикаємо…"
                            : isDeveloperCabinet
                              ? "Кабінет власника"
                              : isRealtorCabinet
                                ? "Кабінет забудовника"
                                : "Кабінет ріелтора"}
                        </button>
                        <button
                          type="button"
                          onClick={logoutProfile}
                          className="inline-flex min-h-11 items-center justify-center rounded-xl px-4 text-xs font-bold text-slate-500 transition hover:bg-rose-50 hover:text-rose-700"
                        >
                          Вийти
                        </button>
                      </div>
                    </div>
                  </details>
                  {publishSuccess ? (
                    <div
                      id="publish-success"
                      className={`rounded-2xl border p-4 ${
                        publishSuccess.isPublished
                          ? "border-emerald-300 bg-emerald-50"
                          : "border-amber-300 bg-amber-50"
                      }`}
                      role="status"
                      aria-live="polite"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className={publishSuccess.isPublished ? "font-black text-emerald-900" : "font-black text-amber-900"}>
                            {publishSuccess.isEditing
                              ? "Зміни успішно завантажено"
                              : publishSuccess.isPublished
                                ? "Оголошення успішно завантажено й опубліковано"
                                : "Оголошення успішно завантажено й надіслано на перевірку"}
                          </p>
                          <p className={`mt-1 text-sm ${publishSuccess.isPublished ? "text-emerald-800" : "text-amber-800"}`}>
                            {publishSuccess.title} доступне в розділі «Мої оголошення»
                            {publishSuccess.isPublished ? " і вже показується в каталозі." : "; після перевірки воно з’явиться в каталозі."}
                          </p>
                        </div>
                        <div className="flex gap-2">
                          {publishSuccess.id && publishSuccess.isPublished ? (
                            <a
                              href={`/listing/${publishSuccess.id}`}
                              className="inline-flex min-h-11 items-center rounded-xl bg-emerald-700 px-4 text-sm font-bold text-white"
                            >
                              Переглянути
                            </a>
                          ) : null}
                          <button
                            type="button"
                            onClick={() => setPublishSuccess(null)}
                            className={`min-h-11 rounded-xl border px-3 text-sm font-bold ${
                              publishSuccess.isPublished
                                ? "border-emerald-300 text-emerald-900"
                                : "border-amber-300 text-amber-900"
                            }`}
                            aria-label="Закрити повідомлення про публікацію"
                          >
                            Закрити
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  <section
                    id="inquiries"
                    className="rounded-3xl border border-blue-100 bg-blue-50 p-3 sm:p-4"
                    aria-labelledby="inquiries-title"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <h2 id="inquiries-title" className="text-xs font-black uppercase tracking-wide text-blue-700">
                          Заявки покупців
                        </h2>
                        <p className="mt-1 text-sm text-slate-600">Контакти й відповіді щодо ваших оголошень.</p>
                      </div>
                      <span className="rounded-full bg-white px-2 py-1 text-xs font-bold text-blue-700">
                        {inquiries.filter((item) => item.status === "new").length} нових
                      </span>
                    </div>
                    {inquiryMessage ? (
                      <p className="mt-3 rounded-xl bg-white px-3 py-2 text-sm font-semibold text-slate-700" role="status">
                        {inquiryMessage}
                      </p>
                    ) : null}
                    {inquiriesLoading ? (
                      <p className="mt-4 text-sm text-slate-600">Завантаження заявок…</p>
                    ) : inquiries.length ? (
                      <ul className="mt-4 grid gap-3 lg:grid-cols-2">
                        {inquiries.map((inquiry) => (
                          <li key={inquiry.id} className="rounded-2xl border border-blue-100 bg-white p-4 shadow-sm">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="truncate font-black text-slate-900">{inquiry.listing_title}</p>
                                <p className="mt-1 text-sm font-semibold text-slate-700">{inquiry.name}</p>
                              </div>
                              <span className={`rounded-full px-2 py-1 text-[10px] font-black uppercase ${
                                inquiry.status === "new"
                                  ? "bg-amber-100 text-amber-800"
                                  : inquiry.status === "responded"
                                    ? "bg-emerald-100 text-emerald-800"
                                    : "bg-slate-100 text-slate-700"
                              }`}>
                                {inquiry.status === "new"
                                  ? "Нова"
                                  : inquiry.status === "viewed"
                                    ? "Переглянута"
                                    : inquiry.status === "responded"
                                      ? "Відповіли"
                                      : "Закрита"}
                              </span>
                            </div>
                            <div className="mt-3 space-y-1 text-sm text-slate-700">
                              {inquiry.phone ? <p><a href={`tel:${inquiry.phone}`} className="font-bold text-blue-700">{inquiry.phone}</a></p> : null}
                              {inquiry.email ? <p><a href={`mailto:${inquiry.email}`} className="font-bold text-blue-700">{inquiry.email}</a></p> : null}
                              <p>Зручний канал: {inquiry.preferred_channel === "chat" ? "повідомлення без дзвінка" : inquiry.preferred_channel}</p>
                              {inquiry.message ? <p className="rounded-xl bg-slate-50 p-2">{inquiry.message}</p> : null}
                              {inquiry.response_message ? <p className="rounded-xl bg-emerald-50 p-2 text-emerald-900">Ваша відповідь: {inquiry.response_message}</p> : null}
                            </div>
                            <div className="mt-3 flex flex-wrap gap-2">
                              {inquiry.status === "new" ? (
                                <button type="button" onClick={() => updateInquiry(inquiry, "viewed")} className="min-h-11 rounded-xl border border-slate-200 px-3 text-xs font-bold text-slate-700">
                                  Позначити переглянутою
                                </button>
                              ) : null}
                              {inquiry.status !== "responded" && inquiry.status !== "closed" ? (
                                <button type="button" onClick={() => updateInquiry(inquiry, "responded")} className="min-h-11 rounded-xl bg-blue-600 px-3 text-xs font-black text-white">
                                  Записати відповідь
                                </button>
                              ) : null}
                              {inquiry.status !== "closed" ? (
                                <button type="button" onClick={() => updateInquiry(inquiry, "closed")} className="min-h-11 rounded-xl px-3 text-xs font-bold text-slate-500">
                                  Закрити
                                </button>
                              ) : null}
                            </div>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-4 rounded-2xl border border-dashed border-blue-200 bg-white p-5 text-center text-sm text-slate-600">
                        Нових заявок ще немає.
                      </p>
                    )}
                  </section>

                  <div
                    id="my-listings"
                    tabIndex={-1}
                    aria-labelledby="my-listings-title"
                    className="scroll-mt-4 rounded-3xl border border-slate-200 bg-slate-50 p-3 outline-none focus-visible:ring-4 focus-visible:ring-blue-200 sm:p-4"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <h2 id="my-listings-title" className="text-xs font-black uppercase tracking-wide text-slate-500">Мої оголошення</h2>
                      {myListingsLoading ? (
                        <span className="text-xs text-slate-500">Завантаження…</span>
                      ) : (
                        <span className="rounded-full bg-white px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                          {activeMyListingsCount} активних
                        </span>
                      )}
                    </div>
                    <div className="mt-3 flex max-w-full gap-2 overflow-x-auto pb-1" aria-label="Фільтр моїх оголошень">
                      {[
                        ["all", "Усі"],
                        ["active", "Активні"],
                        ["review", "Модерація"],
                        ["draft", "Чернетки"],
                        ["archived", "Архів"],
                      ].filter(([id]) => id === "all" || myListingCounts[id] > 0).map(([id, label]) => (
                        <button
                          key={id}
                          type="button"
                          onClick={() => setMyListingsFilter(id)}
                          aria-pressed={myListingsFilter === id}
                          className={`min-h-11 shrink-0 rounded-xl px-3 text-xs font-bold ${
                            myListingsFilter === id
                              ? "bg-slate-900 text-white"
                              : "border border-slate-200 bg-white text-slate-700"
                          }`}
                        >
                          {label} · {myListingCounts[id]}
                        </button>
                      ))}
                    </div>
                    {visibleMyListings.length ? (
                      <ul className="mt-4 grid gap-4 lg:grid-cols-2">
                        {visibleMyListings.map((item) => {
                          const image = Array.isArray(item.images) ? item.images.find(Boolean) : "";
                          const photoCount = Number(item.image_count ?? (Array.isArray(item.images) ? item.images.filter(Boolean).length : 0));
                          const videoCount = Number(item.video_count ?? (Array.isArray(item.videos) ? item.videos.filter(Boolean).length : 0));
                          const completeness = getListingCompleteness(item).score;
                          return (
                          <li key={item.id} className="overflow-hidden rounded-[24px] border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg">
                            <div className="grid sm:grid-cols-[150px_1fr]">
                              <div className="aspect-[16/9] bg-slate-200 sm:aspect-auto sm:min-h-[160px]">
                                {image ? (
                                  <img
                                    src={image}
                                    alt=""
                                    width="300"
                                    height="200"
                                    loading="lazy"
                                    className="h-full w-full object-cover"
                                  />
                                ) : (
                                  <div className="flex h-full min-h-32 items-center justify-center text-4xl" aria-label="Фото відсутнє">🏠</div>
                                )}
                              </div>
                              <div className="min-w-0 p-4">
                                <div className="flex items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <p className="truncate text-base font-black text-slate-900">{item.title}</p>
                                    <p className="mt-1 text-sm text-slate-600">{item.city}, {item.district}</p>
                                  </div>
                                  <span className="shrink-0 rounded-full bg-blue-50 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-blue-700">
                                    {getListingStatusLabel(item)}
                                  </span>
                                </div>
                                <p className="mt-3 text-base font-black text-slate-900">
                                  ${Number(item.price || 0).toLocaleString("uk-UA")}
                                  <span className="ml-2 text-xs font-semibold text-slate-500">
                                    {item.rooms} кімн. · {item.area} м²
                                  </span>
                                </p>
                                <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold text-slate-600">
                                  <span>{photoCount} фото</span>
                                  <span>{videoCount} відео</span>
                                  <span>Заповнено {completeness}%</span>
                                </div>
                                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                                  <span className="block h-full rounded-full bg-emerald-500" style={{ width: `${completeness}%` }} />
                                </div>
                                <div className="mt-4 flex flex-wrap gap-2">
                                  {item.status === "published" ? (
                                    <a
                                      href={`/listing/${item.id}`}
                                      className="inline-flex min-h-11 items-center justify-center rounded-xl border border-slate-200 px-3 text-xs font-bold text-slate-700 transition hover:bg-slate-50"
                                    >
                                      Переглянути
                                    </a>
                                  ) : null}
                              <button
                                type="button"
                                onClick={() => openEditListingModal(item)}
                                className="min-h-11 rounded-xl bg-blue-600 px-4 text-xs font-black text-white transition hover:bg-blue-700"
                              >
                                Редагувати
                              </button>
                                  <button
                                    type="button"
                                    onClick={() => requestDeleteListing(item)}
                                    className="min-h-11 rounded-xl px-3 text-xs font-bold text-slate-500 transition hover:bg-red-50 hover:text-red-700"
                                  >
                                    Видалити
                                  </button>
                                </div>
                              </div>
                            </div>
                          </li>
                          );
                        })}
                      </ul>
                    ) : (
                      <p className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-600">
                        {myListings.length ? "У цій категорії оголошень немає." : "Ще немає створених оголошень."}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
            ) : (
            <>

            <div
              id="search"
              className={`${
                showMobileFilters ? "fixed inset-0 z-[90] flex bg-slate-950/60" : "hidden"
              } lg:static lg:block lg:scroll-mt-28 lg:bg-transparent`}
              onMouseDown={(event) => {
                if (event.target === event.currentTarget) closeMobileFilters();
              }}
            >
              <div
                ref={mobileFiltersDrawerRef}
                role={showMobileFilters ? "dialog" : undefined}
                aria-modal={showMobileFilters ? "true" : undefined}
                aria-labelledby="mobile-filters-title"
                aria-describedby="mobile-filters-description"
                onMouseDown={(event) => event.stopPropagation()}
                className="ml-auto h-full w-full max-w-md overflow-y-auto bg-gradient-to-br from-blue-50 via-white to-cyan-50 p-5 shadow-2xl lg:h-auto lg:max-w-none lg:overflow-visible lg:rounded-[28px] lg:border lg:border-blue-200 lg:shadow-sm"
              >
              <div className="mb-4 h-1.5 rounded-full bg-gradient-to-r from-blue-600 to-cyan-500" />
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-base">🔎</span>
                    <div>
                      <p className="text-xs font-black uppercase tracking-wide text-slate-500">Фільтри</p>
                      <h2 id="mobile-filters-title" className="mt-0.5 text-xl font-black text-slate-900">
                        Пошук
                      </h2>
                    </div>
                  </div>
                  <p id="mobile-filters-description" className="mt-2 text-sm text-slate-600">Оберіть місто, бюджет, кімнати та збережіть запит для наступного разу.</p>
                </div>
                <div className="flex flex-wrap justify-end gap-2">
                  <button
                    ref={mobileFiltersCloseRef}
                    type="button"
                    onClick={() => closeMobileFilters()}
                    className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700 lg:hidden"
                    aria-label="Закрити фільтри"
                  >
                    ✕ Закрити
                  </button>
                  <a
                    href={SMART_SEARCH_PATH}
                    className="inline-flex min-h-[44px] items-center rounded-2xl border border-blue-200 bg-white px-3 py-2 text-xs font-bold text-blue-700 transition hover:bg-blue-50"
                  >
                    Розумний пошук
                  </a>
                  <button
                    type="button"
                    onClick={resetFilters}
                    className="rounded-2xl bg-slate-900 px-3 py-2 text-xs font-bold text-white transition hover:bg-blue-700"
                  >
                    Скинути фільтри
                  </button>
                </div>
              </div>

              <div className="mt-4 rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3">
                <p className="text-[11px] font-black uppercase tracking-wide text-blue-700">Активні умови</p>
                <p className="mt-1 text-sm text-slate-700">{searchSummary}</p>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {activeFilters.length ? (
                  activeFilters.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => clearActiveFilter(item.key)}
                      className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-blue-200 hover:bg-blue-50"
                      aria-label={`Прибрати фільтр ${item.label}`}
                    >
                      {item.label}
                      <span className="text-slate-400">✕</span>
                    </button>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">Активних фільтрів немає.</p>
                )}
              </div>

              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <label htmlFor="filters-keyword-search" className="text-xs font-black uppercase tracking-wide text-slate-600">
                    Пошук за ключовими словами
                  </label>
                  <button
                    type="button"
                    onClick={clearKeywordSearch}
                    className="rounded-lg border border-blue-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-blue-700 transition hover:bg-blue-100"
                  >
                    Очистити
                  </button>
                </div>
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <input
                    id="filters-keyword-search"
                    type="text"
                    value={keywordDraft}
                    onChange={(e) => setKeywordDraft(e.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        applyKeywordSearch();
                      }
                    }}
                    placeholder="ЖК, метро, вулиця, ремонт, тераса..."
                    className="flex-1 rounded-xl border border-slate-200 bg-white p-3 text-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  />
                  <button
                    type="button"
                    onClick={applyKeywordSearch}
                    className="rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700"
                  >
                    🔎 Застосувати
                  </button>
                </div>
              </div>

              <div className="mt-4">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Швидкі сценарії</p>
                  <button
                    type="button"
                    onClick={saveCurrentSearch}
                    className="text-sm font-semibold text-blue-600 underline transition hover:text-blue-700"
                  >
                    {authToken ? "Зберегти й сповіщати" : "Зберегти запит"}
                  </button>
                </div>
                {accountSyncMessage ? (
                  <p className="mb-3 rounded-xl border border-blue-100 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-800" role="status" aria-live="polite">
                    {accountSyncMessage}
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  {QUICK_SCENARIOS.map((scenario) => {
                    const isActive = propertyTypeFilter === scenario.value;
                    return (
                      <button
                        key={scenario.label}
                        type="button"
                        onClick={() => applyScenario(scenario)}
                        className={`rounded-xl px-3 py-2 text-sm font-semibold transition ${
                          isActive
                            ? "bg-blue-600 text-white shadow-sm"
                            : "bg-slate-100 text-slate-800 hover:bg-slate-200"
                        }`}
                      >
                        {scenario.label}
                      </button>
                    );
                  })}
                </div>
                {!!savedSearches.length && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {savedSearches.slice(0, 4).map((entry) => (
                      <span
                        key={entry.id}
                        className="inline-flex items-center gap-2 rounded-full border border-blue-100 bg-white px-3 py-1 text-xs font-semibold text-slate-700"
                      >
                        <button type="button" onClick={() => openSavedSearch(entry)} className="inline-flex min-h-[44px] items-center hover:text-blue-700">
                          {entry.isActive ? "🔔 " : entry.serverId ? "🔕 " : ""}
                          {entry.name}
                        </button>
                        {entry.serverId ? (
                          <button
                            type="button"
                            onClick={() => toggleSavedSearchAlert(entry)}
                            className="inline-flex h-11 items-center px-1 text-blue-700 hover:text-blue-900"
                            aria-label={entry.isActive ? `Призупинити сповіщення ${entry.name}` : `Увімкнути сповіщення ${entry.name}`}
                            title={entry.isActive ? "Призупинити email-сповіщення" : "Увімкнути email-сповіщення"}
                          >
                            {entry.isActive ? "Пауза" : "Увімкнути"}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => deleteSavedSearch(entry)}
                          className="inline-flex h-11 w-11 items-center justify-center text-rose-700 hover:text-rose-900"
                          aria-label={`Видалити пошук ${entry.name}`}
                        >
                          ✕
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div className="mt-4 grid grid-cols-1 gap-4">
                <div>
                  <label htmlFor="filter-city" className="text-xs font-bold uppercase tracking-wide text-slate-600">Місто</label>
                  <select
                    id="filter-city"
                    value={cityFilter}
                    onChange={(e) => setCityFilter(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                  >
                    {cities.map((city) => (
                      <option key={city} value={city}>
                        {city === "Всі" ? "Всі міста України" : city}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label htmlFor="filter-property-type" className="text-xs font-bold uppercase tracking-wide text-slate-600">Тип нерухомості</label>
                  <select
                    id="filter-property-type"
                    value={propertyTypeFilter}
                    onChange={(event) => setPropertyTypeFilter(event.target.value)}
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                  >
                    {PROPERTY_TYPE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                <fieldset>
                  <legend className="text-xs font-bold uppercase tracking-wide text-slate-600">Ціна, $</legend>
                  <div className="mt-1 grid grid-cols-2 gap-2">
                    <label htmlFor="filter-price-min" className="text-xs font-semibold text-slate-600">
                      Від
                      <input
                        id="filter-price-min"
                        type="number"
                        min="0"
                        placeholder="0"
                        value={minPrice}
                        onChange={(e) => setMinPrice(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                      />
                    </label>
                    <label htmlFor="filter-price-max" className="text-xs font-semibold text-slate-600">
                      До
                      <input
                        id="filter-price-max"
                        type="number"
                        min="0"
                        placeholder="Без межі"
                        value={maxPrice}
                        onChange={(e) => setMaxPrice(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                      />
                    </label>
                  </div>
                </fieldset>

                <fieldset>
                  <legend className="text-xs font-bold uppercase tracking-wide text-slate-600">Кімнати</legend>
                  <div className="mt-1 grid grid-cols-2 gap-2">
                    <label htmlFor="filter-rooms-min" className="text-xs font-semibold text-slate-600">
                      Від
                      <input
                        id="filter-rooms-min"
                        type="number"
                        min="0"
                        placeholder="0"
                        value={minRooms}
                        onChange={(e) => setMinRooms(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                      />
                    </label>
                    <label htmlFor="filter-rooms-max" className="text-xs font-semibold text-slate-600">
                      До
                      <input
                        id="filter-rooms-max"
                        type="number"
                        min="0"
                        placeholder="Без межі"
                        value={maxRooms}
                        onChange={(e) => setMaxRooms(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                      />
                    </label>
                  </div>
                </fieldset>

                <fieldset>
                  <legend className="text-xs font-bold uppercase tracking-wide text-slate-600">Площа, м²</legend>
                  <div className="mt-1 grid grid-cols-2 gap-2">
                    <label htmlFor="filter-area-min" className="text-xs font-semibold text-slate-600">
                      Від
                      <input
                        id="filter-area-min"
                        type="number"
                        min="0"
                        placeholder="0"
                        value={minArea}
                        onChange={(e) => setMinArea(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                      />
                    </label>
                    <label htmlFor="filter-area-max" className="text-xs font-semibold text-slate-600">
                      До
                      <input
                        id="filter-area-max"
                        type="number"
                        min="0"
                        placeholder="Без межі"
                        value={maxArea}
                        onChange={(e) => setMaxArea(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                      />
                    </label>
                  </div>
                </fieldset>

                <div>
                  <label htmlFor="filter-sort" className="text-xs font-bold uppercase tracking-wide text-slate-600">Сортування</label>
                  <select
                    id="filter-sort"
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    aria-describedby="filter-sort-help"
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                  >
                    <option value="relevance">Найбільш релевантні</option>
                    <option value="price-asc">Дешевші спочатку</option>
                    <option value="price-desc">Дорожчі спочатку</option>
                    <option value="area-desc">Більша площа спочатку</option>
                    <option value="area-asc">Менша площа спочатку</option>
                  </select>
                  <p id="filter-sort-help" className="mt-1 text-xs text-slate-600">Авто: дешевші спочатку для єОселя</p>
                </div>
              </div>

              <div className="mt-5 rounded-2xl border border-slate-200 bg-white px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <label className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={onlyEOselya}
                      onChange={(e) => setOnlyEOselya(e.target.checked)}
                      className="h-5 w-5"
                    />
                    <span className="font-medium text-slate-700">
                      Тільки об&apos;єкти під <span className="font-bold text-blue-600">єОселя</span>
                    </span>
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      if (!window.matchMedia("(min-width: 1024px)").matches) closeMobileFilters(false);
                      setShowEOselyaCalculator(true);
                    }}
                    className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-bold text-blue-700 transition hover:bg-blue-100"
                  >
                    Калькулятор 3% / 7%
                  </button>
                </div>
                <p className="mt-2 text-xs text-slate-500">Розрахуйте комісію для об’єкта за ставками 3% або 7%.</p>
              </div>

              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setFavoriteIds([]);
                    setShowFavoritesOnly(false);
                  }}
                  className="rounded-2xl border border-rose-200 bg-white px-4 py-2 text-sm font-bold text-rose-700 transition hover:bg-rose-50"
                >
                  Очистити обрані
                </button>
                <button
                  type="button"
                  onClick={clearSavedFilters}
                  className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-bold text-slate-700 transition hover:bg-slate-100"
                >
                  Очистити localStorage
                </button>
              </div>
              <div className="sticky bottom-0 -mx-5 mt-5 border-t border-slate-200 bg-white/95 p-4 backdrop-blur lg:hidden">
                <button
                  type="button"
                  onClick={() => {
                    closeMobileFilters(false);
                    window.dispatchEvent(
                      new CustomEvent("uah:meaningful-interaction", { detail: { source: "mobile-filters" } })
                    );
                    window.requestAnimationFrame(() => {
                      const results = document.getElementById("results");
                      results?.focus({ preventScroll: true });
                      results?.scrollIntoView({ behavior: getPreferredScrollBehavior(), block: "start" });
                    });
                  }}
                  className="w-full rounded-2xl bg-blue-600 px-4 py-3 text-sm font-black text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700"
                >
                  Показати {visibleProperties.length} оголошень
                </button>
              </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-rose-200 bg-rose-50 p-5 shadow-sm">
              <div className="flex flex-col gap-3">
                <div>
                  <p className="text-xs font-black uppercase tracking-wide text-rose-700">Обрані</p>
                  <p className="mt-1 text-sm text-slate-600">
                    {favoriteStats.count
                      ? `Збережено ${favoriteStats.count} об'єктів, середня ціна $${favoriteStats.avgPrice.toLocaleString(
                          "uk-UA"
                        )}, ${favoriteStats.verifiedCount} під єОселя.`
                      : "Додавайте об'єкти в обране, щоб повертатися до них швидше."}
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setShowFavoritesOnly((current) => !current)}
                    className={`min-h-[44px] rounded-2xl px-4 text-sm font-bold transition ${
                      showFavoritesOnly
                        ? "bg-rose-600 text-white hover:bg-rose-700"
                        : "border border-rose-200 bg-white text-rose-700 hover:bg-rose-100"
                    }`}
                  >
                    {showFavoritesOnly ? "❤️ Показую лише обрані" : "🤍 Показати лише обрані"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowFavoritesOnly(true);
                      activatePanel("favorites");
                    }}
                    className="min-h-[44px] rounded-2xl bg-slate-900 px-4 text-sm font-bold text-white transition hover:bg-blue-700"
                  >
                    Порівняти зараз
                  </button>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Порівняння обраних</p>
                  <p className="mt-1 text-sm text-slate-600">{compareSummary}</p>

                  {!!compareProperties.length && (
                    <div className="mt-4 space-y-3">
                      {compareProperties.map((property) => (
                        <div
                          key={property.id}
                          className={`rounded-xl border p-3 ${
                            property.id === bestValueId
                              ? "border-emerald-300 bg-emerald-50"
                              : "border-slate-200 bg-white"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-sm font-bold text-slate-900">{property.title}</p>
                              <p className="mt-1 text-xs text-slate-500">
                                {property.city}, {property.district}
                              </p>
                            </div>
                            {property.id === bestValueId && (
                              <span className="rounded-full bg-emerald-100 px-2 py-1 text-[10px] font-semibold text-emerald-700">
                                BEST VALUE
                              </span>
                            )}
                          </div>
                          <div className="mt-3 space-y-1.5 text-sm text-slate-700">
                            <div className="flex justify-between gap-3">
                              <span>Ціна</span>
                              <b>${property.price.toLocaleString("uk-UA")}</b>
                            </div>
                            <div className="flex justify-between gap-3">
                              <span>Площа</span>
                              <b>{property.area} м²</b>
                            </div>
                            <div className="flex justify-between gap-3">
                              <span>Кімнати</span>
                              <b>{property.rooms}</b>
                            </div>
                            <div className="flex justify-between gap-3">
                              <span>єОселя</span>
                              <b>{property.eOselya ? "Так" : "Ні"}</b>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {!!favoriteProperties.length && (
                  <div className="flex flex-wrap gap-2">
                    {favoriteProperties.slice(0, 4).map((property) => (
                      <span
                        key={property.id}
                        className="inline-flex items-center gap-2 rounded-full border border-rose-100 bg-white px-3 py-1 text-xs font-semibold text-slate-700"
                      >
                        {property.title}
                        <button
                          type="button"
                          onClick={() => toggleFavorite(property)}
                          className="inline-flex h-11 w-11 items-center justify-center text-rose-700 hover:text-rose-900"
                          aria-label={`Прибрати ${property.title} з обраного`}
                        >
                          ✕
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
            </>
            )}
          </aside>

          {!sellerCabinetMode ? (
          <div className="order-1 space-y-4 lg:order-2 lg:col-span-8">
            <div
              id="results"
              tabIndex={-1}
              aria-busy={catalogLoading}
              className="scroll-mt-24 rounded-[28px] border border-slate-200 bg-white p-4 shadow-sm outline-none"
            >
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="text-xs font-black uppercase tracking-wide text-slate-500">Результати</p>
                  <h2 className="mt-1 text-2xl font-black text-slate-900">
                    {catalogLoading && !catalogProperties.length
                      ? "Завантажуємо оголошення"
                      : visibleProperties.length
                      ? `Показано ${visibleProperties.length} з ${catalogLoaded ? catalogTotal : filteredProperties.length}`
                      : "Нічого не знайдено"}
                  </h2>
                  <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
                    {catalogLoading
                      ? "Оголошення завантажуються."
                      : `Показано ${visibleProperties.length} з ${
                          catalogLoaded ? catalogTotal : filteredProperties.length
                        } оголошень у режимі ${
                          resultsView === "map" ? "карти" : "списку"
                        }.`}
                  </p>
                  <p className="mt-1 text-sm text-slate-600">
                    {catalogError
                      ? catalogError
                      : showFavoritesOnly
                      ? "Лише обрані об'єкти"
                      : "Об'єкти відсортовано за вашими фільтрами та релевантністю"}
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <div
                    data-role="results-view-toggle"
                    role="group"
                    aria-label="Вигляд результатів"
                    className="inline-flex rounded-2xl border border-slate-200 bg-slate-100 p-1"
                  >
                    <button
                      type="button"
                      onClick={() => setResultsView("list")}
                      aria-pressed={resultsView === "list"}
                      className={`rounded-xl px-3 py-2 text-sm font-bold transition ${
                        resultsView === "list"
                          ? "bg-white text-slate-900 shadow-sm"
                          : "text-slate-500 hover:text-slate-900"
                      }`}
                    >
                      Список
                    </button>
                    <button
                      type="button"
                      onClick={() => setResultsView("map")}
                      aria-pressed={resultsView === "map"}
                      className={`rounded-xl px-3 py-2 text-sm font-bold transition ${
                        resultsView === "map"
                          ? "bg-blue-600 text-white shadow-sm"
                          : "text-slate-500 hover:text-slate-900"
                      }`}
                    >
                      Карта
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowFavoritesOnly((current) => !current)}
                    aria-pressed={showFavoritesOnly}
                    className={`rounded-2xl px-4 py-2 text-sm font-bold transition ${
                      showFavoritesOnly
                        ? "bg-rose-600 text-white hover:bg-rose-700"
                        : "border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
                    }`}
                  >
                    {showFavoritesOnly ? "Лише обрані" : "Показати обрані"}
                  </button>
                  <button
                    type="button"
                    onClick={resetFilters}
                    className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-bold text-slate-700 transition hover:bg-slate-100"
                  >
                    Скинути фільтри
                  </button>
                  <label htmlFor="results-sort" className="inline-flex min-h-[44px] items-center gap-2 text-xs font-bold text-slate-600">
                    <span>Сортування</span>
                    <select
                      id="results-sort"
                      value={sortBy}
                      onChange={(e) => setSortBy(e.target.value)}
                      className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
                    >
                      <option value="relevance">Релевантність</option>
                      <option value="price-asc">Дешевші</option>
                      <option value="price-desc">Дорожчі</option>
                      <option value="area-desc">Більша площа</option>
                      <option value="area-asc">Менша площа</option>
                    </select>
                  </label>
                </div>
              </div>
            </div>

            {catalogError ? (
             <div role="alert" className="rounded-[28px] border border-rose-200 bg-rose-50 p-4 shadow-sm">
               <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                 <div>
                   <p className="text-sm font-bold text-rose-700">Каталог тимчасово недоступний</p>
                   <p className="mt-1 text-sm text-rose-700">{catalogError}</p>
                 </div>
                 <button
                   type="button"
                   onClick={loadCatalogListings}
                   className="rounded-2xl border border-rose-200 bg-white px-4 py-2 text-sm font-bold text-rose-700 transition hover:bg-rose-100"
                 >
                   Спробувати ще раз
                 </button>
               </div>
             </div>
            ) : null}

            {resultsView === "map" ? (
              <ListingsMapView properties={visibleProperties} onShowList={() => setResultsView("list")} />
            ) : null}

            <div
              id="favorites"
              className={resultsView === "list" ? "grid grid-cols-1 gap-5 md:grid-cols-2" : "hidden"}
            >
              {visibleProperties.map((property, cardIndex) => (
                <ListingCard
                  key={property.id}
                  property={property}
                  favorite={favoriteIds.includes(property.id)}
                  onToggleFavorite={toggleFavorite}
                  onOpenTrust={openTrustDialog}
                  priority={false}
                />
              ))}
            </div>

            {catalogLoaded && catalogHasMore ? (
              <div className="mt-5 flex flex-col items-center gap-2">
                <button
                  type="button"
                  onClick={() => loadCatalogListings(false, true)}
                  disabled={catalogLoadingMore}
                  aria-busy={catalogLoadingMore}
                  className="inline-flex min-h-[44px] items-center justify-center rounded-2xl bg-slate-900 px-6 py-3 text-sm font-black text-white transition hover:bg-blue-700 disabled:cursor-wait disabled:opacity-60"
                >
                  {catalogLoadingMore ? "Завантажуємо…" : "Показати ще"}
                </button>
                <p className="text-xs text-slate-600">
                  Завантажено {visibleProperties.length} з {catalogTotal} оголошень
                  {resultsView === "map" ? " і точок карти" : ""}.
                </p>
              </div>
            ) : null}

            {resultsView === "list" && visibleProperties.length === 0 && (
              <div className="rounded-[28px] border border-dashed border-slate-200 bg-white py-16 text-center px-6">
                <p className="text-lg font-medium text-slate-400">
                  {catalogLoading && !catalogProperties.length
                    ? "Завантажуємо каталог..."
                    : showFavoritesOnly
                    ? "У вас ще немає обраних об'єктів."
                    : "За вказаними фільтрами нічого не знайдено."}
                </p>
                {!catalogLoading && !showFavoritesOnly && activeFilters.length > 0 && (
                  <button
                    onClick={resetFilters}
                    className="mt-4 rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition"
                  >
                    Скинути всі фільтри
                  </button>
                )}
              </div>
            )}
          </div>
          ) : null}
        </div>
      </section>

      {!sellerCabinetMode &&
      pwaOfferEligible &&
      !pwaInstalled &&
      !pwaInstallDismissed &&
      !pwaHiddenForSession &&
      (pwaInstallPrompt || isIosSafari) ? (
        <aside
          data-role="pwa-install-offer"
          aria-label={canPromptPwaInstall ? "Встановлення UA-Dim" : "Як додати UA-Dim на головний екран"}
          className="mx-auto my-6 w-[calc(100%-2rem)] max-w-7xl rounded-[24px] border border-blue-200 bg-white p-4 shadow-sm"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <span aria-hidden="true" className="shrink-0 text-xl">📱</span>
              <div>
                <span className="sr-only" role="status" aria-live="polite">
                  Доступна пропозиція встановлення UA-Dim.
                </span>
                <p className="text-sm font-black text-slate-900">
                  {canPromptPwaInstall ? "UA-Dim можна встановити як застосунок" : "Додайте UA-Dim на головний екран"}
                </p>
                <p className="mt-1 text-sm text-slate-600">
                  {canPromptPwaInstall
                    ? "Поверніться до пошуку житла одним дотиком."
                    : <>У Safari натисніть <strong>Поділитись</strong> → <strong>На екран Початку</strong>.</>}
                </p>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {canPromptPwaInstall ? (
                <button
                  type="button"
                  onClick={async () => {
                    await pwaInstallPrompt.prompt();
                    await pwaInstallPrompt.userChoice;
                    setPwaInstallPrompt(null);
                    hidePwaOfferForSession();
                  }}
                  className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-black text-white transition hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2"
                >
                  Встановити
                </button>
              ) : null}
              <button
                type="button"
                onClick={dismissPwaOffer}
                aria-label="Закрити пропозицію встановлення на 30 днів"
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-slate-600 transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2"
              >
                Не зараз
              </button>
            </div>
          </div>
        </aside>
      ) : null}

      {trustDialog}

      {planLimitPrompt ? (
        <div
          className="fixed inset-0 z-[110] flex items-center justify-center bg-slate-950/70 px-4 py-8"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPlanLimitPrompt(null);
          }}
        >
          <div
            ref={planDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="plan-limit-title"
            aria-describedby="plan-limit-description"
            className="w-full max-w-md rounded-[32px] border border-slate-200 bg-white p-6 shadow-2xl"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <p className="text-xs font-black uppercase tracking-wide text-rose-700">Ліміт тарифу</p>
            <h2 id="plan-limit-title" className="mt-1 text-xl font-black text-slate-900">Потрібен більший пакет</h2>
            <p id="plan-limit-description" className="mt-2 text-sm text-slate-600">{planLimitPrompt.message}</p>
            <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
              <p>
                Поточний тариф: <span className="font-bold">{planLimitPrompt.planName}</span>
              </p>
              {formatPlanQuota(planLimitPrompt.usage) ? (
                <p className="mt-1 text-xs text-slate-500">{formatPlanQuota(planLimitPrompt.usage)}</p>
              ) : null}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  setPlanLimitPrompt(null);
                  openPlansModal();
                }}
                className="rounded-2xl bg-blue-600 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-700"
              >
                Переглянути тарифи
              </button>
              <button
                ref={planCloseRef}
                type="button"
                onClick={() => setPlanLimitPrompt(null)}
                className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
              >
                Пізніше
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showCreateListingModal ? (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/70 px-4 py-8"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeListingModal();
          }}
        >
          <div
            ref={listingDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="listing-dialog-title"
            aria-describedby="listing-dialog-description"
            className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-[32px] border border-slate-200 bg-white p-6 shadow-2xl"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-black uppercase tracking-wide text-slate-500">
                  {editingListingId ? "Редагувати оголошення" : "Створити оголошення"}
                </p>
                <h2 id="listing-dialog-title" className="mt-1 text-2xl font-black text-slate-900">Профільне оголошення</h2>
                <p id="listing-dialog-description" className="mt-2 text-sm text-slate-600">
                  {editingListingId
                    ? "Змініть поля, збережіть і оголошення залишиться опублікованим на сайті."
                    : "Після відправки оголошення одразу з'явиться в профілі та на сайті."}
                </p>
              </div>
              <button
                ref={listingCloseRef}
                type="button"
                onClick={() => {
                  closeListingModal();
                  setListingMessage("");
                }}
                disabled={listingSubmitting}
                aria-label="Закрити форму оголошення"
                className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                ✕
              </button>
            </div>

            <form
              onSubmit={handleCreateListing}
              aria-busy={listingSubmitting}
              aria-describedby={listingMessage ? "listing-form-message" : undefined}
              className="mt-6 grid gap-4 md:grid-cols-2"
            >
              <div className="md:col-span-2">
                <label htmlFor="listing-title" className="text-xs font-bold uppercase tracking-wide text-slate-600">Назва</label>
                <input
                  id="listing-title"
                  required
                  value={listingForm.title}
                  onChange={(event) => updateListingField("title", event.target.value)}
                  placeholder="Сучасна квартира з ремонтом"
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label htmlFor="listing-city" className="text-xs font-bold uppercase tracking-wide text-slate-600">Місто</label>
                <input
                  id="listing-city"
                  required
                  value={listingForm.city}
                  onChange={(event) => updateListingField("city", event.target.value)}
                  placeholder="Київ"
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label htmlFor="listing-district" className="text-xs font-bold uppercase tracking-wide text-slate-600">Район</label>
                <input
                  id="listing-district"
                  required
                  value={listingForm.district}
                  onChange={(event) => updateListingField("district", event.target.value)}
                  placeholder="Печерський"
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label htmlFor="listing-property-type" className="text-xs font-bold uppercase tracking-wide text-slate-600">Тип об&apos;єкта</label>
                <select
                  id="listing-property-type"
                  value={listingForm.propertyType}
                  onChange={(event) => updateListingField("propertyType", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                >
                  <option value="квартира">Квартира</option>
                  <option value="будинок">Будинок</option>
                  <option value="комерція">Комерція</option>
                  <option value="земля">Земля</option>
                </select>
              </div>
              <div>
                <label htmlFor="listing-condition" className="text-xs font-bold uppercase tracking-wide text-slate-600">Стан</label>
                <select
                  id="listing-condition"
                  value={listingForm.conditionType}
                  onChange={(event) => updateListingField("conditionType", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                >
                  <option value="нова будова">Нова будова</option>
                  <option value="вторинка">Вторинка</option>
                  <option value="після ремонту">Після ремонту</option>
                  <option value="без ремонту">Без ремонту</option>
                </select>
              </div>
              <div>
                <label htmlFor="listing-price" className="text-xs font-bold uppercase tracking-wide text-slate-600">Ціна, $</label>
                <input
                  id="listing-price"
                  required
                  type="number"
                  min="1"
                  value={listingForm.price}
                  onChange={(event) => updateListingField("price", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label htmlFor="listing-rooms" className="text-xs font-bold uppercase tracking-wide text-slate-600">Кімнат</label>
                <input
                  id="listing-rooms"
                  required
                  type="number"
                  min="0"
                  value={listingForm.rooms}
                  onChange={(event) => updateListingField("rooms", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label htmlFor="listing-area" className="text-xs font-bold uppercase tracking-wide text-slate-600">Площа, м²</label>
                <input
                  id="listing-area"
                  required
                  type="number"
                  min="1"
                  value={listingForm.area}
                  onChange={(event) => updateListingField("area", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label htmlFor="listing-floor" className="text-xs font-bold uppercase tracking-wide text-slate-600">Поверх</label>
                <input
                  id="listing-floor"
                  type="number"
                  min="1"
                  value={listingForm.floor}
                  onChange={(event) => updateListingField("floor", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label htmlFor="listing-total-floors" className="text-xs font-bold uppercase tracking-wide text-slate-600">Загалом поверхів</label>
                <input
                  id="listing-total-floors"
                  type="number"
                  min="1"
                  value={listingForm.totalFloors}
                  onChange={(event) => updateListingField("totalFloors", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label htmlFor="listing-year-built" className="text-xs font-bold uppercase tracking-wide text-slate-600">Рік будівництва</label>
                <input
                  id="listing-year-built"
                  type="number"
                  min="1900"
                  value={listingForm.yearBuilt}
                  onChange={(event) => updateListingField("yearBuilt", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div>
                <label htmlFor="listing-offer-type" className="text-xs font-bold uppercase tracking-wide text-slate-600">Тип пропозиції</label>
                <select
                  id="listing-offer-type"
                  value={listingForm.listingType}
                  onChange={(event) => updateListingField("listingType", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                >
                  <option value="sale">Продаж</option>
                  <option value="rent">Оренда</option>
                </select>
              </div>
              <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 md:col-span-2">
                <input
                  id="listing-eoselya"
                  type="checkbox"
                  checked={listingForm.eOselya}
                  onChange={(event) => updateListingField("eOselya", event.target.checked)}
                  className="h-5 w-5"
                />
                <label htmlFor="listing-eoselya" className="text-sm font-semibold text-slate-700">Під єОселя</label>
              </div>
              <div className="md:col-span-2">
                <label htmlFor="listing-description" className="text-xs font-bold uppercase tracking-wide text-slate-600">Опис</label>
                <textarea
                  id="listing-description"
                  rows="4"
                  value={listingForm.description}
                  onChange={(event) => updateListingField("description", event.target.value)}
                  placeholder="Коротко про переваги об'єкта"
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                />
              </div>
              <div className="md:col-span-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Фото оголошення</p>
                    <p className="mt-1 text-xs text-slate-500">Додайте до 8 фотографій об'єкта.</p>
                  </div>
                  <button
                    type="button"
                    onClick={addListingImageField}
                    className="min-h-11 rounded-xl border border-slate-200 bg-white px-3 text-xs font-bold text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                  >
                    Додати фото за посиланням
                  </button>
                </div>
                <div className="mt-3 rounded-3xl border border-blue-100 bg-blue-50/70 p-4">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="flex min-h-14 cursor-pointer items-center justify-center gap-3 rounded-2xl bg-blue-600 px-5 text-center text-sm font-black text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700 focus-within:ring-4 focus-within:ring-blue-200">
                      <span className="text-xl" aria-hidden="true">＋</span>
                      <span>Обрати з фототеки</span>
                      <input
                        type="file"
                        multiple
                        accept="image/*,.heic,.heif,.avif,.webp,.jpeg,.jpg,.png,.gif,.bmp,.tiff"
                        onChange={(event) => handleListingFileSelection(event, "image")}
                        className="sr-only"
                      />
                    </label>
                    {isMobileDevice ? (
                      <label className="flex min-h-14 cursor-pointer items-center justify-center gap-3 rounded-2xl border border-blue-200 bg-white px-5 text-center text-sm font-black text-blue-700 transition hover:border-blue-300 hover:bg-blue-100 focus-within:ring-4 focus-within:ring-blue-200">
                        <span className="text-xl" aria-hidden="true">📷</span>
                        <span>Зробити фото</span>
                        <input
                          type="file"
                          accept="image/*"
                          capture="environment"
                          onChange={(event) => handleListingFileSelection(event, "image")}
                          className="sr-only"
                        />
                      </label>
                    ) : null}
                  </div>
                  <p className="mt-3 text-xs leading-relaxed text-slate-600">
                    Можна вибрати до 8 фото з фототеки телефона. JPG, PNG, WEBP, AVIF, HEIC/HEIF · до 10 МБ кожне.
                  </p>
                  {selectedListingFiles.length ? (
                    <div className="mt-3 space-y-3">
                      <div className="rounded-2xl border border-blue-100 bg-blue-50 p-3">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="text-[11px] font-black uppercase tracking-wide text-blue-700">Фото додано</p>
                            <p className="mt-1 text-sm text-slate-700">
                              {selectedListingFiles.length} фото{selectedListingFiles.length > 1 ? " готові" : " готове"} до публікації.
                            </p>
                          </div>
                          <span className="rounded-full bg-white px-3 py-1 text-[10px] font-bold uppercase tracking-wide text-blue-700">
                            Буде завантажено на сайт
                          </span>
                        </div>
                        <p className="mt-2 text-xs leading-relaxed text-slate-600">
                          Після надсилання фото автоматично завантажаться в оголошення. Воно з’явиться в каталозі одразу для підтверджених продавців або після перевірки.
                        </p>
                      </div>
                      {selectedListingFilePreviews.length ? (
                        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                          {selectedListingFilePreviews.map((preview, previewIndex) => (
                            <div key={preview.id} className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                              <img src={preview.src} alt={preview.name} className="h-28 w-full object-cover" />
                              <span className="absolute left-2 top-2 rounded-full bg-emerald-700 px-2 py-1 text-[10px] font-black uppercase tracking-wide text-white shadow">
                                Готово
                              </span>
                              <div className="border-t border-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600 truncate">
                                {preview.name}
                              </div>
                              <button
                                type="button"
                                onClick={() => removeSelectedListingFile(previewIndex)}
                                className="absolute right-1.5 top-1.5 flex h-11 w-11 items-center justify-center rounded-full bg-black/75 text-white text-xs font-bold hover:bg-red-700 transition"
                                aria-label={`Видалити фото ${preview.name}`}
                              >
                                ✕
                              </button>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          {selectedListingFiles.map((file, fileIndex) => (
                            <span
                              key={`${file.name}-${file.size}-${file.lastModified}`}
                              className="flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700"
                            >
                              {file.name}
                              <button
                                type="button"
                                onClick={() => removeSelectedListingFile(fileIndex)}
                                className="ml-1 inline-flex h-11 w-11 items-center justify-center text-blue-700 hover:text-red-700 font-black"
                                aria-label={`Видалити фото ${file.name}`}
                              >
                                ✕
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : null}

                </div>
                <div className="mt-3 space-y-2">
                  {listingForm.images.map((image, index) => (
                    <div key={`${index}-${image}`} className="flex items-center gap-2">
                      <label htmlFor={`listing-image-${index}`} className="min-w-0 flex-1 text-xs font-semibold text-slate-600">
                        Посилання на фото {index + 1}
                        <input
                          id={`listing-image-${index}`}
                          type="url"
                          value={image}
                          onChange={(event) => updateListingImage(index, event.target.value)}
                          placeholder="https://…"
                          className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
                        />
                      </label>
                      {listingForm.images.length > 1 ? (
                        <button
                          type="button"
                          onClick={() => removeListingImageField(index)}
                          aria-label={`Видалити поле посилання на фото ${index + 1}`}
                          className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700"
                        >
                          ✕
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
              <div className="md:col-span-2">
                <div>
                  <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Відео оголошення</p>
                  <p className="mt-1 text-xs text-slate-500">Додайте до 2 коротких відео або відеотурів.</p>
                </div>
                <div className="mt-3 rounded-3xl border border-violet-100 bg-violet-50/70 p-4">
                  <label className="flex min-h-14 cursor-pointer items-center justify-center gap-3 rounded-2xl bg-slate-900 px-5 text-center text-sm font-black text-white shadow-lg shadow-slate-900/15 transition hover:bg-violet-700 focus-within:ring-4 focus-within:ring-violet-200">
                    <span className="text-xl" aria-hidden="true">▶</span>
                    <span>Обрати відео</span>
                    <input
                      type="file"
                      multiple
                      accept="video/mp4,video/quicktime,video/webm,video/x-m4v,.mp4,.mov,.webm,.m4v"
                      onChange={(event) => handleListingFileSelection(event, "video")}
                      className="sr-only"
                    />
                  </label>
                  <p className="mt-3 text-xs leading-relaxed text-slate-600">
                    MP4, MOV з iPhone, WEBM або M4V · до 100 МБ кожне.
                  </p>
                  {listingForm.videos.length || selectedListingVideoPreviews.length ? (
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      {listingForm.videos.map((videoUrl, index) => (
                        <div key={videoUrl} className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white">
                          <video controls playsInline preload="metadata" src={videoUrl} className="aspect-video w-full bg-slate-900 object-contain" />
                          <button
                            type="button"
                            onClick={() => removeExistingListingVideo(index)}
                            className="absolute right-2 top-2 flex h-11 w-11 items-center justify-center rounded-full bg-black/75 font-bold text-white"
                            aria-label={`Видалити збережене відео ${index + 1}`}
                          >
                            ✕
                          </button>
                        </div>
                      ))}
                      {selectedListingVideoPreviews.map((preview, index) => (
                        <div key={preview.id} className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white">
                          <video controls playsInline preload="metadata" src={preview.src} className="aspect-video w-full bg-slate-900 object-contain" />
                          <p className="truncate px-3 py-2 text-xs font-semibold text-slate-600">{preview.name}</p>
                          <button
                            type="button"
                            onClick={() => removeSelectedListingVideo(index)}
                            className="absolute right-2 top-2 flex h-11 w-11 items-center justify-center rounded-full bg-black/75 font-bold text-white"
                            aria-label={`Видалити відео ${preview.name}`}
                          >
                            ✕
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
              {mediaUploadStatus ? (
                <p className="rounded-xl bg-blue-50 p-3 text-sm font-bold text-blue-800 md:col-span-2" role="status" aria-live="polite">
                  {mediaUploadStatus}
                </p>
              ) : null}
              {listingMessage ? (
                <p id="listing-form-message" className="rounded-xl bg-rose-50 p-3 text-sm font-bold text-rose-800 md:col-span-2" role="alert">
                  {listingMessage}
                </p>
              ) : null}
              <div className="flex flex-wrap gap-3 md:col-span-2">
                <button
                  type="submit"
                  disabled={listingSubmitting}
                  className="inline-flex min-h-12 items-center justify-center rounded-2xl bg-blue-600 px-5 text-sm font-black text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {listingSubmitting
                    ? editingListingId
                      ? "Зміни зберігаються…"
                      : "Оголошення завантажується…"
                    : editingListingId
                      ? "Зберегти зміни"
                      : "Надіслати оголошення"}
                </button>
                {editingListingId ? (
                  <button
                    type="button"
                    onClick={() =>
                      requestDeleteListing(
                        myListings.find((listing) => listing.id === editingListingId) || {
                          id: editingListingId,
                          title: listingForm.title,
                        }
                      )
                    }
                    disabled={listingSubmitting}
                    className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-bold text-rose-700 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    Видалити оголошення
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => {
                    closeListingModal();
                    setListingMessage("");
                  }}
                  disabled={listingSubmitting}
                  className="min-h-12 rounded-2xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Скасувати
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {deleteCandidate ? (
        <div
          className="fixed inset-0 z-[110] flex items-center justify-center bg-slate-950/70 px-4 py-8"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDeleteCandidate(null);
          }}
        >
          <div
            ref={deleteDialogRef}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-listing-title"
            aria-describedby="delete-listing-description"
            className="w-full max-w-md rounded-[28px] border border-red-200 bg-white p-6 shadow-2xl"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <p className="text-xs font-black uppercase tracking-wide text-red-700">Незворотна дія</p>
            <h2 id="delete-listing-title" className="mt-2 text-xl font-black text-slate-900">
              Видалити оголошення?
            </h2>
            <p id="delete-listing-description" className="mt-3 text-sm leading-relaxed text-slate-700">
              «{deleteCandidate.title || "Оголошення"}» одразу зникне з кабінету, каталогу та публічної сторінки.
              Відновити його після видалення неможливо.
            </p>
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <button
                ref={deleteCancelRef}
                type="button"
                onClick={() => setDeleteCandidate(null)}
                disabled={listingSubmitting}
                className="min-h-11 rounded-xl border border-slate-300 bg-white px-4 text-sm font-bold text-slate-800 disabled:opacity-60"
              >
                Скасувати
              </button>
              <button
                type="button"
                onClick={handleDeleteListing}
                disabled={listingSubmitting}
                className="min-h-11 rounded-xl bg-red-700 px-4 text-sm font-bold text-white transition hover:bg-red-800 disabled:opacity-60"
              >
                {listingSubmitting ? "Видаляємо…" : "Так, видалити"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

if (typeof document !== "undefined") {
  const root = document.getElementById("root");
  if (root && window.ReactDOM?.createRoot) {
    const renderApp = () => {
      if (root.dataset.mounted === "true") return;
      root.dataset.mounted = "true";
      window.ReactDOM.createRoot(root).render(React.createElement(RealEstateApp));
    };
    const sellerPage =
      /^\/seller\/?$/.test(window.location.pathname) ||
      new URLSearchParams(window.location.search).get("seller") === "1";
    const hero = sellerPage ? null : document.querySelector('[data-role="homepage-hero"]');
    const canObserveHeroPaint =
      hero &&
      "PerformanceObserver" in window &&
      PerformanceObserver.supportedEntryTypes?.includes("largest-contentful-paint");

    if (canObserveHeroPaint) {
      const observer = new PerformanceObserver((list) => {
        const heroPainted = list.getEntries().some((entry) => {
          const element = entry.element;
          return !element || element === hero || hero.contains(element);
        });
        if (!heroPainted) return;
        observer.disconnect();
        window.setTimeout(renderApp, 0);
      });
      observer.observe({ type: "largest-contentful-paint", buffered: true });
      window.setTimeout(() => {
        observer.disconnect();
        renderApp();
      }, 250);
    } else {
      window.requestAnimationFrame(renderApp);
    }
  }
}
