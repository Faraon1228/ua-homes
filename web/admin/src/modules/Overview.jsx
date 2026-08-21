import React, { useState } from "../react-shim.js";
import { api } from "../lib/apiClient.js";
import { useAsync } from "../lib/hooks.js";
import { formatDate, formatNumber, formatPrice } from "../lib/format.js";
import { PageHeader, StatCard, Card } from "../components/Layout.jsx";
import { Skeleton, ErrorState, EmptyState } from "../components/States.jsx";

const PERIODS = [
  { id: "7d", label: "7 днів" },
  { id: "30d", label: "30 днів" },
  { id: "90d", label: "90 днів" },
];

export function Overview({ onNavigate }) {
  const [period, setPeriod] = useState("30d");
  const { status, data, error, reload } = useAsync(
    (signal) => api.get("/dashboard/stats", { period }, signal),
    [period],
  );

  return (
    <div className="page">
      <PageHeader
        title="Огляд"
        description="Ключові показники платформи та черга роботи."
        actions={
          <div className="period-switch" role="group" aria-label="Період">
            {PERIODS.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`period-button${period === p.id ? " active" : ""}`}
                aria-pressed={period === p.id}
                onClick={() => setPeriod(p.id)}
              >
                {p.label}
              </button>
            ))}
          </div>
        }
      />

      {status === "loading" ? <Skeleton rows={4} label="Завантаження огляду" /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}

      {status === "success" && data ? (
        <>
          <div className="stats-grid">
            <StatCard icon="home" label="Усього оголошень" value={formatNumber(data.total_listings)} />
            <StatCard icon="check" label="Опубліковано" tone="green" value={formatNumber(data.published_listings)} />
            <StatCard icon="users" label="Користувачів" tone="amber" value={formatNumber(data.total_users)} />
            <StatCard icon="star" label="Середня ціна" tone="blue" value={formatPrice(data.avg_price)} />
          </div>

          <div className="workspace">
            <Card title="Черга роботи" description="Позиції, що потребують уваги персоналу">
              <ul className="backlog-list">
                <li>
                  <button type="button" className="backlog-item" onClick={() => onNavigate("moderation")}>
                    <span>Модерація оголошень</span>
                    <span className="badge badge-amber">{formatNumber(data.backlog?.moderation ?? 0)}</span>
                  </button>
                </li>
                <li>
                  <button type="button" className="backlog-item" onClick={() => onNavigate("moderation")}>
                    <span>Верифікації</span>
                    <span className="badge badge-blue">{formatNumber(data.backlog?.verifications ?? 0)}</span>
                  </button>
                </li>
                <li>
                  <button type="button" className="backlog-item" onClick={() => onNavigate("moderation")}>
                    <span>Скарги на оголошення</span>
                    <span className="badge badge-red">{formatNumber(data.backlog?.reports ?? 0)}</span>
                  </button>
                </li>
              </ul>
            </Card>

            <Card title="Оголошення за містом" description="Топ-5 міст за кількістю публікацій">
              {data.by_city?.length ? (
                <ul className="city-list">
                  {data.by_city.map((row) => (
                    <li key={row.city} className="city-row">
                      <span>{row.city}</span>
                      <span className="badge badge-neutral">{formatNumber(row.count)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState icon="chart" title="Немає даних" description="Опубліковані оголошення ще не з'явились." />
              )}
            </Card>
          </div>

          <Card title="Останні оголошення" description="5 щойно доданих оголошень">
            {data.recent_listings?.length ? (
              <ul className="recent-list">
                {data.recent_listings.map((listing) => (
                  <li key={listing.id} className="recent-row">
                    <div>
                      <p className="recent-title">{listing.title}</p>
                      <p className="recent-meta">
                        {listing.city} · {formatPrice(listing.price)} · {formatDate(listing.created_at)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon="home" title="Оголошень ще немає" />
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}
