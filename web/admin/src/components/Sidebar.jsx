import React from "../react-shim.js";
import { Icon } from "./icons.jsx";
import { USER_ROLE_LABELS } from "../lib/format.js";

export function Sidebar({ sections, activeRoute, onNavigate, staff, mobileOpen, onCloseMobile, badges }) {
  return (
    <>
      {mobileOpen ? (
        <div
          className="sidebar-scrim"
          onClick={onCloseMobile}
          aria-hidden="true"
          data-testid="mobile-nav-scrim"
        />
      ) : null}
      <nav
        id="primary-navigation"
        className={`sidebar${mobileOpen ? " sidebar-open" : ""}`}
        aria-label="Основна навігація"
        data-testid="primary-nav"
        data-state={mobileOpen ? "open" : "closed"}
      >
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            UD
          </span>
          <div>
            <strong>UA-Dim</strong>
            <span>Адмінпанель</span>
          </div>
          <button
            type="button"
            className="btn btn-icon sidebar-close"
            onClick={onCloseMobile}
            aria-label="Закрити меню"
            data-testid="mobile-nav-close"
          >
            <Icon name="close" size={18} />
          </button>
        </div>
        {sections.map((section) => (
          <div key={section.id} className="nav-group">
            <p className="nav-label">{section.label}</p>
            <div className="nav-list">
              {section.items.map((item) => {
                const count = badges?.[item.id];
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`nav-button${activeRoute === item.id ? " active" : ""}`}
                    aria-current={activeRoute === item.id ? "page" : undefined}
                    onClick={() => onNavigate(item.id)}
                    data-testid={`nav-item-${item.id}`}
                  >
                    <Icon name={item.icon} size={18} />
                    <span>{item.label}</span>
                    {count ? <span className="nav-count">{count}</span> : null}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
        {staff ? (
          <div className="sidebar-profile" data-testid="sidebar-profile">
            <span className="avatar" aria-hidden="true">
              {(staff.name || staff.email || "?").trim().charAt(0).toUpperCase()}
            </span>
            <div>
              <strong>{staff.name || staff.email}</strong>
              <span>{USER_ROLE_LABELS[staff.role] || staff.role}</span>
            </div>
          </div>
        ) : null}
      </nav>
    </>
  );
}
