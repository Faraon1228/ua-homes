import React from "../react-shim.js";
import { useModalFocus } from "../lib/modalFocus.js";

/**
 * Small confirmation modal for destructive/bulk actions (delete, bulk
 * moderate). Shares the same focus-trap/Escape/restore semantics as Drawer
 * but keeps its own compact implementation for a lighter footprint.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Підтвердити",
  tone = "primary",
  onConfirm,
  onCancel,
  busy = false,
  testId = "confirm-dialog",
}) {
  const dialogRef = useModalFocus(
    open,
    busy ? () => {} : onCancel,
    "button.btn-primary, button.btn-danger",
  );

  if (!open) return null;

  return (
    <div className="drawer-overlay" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div
        className="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        ref={dialogRef}
        tabIndex={-1}
        data-testid={testId}
      >
        <h2 className="confirm-dialog-title">{title}</h2>
        {description ? <p className="confirm-dialog-description">{description}</p> : null}
        <div className="confirm-dialog-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onCancel}
            disabled={busy}
            data-testid={`${testId}-cancel`}
          >
            Скасувати
          </button>
          <button
            type="button"
            className={`btn ${tone === "danger" ? "btn-danger" : "btn-primary"}`}
            onClick={onConfirm}
            disabled={busy}
            data-testid={`${testId}-confirm`}
          >
            {busy ? "Виконання…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
