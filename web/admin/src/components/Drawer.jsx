import React from "../react-shim.js";
import { Icon } from "./icons.jsx";
import { useModalFocus } from "../lib/modalFocus.js";

/**
 * Reusable entity detail drawer/dialog. Handles focus trap + restore, Escape
 * to close, and backdrop dismissal. Used for listing/user/lead/report detail
 * views across the panel so there is a single accessible pattern.
 */
export function Drawer({ open, onClose, title, children, footer, wide = false }) {
  const panelRef = useModalFocus(open, onClose);

  if (!open) return null;

  return (
    <div className="drawer-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`drawer-panel${wide ? " drawer-panel-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={panelRef}
        tabIndex={-1}
      >
        <div className="drawer-header">
          <h2 className="drawer-title">{title}</h2>
          <button type="button" className="btn btn-icon" onClick={onClose} aria-label="Закрити панель">
            <Icon name="close" size={18} />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer ? <div className="drawer-footer">{footer}</div> : null}
      </div>
    </div>
  );
}
