import React from "../react-shim.js";
import { Icon } from "./icons.jsx";

export function PageHeader({ title, description, actions, testId }) {
  return (
    <div className="page-header" data-testid={testId}>
      <div>
        <h2 className="page-title">{title}</h2>
        {description ? <p className="page-description">{description}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </div>
  );
}

export function Card({ title, description, actions, children, className = "", testId }) {
  return (
    <section className={`card ${className}`.trim()} data-testid={testId}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title ? <h3>{title}</h3> : null}
            {description ? <p>{description}</p> : null}
          </div>
          {actions}
        </div>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function StatCard({ icon, label, value, tone = "blue", trend }) {
  return (
    <div className="card stat-card">
      <span className={`stat-icon stat-icon-${tone}`} aria-hidden="true">
        <Icon name={icon} size={19} />
      </span>
      <p className="stat-value">{value}</p>
      <p className="stat-label">{label}</p>
      {trend ? <span className={`stat-trend stat-trend-${trend.tone || "blue"}`}>{trend.label}</span> : null}
    </div>
  );
}

export function Tabs({ tabs, activeId, onChange, idBase }) {
  return (
    <div className="tabs" role="tablist" aria-label="Розділи" data-testid={`${idBase}-tabs`}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`${idBase}-tab-${tab.id}`}
          aria-selected={activeId === tab.id}
          aria-controls={`${idBase}-panel-${tab.id}`}
          className={`tab-button${activeId === tab.id ? " active" : ""}`}
          tabIndex={activeId === tab.id ? 0 : -1}
          onClick={() => onChange(tab.id)}
          data-testid={`${idBase}-tab-${tab.id}`}
        >
          {tab.label}
          {tab.count != null ? <span className="tab-count">{tab.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, idBase, active, children }) {
  if (!active) return null;
  return (
    <div
      id={`${idBase}-panel-${id}`}
      role="tabpanel"
      aria-labelledby={`${idBase}-tab-${id}`}
      tabIndex={0}
      data-testid={`${idBase}-panel-${id}`}
    >
      {children}
    </div>
  );
}
