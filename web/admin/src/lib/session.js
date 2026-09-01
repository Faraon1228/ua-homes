import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "../react-shim.js";
import { api, onUnauthorized } from "./apiClient.js";

// Mirrors backend/admin_routes.py Permission enum values exactly.
export const PERMISSIONS = {
  ADMIN_ONLY: "admin/all",
  DASHBOARD_READ: "dashboard/read",
  LISTINGS_READ: "listings/read",
  LISTINGS_WRITE: "listings/write",
  LISTINGS_MODERATE: "listings/moderate",
  VERIFICATIONS_MANAGE: "verifications/manage",
  REPORTS_MANAGE: "reports/manage",
  AUDIT_READ: "audit/read",
  USERS_MANAGE: "users/manage",
  LEADS_MANAGE: "leads/manage",
  AGENCIES_MANAGE: "agencies/manage",
  DEVELOPERS_MANAGE: "developers/manage",
  SYSTEM_READ: "system/read",
};

export function hasPermission(staff, permission) {
  if (!staff) return false;
  if (permission === PERMISSIONS.ADMIN_ONLY) return staff.role === "admin";
  return Array.isArray(staff.permissions) && staff.permissions.includes(permission);
}

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [state, setState] = useState({ status: "loading", staff: null, error: null });

  const load = useCallback(async () => {
    setState((prev) => ({ ...prev, status: "loading", error: null }));
    try {
      const data = await api.get("/auth/session");
      setState({ status: "ready", staff: data.staff, error: null });
    } catch (err) {
      if (err && err.status === 401) {
        setState({ status: "unauthenticated", staff: null, error: null });
      } else {
        setState({ status: "error", staff: null, error: err });
      }
    }
  }, []);

  useEffect(() => {
    onUnauthorized(() => {
      setState({ status: "unauthenticated", staff: null, error: null });
    });
    load();
  }, [load]);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout", {});
    } catch {
      // Cookie is cleared server-side even if this request itself races a
      // 401 (e.g. session already expired); treat logout as best-effort.
    }
    setState({ status: "unauthenticated", staff: null, error: null });
  }, []);

  return React.createElement(
    SessionContext.Provider,
    { value: { ...state, reload: load, logout } },
    children,
  );
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
