import React, {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
} from "../react-shim.js";
import { Icon } from "./icons.jsx";

const ToastContext = createContext(null);
let idSeed = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (message, { tone = "info", duration = 5000 } = {}) => {
      const id = ++idSeed;
      setToasts((prev) => [...prev, { id, message, tone }]);
      if (duration > 0) {
        const timer = setTimeout(() => dismiss(id), duration);
        timers.current.set(id, timer);
      }
      return id;
    },
    [dismiss],
  );

  const api = {
    show: push,
    success: (message, opts) => push(message, { ...opts, tone: "success" }),
    error: (message, opts) => push(message, { ...opts, tone: "error", duration: opts?.duration ?? 8000 }),
    info: (message, opts) => push(message, { ...opts, tone: "info" }),
    dismiss,
  };

  return React.createElement(
    ToastContext.Provider,
    { value: api },
    children,
    React.createElement(
      "div",
      { className: "toast-region", role: "region", "aria-label": "Сповіщення" },
      React.createElement(
        "ol",
        { className: "toast-list", "aria-live": "polite", "aria-atomic": "false" },
        toasts.map((toast) =>
          React.createElement(
            "li",
            { key: toast.id, className: `toast toast-${toast.tone}`, role: "status" },
            React.createElement(Icon, {
              name: toast.tone === "success" ? "check" : toast.tone === "error" ? "alert" : "bell",
              size: 16,
            }),
            React.createElement("span", { className: "toast-message" }, toast.message),
            React.createElement(
              "button",
              {
                type: "button",
                className: "toast-close",
                "aria-label": "Закрити сповіщення",
                onClick: () => dismiss(toast.id),
              },
              React.createElement(Icon, { name: "close", size: 14 }),
            ),
          ),
        ),
      ),
    ),
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
