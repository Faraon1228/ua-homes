import React, { useId } from "../react-shim.js";

// React 18's useId is not re-exported by our trimmed shim; fall back to a
// module-scoped counter shared across the admin bundle if unavailable.
let seed = 0;
function useFieldId() {
  if (typeof useId === "function") return useId();
  seed += 1;
  return `field-${seed}`;
}

export function FormField({ label, htmlFor, error, hint, required, children }) {
  const generatedId = useFieldId();
  const id = htmlFor || generatedId;
  const child = React.isValidElement(children)
    ? React.cloneElement(children, {
        id,
        "aria-invalid": error ? "true" : undefined,
        "aria-describedby": error ? `${id}-error` : hint ? `${id}-hint` : undefined,
      })
    : children;
  return (
    <div className={`form-field${error ? " form-field-invalid" : ""}`}>
      <label htmlFor={id} className="form-label">
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </label>
      {child}
      {hint && !error ? (
        <p id={`${id}-hint`} className="form-hint">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
