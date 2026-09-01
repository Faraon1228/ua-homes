import React from "../react-shim.js";
import { Icon } from "./icons.jsx";

export function Skeleton({ rows = 5, label = "Завантаження даних", testId = "loading-skeleton" }) {
  return React.createElement(
    "div",
    { className: "skeleton-block", role: "status", "aria-label": label, "data-testid": testId },
    Array.from({ length: rows }).map((_, index) =>
      React.createElement("div", { key: index, className: "skeleton-row" }),
    ),
  );
}

export function EmptyState({ icon = "inbox", title, description, action, testId = "empty-state" }) {
  return React.createElement(
    "div",
    { className: "empty-state", "data-testid": testId },
    React.createElement(Icon, { name: icon, size: 34 }),
    React.createElement("p", { className: "empty-state-title" }, title),
    description ? React.createElement("p", { className: "empty-state-description" }, description) : null,
    action || null,
  );
}

export function ErrorState({ message, onRetry, testId = "error-state" }) {
  return React.createElement(
    "div",
    { className: "error-state", role: "alert", "data-testid": testId },
    React.createElement(Icon, { name: "alert", size: 30 }),
    React.createElement("p", { className: "error-state-message" }, message || "Не вдалося завантажити дані."),
    onRetry
      ? React.createElement(
          "button",
          { type: "button", className: "btn btn-secondary", onClick: onRetry, "data-testid": "error-retry-button" },
          React.createElement(Icon, { name: "refresh", size: 15 }),
          "Спробувати ще раз",
        )
      : null,
  );
}

export function Pagination({ total, limit, offset, onChange, testId = "pagination" }) {
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.floor(offset / limit) + 1;
  const canPrev = offset > 0;
  const canNext = offset + limit < total;
  return React.createElement(
    "nav",
    { className: "pagination", "aria-label": "Сторінки", "data-testid": testId },
    React.createElement(
      "span",
      { className: "pagination-summary" },
      `Показано ${total === 0 ? 0 : offset + 1}–${Math.min(offset + limit, total)} з ${total}`,
    ),
    React.createElement(
      "div",
      { className: "pagination-controls" },
      React.createElement(
        "button",
        {
          type: "button",
          className: "btn btn-icon",
          disabled: !canPrev,
          "aria-label": "Попередня сторінка",
          onClick: () => onChange(Math.max(0, offset - limit)),
          "data-testid": "pagination-prev",
        },
        React.createElement(Icon, { name: "chevron-right", className: "icon-flip", size: 16 }),
      ),
      React.createElement("span", { className: "pagination-page" }, `${currentPage} / ${totalPages}`),
      React.createElement(
        "button",
        {
          type: "button",
          className: "btn btn-icon",
          disabled: !canNext,
          "aria-label": "Наступна сторінка",
          onClick: () => onChange(offset + limit),
          "data-testid": "pagination-next",
        },
        React.createElement(Icon, { name: "chevron-right", size: 16 }),
      ),
    ),
  );
}

export function StatusBadge({ tone = "neutral", children }) {
  return React.createElement("span", { className: `badge badge-${tone}` }, children);
}
