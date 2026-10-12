import React, { useEffect, useRef, useState } from "../react-shim.js";
import { apiRequest } from "../lib/apiClient.js";

export default function DeleteAccountDialog({ authToken, onClose, onDeleted }) {
  const [password, setPassword] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retryable, setRetryable] = useState(false);
  const passwordRef = useRef(null);

  useEffect(() => {
    passwordRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  const submit = async (event) => {
    event.preventDefault();
    if (busy || !confirmed || !password) return;
    setBusy(true);
    setError("");
    setRetryable(false);
    try {
      await apiRequest("/auth/delete-account", {
        method: "POST",
        token: authToken,
        body: { password, confirm: true },
        timeout: 60000,
        errorMessage: "Не вдалося видалити акаунт. Спробуйте ще раз.",
      });
      onDeleted();
    } catch (requestError) {
      setError(requestError.message || "Не вдалося видалити акаунт.");
      setRetryable(Boolean(requestError.payload?.retryable));
      setBusy(false);
    }
  };

  // Rendered on <body> so it stacks above the fixed privacy-consent banner.
  return window.ReactDOM.createPortal(
    <div
      style={{ zIndex: 10000 }}
      className="fixed inset-0 z-[120] flex items-end justify-center bg-slate-950/65 sm:items-center sm:p-6"
      onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}
    >
      <form
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-account-title"
        className="max-h-[92svh] w-full overflow-y-auto rounded-t-[30px] bg-white p-5 shadow-2xl sm:max-w-lg sm:rounded-[30px] sm:p-6"
      >
        <h2 id="delete-account-title" className="text-xl font-black text-slate-900">
          Видалити акаунт
        </h2>
        <p className="mt-2 text-sm text-slate-600">
          Усі ваші оголошення негайно знімуться з публікації, а їхні тексти й фото
          буде видалено разом з акаунтом, обраним, підписками та пристроями. Дію
          не можна скасувати. Докладніше —{" "}
          <a href="/delete-account.html" className="font-bold underline">
            умови видалення
          </a>
          .
        </p>
        <label htmlFor="delete-account-password" className="mt-4 block text-xs font-black uppercase">
          Пароль для підтвердження
        </label>
        <input
          id="delete-account-password"
          ref={passwordRef}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mt-1 min-h-11 w-full rounded-xl border border-slate-300 px-3"
        />
        <label className="mt-4 flex items-start gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            className="mt-1 h-4 w-4"
          />
          <span>Я розумію, що акаунт і оголошення буде видалено безповоротно.</span>
        </label>
        {error ? (
          <p role="alert" className="mt-3 rounded-xl bg-rose-50 p-3 text-sm font-bold text-rose-700">
            {error}
            {retryable ? " Ваші дані ще не видалено повністю — натисніть кнопку ще раз." : ""}
          </p>
        ) : null}
        <div className="mt-5 flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={busy || !confirmed || !password}
            className="inline-flex min-h-11 items-center justify-center rounded-xl bg-rose-600 px-4 text-sm font-black text-white disabled:opacity-50"
          >
            {busy ? "Видаляємо…" : retryable ? "Повторити видалення" : "Видалити назавжди"}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="inline-flex min-h-11 items-center justify-center rounded-xl border border-slate-200 px-4 text-sm font-bold disabled:opacity-50"
          >
            Скасувати
          </button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
