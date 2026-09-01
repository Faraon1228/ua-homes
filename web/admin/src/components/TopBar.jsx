import React from "../react-shim.js";
import { Icon } from "./icons.jsx";
import { GlobalSearch } from "./GlobalSearch.jsx";

export function TopBar({ title, staff, onOpenMobileNav, onLogout, onOpenListing, onOpenUsers }) {
  return (
    <header className="topbar" data-testid="topbar">
      <button
        type="button"
        className="btn btn-icon topbar-menu"
        onClick={onOpenMobileNav}
        aria-label="Відкрити навігацію"
        aria-controls="primary-navigation"
        data-testid="mobile-nav-toggle"
      >
        <Icon name="menu" size={20} />
      </button>
      <h1 className="topbar-title" data-testid="topbar-title">
        {title}
      </h1>
      <GlobalSearch staff={staff} onOpenListing={onOpenListing} onOpenUsers={onOpenUsers} />
      <div className="top-actions">
        <button
          type="button"
          className="btn btn-secondary topbar-logout"
          onClick={onLogout}
          data-testid="logout-button"
        >
          <Icon name="logout" size={16} />
          <span>Вийти</span>
        </button>
      </div>
    </header>
  );
}
