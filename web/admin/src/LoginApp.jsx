import React, { useState } from "./react-shim.js";
import { api, ApiError } from "./lib/apiClient.js";
import { Icon } from "./components/icons.jsx";

function resolveDashboardUrl() {
  return window.location.protocol === "file:" ? "./dashboard.html" : "./dashboard.html";
}

export function LoginApp() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState(null); // { tone: 'error'|'success', text }

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    try {
      await api.post("/auth/login", { email: email.trim(), password });
      setMessage({ tone: "success", text: "Успішний вхід! Перенаправлення…" });
      window.setTimeout(() => {
        window.location.href = resolveDashboardUrl();
      }, 600);
    } catch (err) {
      const text =
        err instanceof ApiError && err.status === 429
          ? "Забагато спроб входу. Спробуйте пізніше."
          : err.message || "Помилка входу";
      setMessage({ tone: "error", text });
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page" data-testid="login-page">
      <div className="login-card">
        <div className="login-brand">
          <span className="brand-mark" aria-hidden="true">
            UD
          </span>
          <div>
            <h1>UA-Dim</h1>
            <p>Адмінпанель</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} noValidate data-testid="login-form">
          <label className="form-field">
            <span className="form-label">Email</span>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              data-testid="login-email-input"
            />
          </label>
          <label className="form-field">
            <span className="form-label">Пароль</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              data-testid="login-password-input"
            />
          </label>

          <div
            className={`login-message${message ? ` login-message-${message.tone}` : ""}`}
            role="status"
            aria-live="polite"
            data-testid="login-status"
            data-tone={message?.tone || ""}
          >
            {message?.text || ""}
          </div>

          <button
            type="submit"
            className="btn btn-primary login-submit"
            disabled={submitting}
            data-testid="login-submit-button"
          >
            <Icon name="logout" size={16} className="icon-flip" />
            {submitting ? "Завантаження…" : "Увійти"}
          </button>
        </form>
      </div>
    </div>
  );
}
