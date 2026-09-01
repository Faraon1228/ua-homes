// Shared formatting + label dictionaries (Ukrainian labels only — no
// copied concept mock data).
export const currencyFormatter = new Intl.NumberFormat("uk-UA", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

export const numberFormatter = new Intl.NumberFormat("uk-UA");

export function formatPrice(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return currencyFormatter.format(n);
}

export function formatNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return numberFormatter.format(n);
}

export function formatDate(value) {
  if (!value) return "—";
  const date = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("uk-UA", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatPercent(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n.toFixed(1)}%`;
}

export const LISTING_STATUS_LABELS = {
  draft: "Чернетка",
  published: "Опубліковано",
  pending: "На розгляді",
  rejected: "Відхилено",
  archived: "Архів",
};

export const LISTING_LIFECYCLE_LABELS = {
  active: "Активне",
  sold: "Продано",
  removed: "Знято",
};

export const MODERATION_STATUS_LABELS = {
  approved: "Схвалено",
  rejected: "Відхилено",
  pending_review: "Очікує розгляду",
  in_review: "На розгляді",
  changes_requested: "Потрібні правки",
};

export const VERIFICATION_STATUS_LABELS = {
  unverified: "Не перевірено",
  pending: "Очікує",
  verified: "Підтверджено",
  rejected: "Відхилено",
};

export const REPORT_STATUS_LABELS = {
  pending: "Очікує",
  reviewing: "На розгляді",
  resolved: "Вирішено",
  dismissed: "Відхилено",
};

export const LEAD_STATUS_LABELS = {
  new: "Нова",
  viewed: "Переглянута",
  responded: "Опрацьовано",
  closed: "Закрита",
};

export const USER_ROLE_LABELS = {
  user: "Користувач",
  agent: "Агент",
  moderator: "Модератор",
  admin: "Адміністратор",
};

export const USER_STATUS_LABELS = {
  active: "Активний",
  inactive: "Неактивний",
  suspended: "Заблокований",
};
