import React, { useEffect, useRef, useState } from "../../react-shim.js";
import { useModalFocus } from "../../lib/modalFocus.js";

const ACTION_LABELS = {
  approve: "Схвалити",
  reject: "Відхилити",
  hold: "Призупинити",
  review: "На розгляд",
  changes_requested: "Запросити правки",
};

/**
 * Shared moderation-action confirmation dialog (single listing or bulk),
 * collecting an optional/required reason before calling the moderate
 * endpoint. Reuses the same focus-trap/Escape pattern as ConfirmDialog.
 */
export function ModerationActionDialog({ open, action, count = 1, onConfirm, onCancel, busy }) {
  const [reason, setReason] = useState("");
  const textareaRef = useRef(null);
  const requiresReason = action === "reject" || action === "changes_requested";
  const dialogRef = useModalFocus(open, busy ? () => {} : onCancel, "textarea");

  useEffect(() => {
    if (open) {
      setReason("");
      setTimeout(() => textareaRef.current?.focus(), 0);
    }
  }, [open, action]);

  if (!open) return null;

  return (
    <div className="drawer-overlay" onMouseDown={(e) => e.target === e.currentTarget && !busy && onCancel()}>
      <div
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`${ACTION_LABELS[action] || action} (${count})`}
        ref={dialogRef}
        tabIndex={-1}
        data-testid="moderation-action-dialog"
        data-action={action}
      >
        <h2 className="confirm-dialog-title">
          {ACTION_LABELS[action] || action}
          {count > 1 ? ` — ${count} оголошень` : ""}
        </h2>
        <label className="form-field">
          <span className="form-label">
            Причина {requiresReason ? "(обов'язково)" : "(необов'язково)"}
          </span>
          <textarea
            ref={textareaRef}
            rows={3}
            maxLength={1000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            data-testid="moderation-action-reason"
          />
        </label>
        <div className="confirm-dialog-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onCancel}
            disabled={busy}
            data-testid="moderation-action-cancel"
          >
            Скасувати
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || (requiresReason && !reason.trim())}
            onClick={() => onConfirm(reason.trim())}
            data-testid="moderation-action-confirm"
          >
            {busy ? "Виконання…" : "Підтвердити"}
          </button>
        </div>
      </div>
    </div>
  );
}
