import { apiRequest } from "./apiClient.js";

const TOKEN_KEY = "uaDim.authToken";
const USER_KEY = "uaDim.currentUser";

let lastToken;
let pending;
let waiter;
let released;

const isNative = () => Boolean(window.UaDimAuth?.postMessage);
const isReady = () => !isNative() || released || window.__uaDimAuthReady;

// A handshake-capable shell registers the UaDimAuthHandshake channel at document start, restores
// its secure token on cold start and then fires "uadim-auth-ready". Until then web auth state may
// be stale, so nothing is validated or sent to native, however slow the restore is. Only legacy
// shells without the channel are released by the timeout and keep the previous behaviour.
export function whenAuthReady() {
  if (isReady()) return Promise.resolve();
  waiter ??= new Promise((resolve) => {
    const done = () => {
      if (released) return;
      released = true;
      window.removeEventListener("uadim-auth-ready", done);
      if (pending) persistAuthSession(...pending);
      resolve();
    };
    if (!window.UaDimAuthHandshake) setTimeout(done, 3000);
    window.addEventListener("uadim-auth-ready", done);
  });
  return waiter;
}

export function persistAuthSession(token, user) {
  if (typeof window === "undefined") return;
  if (!isReady()) {
    pending = [token, user];
    whenAuthReady();
    return;
  }
  const native = isNative();
  const previous = lastToken;
  lastToken = token;
  if (native) {
    if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
    else window.sessionStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(TOKEN_KEY);
    // Must match the Flutter auth bridge envelope (version 1); other shapes are ignored natively.
    if (previous !== token) window.UaDimAuth.postMessage(JSON.stringify({ version: 1, type: "auth", token: token || null }));
  } else if (token) {
    window.localStorage.setItem(TOKEN_KEY, token);
  } else {
    window.localStorage.removeItem(TOKEN_KEY);
  }
  if (user) window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  else window.localStorage.removeItem(USER_KEY);
}

// A late 401 must only clear the session it was issued for, judged by the live storage as well.
export function clearAuthSessionCache(requestToken) {
  const stored = window.sessionStorage.getItem(TOKEN_KEY) || window.localStorage.getItem(TOKEN_KEY);
  if (requestToken !== lastToken || (stored && stored !== requestToken)) return false;
  window.sessionStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  return true;
}

export function fetchCurrentUser(token, onUnauthorized) {
  return apiRequest("/auth/me", {
    token,
    onUnauthorized,
    errorMessage: "Не вдалося оновити профіль",
  });
}

export function submitAuth(mode, form) {
  return apiRequest(mode === "login" ? "/auth/login" : "/auth/register", {
    method: "POST",
    body:
      mode === "login"
        ? { email: form.email.trim(), password: form.password }
        : {
            name: form.name.trim(),
            email: form.email.trim(),
            password: form.password,
            accountType: form.accountType,
          },
    errorMessage: "Не вдалося виконати дію",
  });
}

export function requestPasswordReset(email) {
  return apiRequest("/auth/forgot-password", {
    method: "POST",
    body: { email: email.trim() },
    errorMessage: "Не вдалося надіслати запит. Спробуйте ще раз.",
  });
}

export function resetPassword(token, password) {
  return apiRequest("/auth/reset-password", {
    method: "POST",
    body: { token, password },
    errorMessage: "Не вдалося скинути пароль.",
  });
}
