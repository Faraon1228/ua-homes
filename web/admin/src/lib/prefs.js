// Non-sensitive UI preference persistence (sidebar collapse state, last
// active tab, page size). Never store tokens/session data here.
const PREFIX = "ua_dim_admin_pref:";

export function getPref(key, fallback) {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (raw === null) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function setPref(key, value) {
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // Ignore quota/availability errors — preferences are best-effort only.
  }
}
