import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "./react-shim.js";
import { SessionProvider, useSession, hasPermission } from "./lib/session.js";
import { ToastProvider, useToast } from "./components/Toast.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { TopBar } from "./components/TopBar.jsx";
import { Skeleton, ErrorState } from "./components/States.jsx";
import { ErrorBoundary } from "./components/ErrorBoundary.jsx";
import { NAV_SECTIONS, DEFAULT_ROUTE, findNavItem } from "./lib/navigation.js";

const LazyOverview = lazy(() => import("./modules/Overview.jsx").then((m) => ({ default: m.Overview })));
const LazyModeration = lazy(() => import("./modules/moderation/Moderation.jsx").then((m) => ({ default: m.Moderation })));
const LazyListings = lazy(() => import("./modules/listings/Listings.jsx").then((m) => ({ default: m.Listings })));
const LazyRequests = lazy(() => import("./modules/requests/Requests.jsx").then((m) => ({ default: m.Requests })));
const LazyUsers = lazy(() => import("./modules/community/Users.jsx").then((m) => ({ default: m.Users })));
const LazyAgencies = lazy(() => import("./modules/community/Agencies.jsx").then((m) => ({ default: m.Agencies })));
const LazyPricesHistory = lazy(() => import("./modules/trust/PricesHistory.jsx").then((m) => ({ default: m.PricesHistory })));
const LazyAnalytics = lazy(() => import("./modules/trust/Analytics.jsx").then((m) => ({ default: m.Analytics })));
const LazyHealth = lazy(() => import("./modules/system/Health.jsx").then((m) => ({ default: m.Health })));
const LazyAudit = lazy(() => import("./modules/system/Audit.jsx").then((m) => ({ default: m.Audit })));

function readRouteFromHash() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  return raw || DEFAULT_ROUTE;
}

function DashboardShell() {
  const { status, staff, error, reload, logout } = useSession();
  const toast = useToast();
  const [route, setRoute] = useState(readRouteFromHash());
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [openListingId, setOpenListingId] = useState(null);
  const [focusUser, setFocusUser] = useState(null);

  useEffect(() => {
    function onHashChange() {
      setRoute(readRouteFromHash());
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = useCallback((routeId) => {
    window.location.hash = `/${routeId}`;
    setRoute(routeId);
    setMobileNavOpen(false);
  }, []);

  const visibleSections = useMemo(
    () =>
      NAV_SECTIONS.map((section) => ({
        ...section,
        items: section.items.filter((item) => hasPermission(staff, item.permission)),
      })).filter((section) => section.items.length > 0),
    [staff],
  );

  useEffect(() => {
    if (status !== "ready") return;
    const currentItem = findNavItem(route);
    if (!currentItem || !hasPermission(staff, currentItem.permission)) {
      const firstAllowed = visibleSections[0]?.items[0]?.id;
      if (firstAllowed && firstAllowed !== route) navigate(firstAllowed);
    }
  }, [status, staff, route, visibleSections, navigate]);

  const handleLogout = useCallback(async () => {
    await logout();
    toast.info("Ви вийшли з системи");
  }, [logout, toast]);

  if (status === "loading") {
    return (
      <div className="auth-gate" role="status" aria-live="polite" data-testid="session-loading">
        <Skeleton rows={3} label="Перевірка сесії" />
      </div>
    );
  }

  if (status === "unauthenticated") {
    window.location.replace("./login.html");
    return null;
  }

  if (status === "error") {
    return (
      <div className="auth-gate" data-testid="session-error">
        <ErrorState message={error?.message || "Не вдалося завантажити сесію"} onRetry={reload} />
      </div>
    );
  }

  const currentItem = findNavItem(route) || findNavItem(DEFAULT_ROUTE);

  return (
    <div className="app-shell" data-testid="app-shell">
      <a href="#main-content" className="skip-link">
        Перейти до основного вмісту
      </a>
      <Sidebar
        sections={visibleSections}
        activeRoute={route}
        onNavigate={navigate}
        staff={staff}
        mobileOpen={mobileNavOpen}
        onCloseMobile={() => setMobileNavOpen(false)}
      />
      <div className="content-column">
        <TopBar
          title={currentItem?.label || "Адмінпанель"}
          staff={staff}
          onOpenMobileNav={() => setMobileNavOpen(true)}
          onLogout={handleLogout}
          onOpenListing={(id) => {
            navigate("listings");
            setOpenListingId(id);
          }}
          onOpenUsers={(user) => {
            navigate("users");
            setFocusUser(user);
          }}
        />
        <main id="main-content" className="main-content" tabIndex={-1} data-testid="main-content" data-active-route={route}>
          <ErrorBoundary resetKey={route}>
            <Suspense fallback={<Skeleton rows={5} label="Завантаження розділу" />}>
              {route === "overview" ? <LazyOverview onNavigate={navigate} /> : null}
              {route === "moderation" ? <LazyModeration staff={staff} /> : null}
              {route === "listings" ? (
                <LazyListings
                  staff={staff}
                  openListingId={openListingId}
                  onConsumeOpenListingId={() => setOpenListingId(null)}
                />
              ) : null}
              {route === "requests" ? <LazyRequests /> : null}
              {route === "users" ? <LazyUsers focusUser={focusUser} onConsumeFocusUser={() => setFocusUser(null)} /> : null}
              {route === "agencies" ? <LazyAgencies /> : null}
              {route === "prices" ? <LazyPricesHistory staff={staff} /> : null}
              {route === "analytics" ? <LazyAnalytics /> : null}
              {route === "health" ? <LazyHealth /> : null}
              {route === "audit" ? <LazyAudit /> : null}
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

export function AdminApp() {
  return (
    <ToastProvider>
      <SessionProvider>
        <DashboardShell />
      </SessionProvider>
    </ToastProvider>
  );
}
