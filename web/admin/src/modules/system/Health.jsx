import React from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync } from "../../lib/hooks.js";
import { PageHeader, Card } from "../../components/Layout.jsx";
import { Skeleton, ErrorState, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";

export function Health() {
  const { status, data, error, reload } = useAsync((signal) => api.get("/system/health", undefined, signal), []);
  const [refreshing, setRefreshing] = React.useState(false);
  const [refreshError, setRefreshError] = React.useState("");
  const [snapshot, setSnapshot] = React.useState(null);
  const health = snapshot || data;
  const refresh = async () => {
    setRefreshing(true);
    setRefreshError("");
    try {
      setSnapshot(await api.post("/system/health/refresh"));
    } catch (err) {
      setRefreshError(err?.message || "Не вдалося оновити стан системи.");
    } finally {
      setRefreshing(false);
    }
  };
  const componentLabel = {
    website: "Сайт", api: "API", database: "База даних", push: "Push-доставка",
  };
  const statusLabel = {
    ok: "У нормі", degraded: "Погіршено", down: "Недоступно",
    unknown: "Невідомо", not_configured: "Не налаштовано",
  };
  const tone = (value) => (value === "ok" ? "green" : value === "down" ? "red" : value === "degraded" ? "amber" : "neutral");

  return (
    <div className="page">
      <PageHeader title="Стан системи" description="Операційний знімок сервісів і production-версій." />
      <Card
        actions={
          <button type="button" className="btn btn-icon" onClick={refresh} disabled={refreshing} aria-label="Оновити стан системи">
            <Icon name="refresh" size={16} />
          </button>
        }
      >
        {status === "loading" ? <Skeleton rows={3} label="Перевірка стану системи" /> : null}
        {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
        {health ? (
          <>
            <div className="health-row" aria-live="polite">
              <StatusBadge tone={tone(health.overall_status)}>{statusLabel[health.overall_status] || "Невідомо"}</StatusBadge>
              <span className="table-toolbar-hint">Знімок: {health.generated_at || "немає даних"}{health.stale ? " (застарілий)" : ""}</span>
            </div>
            {refreshError ? <p className="health-error" role="alert">{refreshError}</p> : null}
            <section aria-labelledby="core-status-heading">
              <h2 id="core-status-heading" className="health-heading">Основні сервіси</h2>
              <div className="health-cards">
                {Object.entries(componentLabel).map(([key, label]) => {
                  const component = health.components?.[key] || {};
                  return <article className="health-card" key={key}>
                    <h3>{label}</h3>
                    <StatusBadge tone={tone(component.status)}>{statusLabel[component.status] || "Невідомо"}</StatusBadge>
                    {component.latency_ms !== undefined ? <p>{component.latency_ms} мс</p> : null}
                    {component.engine ? <p>{component.engine}</p> : null}
                  </article>;
                })}
              </div>
            </section>
            <section className="health-details" aria-labelledby="version-heading">
              <h2 id="version-heading" className="health-heading">Production-версія</h2>
              <p>Backend: <code>{health.production_version?.backend || "невідомо"}</code></p>
              <p>Frontend: <code>{health.production_version?.frontend || "невідомо"}</code></p>
              <StatusBadge tone={tone(health.production_version?.status)}>{statusLabel[health.production_version?.status] || "Невідомо"}</StatusBadge>
            </section>
            <section className="health-details" aria-labelledby="sentry-heading">
              <h2 id="sentry-heading">Sentry</h2>
              <p>Нових критичних проблем: <strong>{health.components?.sentry?.critical_new_count ?? "немає даних"}</strong></p>
              {health.components?.sentry?.open_url ? <a href={health.components.sentry.open_url} target="_blank" rel="noopener noreferrer">Відкрити в Sentry</a> : null}
              <ul className="health-list">
                {(health.components?.sentry?.recent_issues || []).map((issue, index) => <li key={`${issue.url || issue.title}-${index}`}>
                  {issue.url ? <a href={issue.url} target="_blank" rel="noopener noreferrer">{issue.title || issue.type}</a> : (issue.title || issue.type)}
                  <span>{issue.project} · {issue.first_seen}</span>
                </li>)}
              </ul>
            </section>
            <section className="health-details" aria-labelledby="deployments-heading">
              <h2 id="deployments-heading">Невдалі розгортання</h2>
              <ul className="health-list">
                {(health.components?.deployments?.recent_failures || []).map((run, index) => <li key={`${run.url || run.sha}-${index}`}>
                  {run.url ? <a href={run.url} target="_blank" rel="noopener noreferrer">{run.conclusion}</a> : run.conclusion}
                  <span>{run.sha} · {run.created_at}</span>
                </li>)}
                {!health.components?.deployments?.recent_failures?.length ? <li>Немає доступних невдалих розгортань.</li> : null}
              </ul>
            </section>
            <section className="health-details" aria-labelledby="channels-heading">
              <h2 id="channels-heading">Канали інцидентів</h2>
              <p>Email: {health.notification_channels?.email_configured ? "налаштовано" : "не налаштовано"}; Telegram: {health.notification_channels?.telegram_configured ? "налаштовано" : "не налаштовано"}.</p>
            </section>
            <div className="health-row">
              <button type="button" className="btn btn-secondary" onClick={refresh} disabled={refreshing}>
                {refreshing ? "Оновлення…" : "Оновити"}
              </button>
            </div>
          </>
        ) : null}
      </Card>
    </div>
  );
}
