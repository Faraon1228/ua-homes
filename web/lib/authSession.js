import { apiRequest } from "./apiClient.js";

const TOKEN_KEY = "uaDim.authToken";
const USER_KEY = "uaDim.currentUser";

export function persistAuthSession(token, user) {
  if (typeof window === "undefined") return;
  if (window.UaDimAuth?.postMessage) {
    if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
    else window.sessionStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(TOKEN_KEY);
    window.UaDimAuth.postMessage(JSON.stringify({ type: "auth", token: token || null }));
  } else if (token) {
    window.localStorage.setItem(TOKEN_KEY, token);
  } else {
    window.localStorage.removeItem(TOKEN_KEY);
  }
  if (user) window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  else window.localStorage.removeItem(USER_KEY);
}

export function clearAuthSessionCache() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
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
