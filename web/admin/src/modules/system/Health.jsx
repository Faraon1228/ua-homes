import React, { useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync } from "../../lib/hooks.js";
import { PageHeader, Card } from "../../components/Layout.jsx";
import { Skeleton, ErrorState, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { formatDate, formatNumber } from "../../lib/format.js";

const STATUS = {
  ok: ["Працює", "green"],
  degraded: ["Погіршено", "amber"],
  down: ["Недоступно", "red"],
  unknown: ["Невідомо", "neutral"],
  not_configured: ["Не налаштовано", "neutral"],
};

function Badge({ status }) {
  const [label, tone] = STATUS[status] || STATUS.unknown;
  return <StatusBadge tone={tone}>{label}</StatusBadge>;
}

function ServiceCard({ title, value }) {
  return (
    <div className="system-service">
      <span>{title}</span>
      <Badge status={value?.status} />
      {value?.detail ? <small>{value.detail}</small> : null}
    </div>
  );
}

export function Health() {
  const { status, data, error, reload } = useAsync((signal) => api.get("/system/health", undefined, signal), []);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");

  async function refresh() {
    setRefreshing(true);
    setRefreshError("");
    try {
      await api.post("/system/health/refresh");
      reload();
    } catch (err) {
      setRefreshError(err?.message || "Не вдалося оновити стан");
    } finally {
      setRefreshing(false);
    }
  }

  const services = data?.services || {};
  return (
    <div className="page">
      <PageHeader
        title="Стан системи"
        description="Операційний стан production, помилки, розгортання та канали сповіщень."
        actions={
          <button type="button" className="btn btn-primary" onClick={refresh} disabled={refreshing}>
            <Icon name="refresh" size={16} />
            {refreshing ? "Оновлення…" : "Оновити зараз"}
          </button>
        }
      />
      {refreshError ? <p className="form-error" role="alert">{refreshError}</p> : null}
      {status === "loading" ? <Skeleton rows={5} label="Перевірка стану системи" /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
      {status === "success" && data ? (
        <>
          <Card title="Production">
            <div className="health-row">
              <Badge status={data.status} />
              {data.stale ? <StatusBadge tone="amber">Дані застаріли</StatusBadge> : null}
              <span className="table-toolbar-hint">Оновлено: {formatDate(data.refreshed_at)}</span>
            </div>
            <div className="system-service-grid">
              <ServiceCard title="Вебсайт" value={services.website} />
              <ServiceCard title="API" value={services.api} />
              <ServiceCard title="База даних" value={services.database} />
              <ServiceCard title="Push" value={services.push} />
            </div>
          </Card>

          <div className="system-two-column">
            <Card title="Версія">
              <dl className="system-details">
                <div><dt>Release</dt><dd>{data.version?.release || "Невідомо"}</dd></div>
                <div><dt>Production SHA</dt><dd><code>{data.version?.sha?.slice(0, 12) || "Невідомо"}</code></dd></div>
                <div><dt>Останній успішний deploy</dt><dd><code>{data.version?.expected_sha?.slice(0, 12) || "Невідомо"}</code></dd></div>
                <div><dt>Відповідність</dt><dd><Badge status={data.version?.mismatch ? "degraded" : data.version?.sha ? "ok" : "unknown"} /></dd></div>
              </dl>
            </Card>
            <Card title="Сповіщення">
              <div className="system-service-grid">
                <ServiceCard title="Email" value={{ status: data.notifications?.email }} />
                <ServiceCard title="Telegram" value={{ status: data.notifications?.telegram }} />
              </div>
            </Card>
          </div>

          <Card title="Нові критичні помилки Sentry" description="Нерозв’язані error/fatal за останні 24 години. Дані користувачів не відображаються.">
            <div className="health-row">
              <Badge status={data.sentry?.status} />
              <strong>{data.sentry?.new_critical_count == null ? "—" : formatNumber(data.sentry.new_critical_count)}</strong>
            </div>
            {data.sentry?.issues?.length ? (
              <div className="table-wrap">
                <table className="data-table">
                  <caption className="sr-only">Нові критичні помилки Sentry</caption>
                  <thead><tr><th>Помилка</th><th>Рівень</th><th>Подій</th><th>Остання</th><th><span className="sr-only">Дії</span></th></tr></thead>
                  <tbody>{data.sentry.issues.map((issue) => (
                    <tr key={issue.id}>
                      <td><strong>{issue.title}</strong>{issue.culprit ? <small className="system-secondary">{issue.culprit}</small> : null}</td>
                      <td>{issue.level}</td><td>{formatNumber(issue.count)}</td><td>{formatDate(issue.last_seen)}</td>
                      <td>{issue.url ? <a className="btn btn-secondary" href={issue.url} target="_blank" rel="noopener noreferrer">Відкрити в Sentry</a> : "—"}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            ) : <p className="table-toolbar-hint">Нових критичних помилок немає або Sentry не налаштовано.</p>}
          </Card>

          <Card title="Невдалі production deploy">
            <div className="health-row"><Badge status={data.deployments?.status} /></div>
            {data.deployments?.failed_runs?.length ? (
              <ul className="system-run-list">
                {data.deployments.failed_runs.map((run) => (
                  <li key={run.id}>
                    <span><strong>{run.name}</strong><small>{run.conclusion} · {run.sha} · {formatDate(run.created_at)}</small></span>
                    {run.url ? <a href={run.url} target="_blank" rel="noopener noreferrer">Відкрити run</a> : null}
                  </li>
                ))}
              </ul>
            ) : <p className="table-toolbar-hint">Невдалих запусків не знайдено або GitHub не налаштовано.</p>}
          </Card>

          <Card title="Лічильники">
            <div className="stats-grid stats-grid-compact">
              <div className="mini-stat"><span>Користувачів</span><strong>{formatNumber(data.counts?.users ?? 0)}</strong></div>
              <div className="mini-stat"><span>Оголошень</span><strong>{formatNumber(data.counts?.listings ?? 0)}</strong></div>
              <div className="mini-stat"><span>Скарг очікує</span><strong>{formatNumber(data.counts?.pending_reports ?? 0)}</strong></div>
            </div>
            {data.request_id ? <p className="table-toolbar-hint">Request ID: {data.request_id}</p> : null}
          </Card>
        </>
      ) : null}
    </div>
  );
}
