import { PERMISSIONS } from "./session.js";

// Information architecture for the staff admin panel. `permission` gates
// both navigation visibility and the module's own guard check.
export const NAV_SECTIONS = [
  {
    id: "overview",
    label: "Огляд",
    items: [
      { id: "overview", label: "Огляд", icon: "grid", permission: PERMISSIONS.DASHBOARD_READ },
    ],
  },
  {
    id: "work",
    label: "Робота",
    items: [
      { id: "moderation", label: "Модерація", icon: "shield", permission: PERMISSIONS.LISTINGS_MODERATE },
      { id: "listings", label: "Оголошення", icon: "home", permission: PERMISSIONS.LISTINGS_READ },
      { id: "requests", label: "Заявки", icon: "inbox", permission: PERMISSIONS.LEADS_MANAGE },
    ],
  },
  {
    id: "community",
    label: "Спільнота",
    items: [
      { id: "users", label: "Користувачі", icon: "users", permission: PERMISSIONS.USERS_MANAGE },
      { id: "agencies", label: "Агенції", icon: "building", permission: PERMISSIONS.AGENCIES_MANAGE },
    ],
  },
  {
    id: "trust",
    label: "Довіра й аналітика",
    items: [
      { id: "prices", label: "Ціни й історія", icon: "history", permission: PERMISSIONS.LISTINGS_READ },
      { id: "analytics", label: "Аналітика", icon: "chart", permission: PERMISSIONS.ADMIN_ONLY },
    ],
  },
  {
    id: "system",
    label: "Система",
    items: [
      { id: "health", label: "Стан системи", icon: "pulse", permission: PERMISSIONS.SYSTEM_READ },
      { id: "audit", label: "Аудит", icon: "list", permission: PERMISSIONS.AUDIT_READ },
    ],
  },
];

export const DEFAULT_ROUTE = "overview";

export function flattenNavItems() {
  return NAV_SECTIONS.flatMap((section) => section.items);
}

export function findNavItem(routeId) {
  return flattenNavItems().find((item) => item.id === routeId) || null;
}
