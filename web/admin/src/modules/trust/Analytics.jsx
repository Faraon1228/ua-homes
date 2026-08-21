import React, { useMemo, useState } from "../../react-shim.js";
import { api, downloadFile } from "../../lib/apiClient.js";
import { useAsync } from "../../lib/hooks.js";
import { PageHeader, Card, Tabs, TabPanel } from "../../components/Layout.jsx";
import { Skeleton, ErrorState, EmptyState } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { formatDate, formatNumber, formatPercent, formatPrice } from "../../lib/format.js";

const TABS = [
  { id: "cities", label: "Міста" },
  { id: "growth", label: "Користувачі" },
  { id: "observability", label: "Спостережуваність" },
  { id: "leads", label: "Лід-воронка" },
];

export function Analytics() {
  const [tab, setTab] = useState("cities");
  return (
    <div className="page">
      <PageHeader title="Аналітика" description="Звіти платформи: міста, зростання користувачів, помилки клієнта, лід-воронка." />
      <Tabs idBase="analytics" tabs={TABS} activeId={tab} onChange={setTab} />
      <TabPanel id="cities" idBase="analytics" active={tab === "cities"}>
        <CitiesReport />
      </TabPanel>
      <TabPanel id="growth" idBase="analytics" active={tab === "growth"}>
        <GrowthReport />
      </TabPanel>
      <TabPanel id="observability" idBase="analytics" active={tab === "observability"}>
        <ObservabilityReport />
      </TabPanel>
      <TabPanel id="leads" idBase="analytics" active={tab === "leads"}>
        <LeadFunnelReport />
      </TabPanel>
    </div>
  );
}

function BarRow({ label, value, max, formatValue }) {
  const pct = max > 0 ? Math.max(4, Math.round((value / max) * 100)) : 0;
  return (
    <li className="bar-row">
      <span className="bar-label">{label}</span>
      <span className="bar-track">
        <span className="bar-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="bar-value">{formatValue ? formatValue(value) : formatNumber(value)}</span>
    </li>
  );
}

function CitiesReport() {
  const { status, data, error, reload } = useAsync((signal) => api.get("/reports/listings-by-city", undefined, signal), []);
  const rows = data?.data || [];
  const max = Math.max(1, ...rows.map((r) => r.count || 0));
  return (
    <Card title="Оголошення за містом" description="Кількість опублікованих оголошень і середня ціна">
      {status === "loading" ? <Skeleton rows={4} /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
      {status === "success" && rows.length === 0 ? <EmptyState icon="chart" title="Немає даних" /> : null}
      {status === "success" && rows.length > 0 ? (
        <ul className="bar-list">
          {rows.map((row) => (
            <BarRow key={row.city} label={`${row.city} · ${formatPrice(row.avg_price)}`} value={row.count} max={max} />
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

function GrowthReport() {
  const { status, data, error, reload } = useAsync((signal) => api.get("/reports/user-growth", undefined, signal), []);
  const rows = data?.data || [];
  const max = Math.max(1, ...rows.map((r) => r.count || 0));
  return (
    <Card title="Зростання користувачів" description="Нові реєстрації за останні 30 днів">
      {status === "loading" ? <Skeleton rows={4} /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
      {status === "success" && rows.length === 0 ? <EmptyState icon="users" title="Немає даних" /> : null}
      {status === "success" && rows.length > 0 ? (
        <ul className="bar-list">
          {rows.map((row) => (
            <BarRow key={row.date} label={formatDate(row.date)} value={row.count} max={max} />
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

function ObservabilityReport() {
  const [hours, setHours] = useState(24);
  const { status, data, error, reload } = useAsync((signal) => api.get("/reports/observability", { hours }, signal), [hours]);

  const errorColumns = useMemo(
    () => [
      { key: "event_type", header: "Тип" },
      { key: "message", header: "Повідомлення" },
      { key: "source", header: "Джерело" },
      { key: "created_at", header: "Час", render: (row) => formatDate(row.created_at) },
    ],
    [],
  );
  const vitalsColumns = useMemo(
    () => [
      { key: "metric_name", header: "Метрика" },
      { key: "samples", header: "Зразків" },
      { key: "avg_value", header: "Середнє", render: (row) => Number(row.avg_value).toFixed(1) },
      { key: "good_count", header: "Добре" },
      { key: "needs_improvement_count", header: "Потребує уваги" },
      { key: "poor_count", header: "Погано" },
    ],
    [],
  );

  return (
    <Card
      title="Спостережуваність клієнта"
      description="Помилки виконання та Web Vitals за вибране вікно"
      actions={
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Вікно часу">
          {[6, 24, 48, 168].map((value) => (
            <option key={value} value={value}>
              {value} год
            </option>
          ))}
        </select>
      }
    >
      {status === "loading" ? <Skeleton rows={4} /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
      {status === "success" && data ? (
        <>
          <div className="stats-grid stats-grid-compact">
            <div className="mini-stat">
              <span>Подій</span>
              <strong>{formatNumber(data.summary?.events_total ?? 0)}</strong>
            </div>
            <div className="mini-stat">
              <span>Помилки виконання</span>
              <strong>{formatNumber(data.summary?.runtime_error ?? 0)}</strong>
            </div>
            <div className="mini-stat">
              <span>Необроблені відхилення</span>
              <strong>{formatNumber(data.summary?.unhandled_rejection ?? 0)}</strong>
            </div>
            <div className="mini-stat">
              <span>Web Vitals</span>
              <strong>{formatNumber(data.summary?.web_vital ?? 0)}</strong>
            </div>
          </div>
          <h4 className="subsection-title">Останні помилки</h4>
          {data.recent_errors?.length ? (
            <DataTable columns={errorColumns} rows={data.recent_errors} getRowId={(row) => row.id} caption="Останні помилки" />
          ) : (
            <p className="empty-inline">Помилок не зафіксовано.</p>
          )}
          <h4 className="subsection-title">Web Vitals за метрикою</h4>
          {data.vitals_by_metric?.length ? (
            <DataTable columns={vitalsColumns} rows={data.vitals_by_metric} getRowId={(row) => row.metric_name} caption="Web Vitals" />
          ) : (
            <p className="empty-inline">Даних Web Vitals немає.</p>
          )}
        </>
      ) : null}
    </Card>
  );
}

function LeadFunnelReport() {
  const [days, setDays] = useState(30);
  const { status, data, error, reload } = useAsync((signal) => api.get("/reports/lead-funnel", { days }, signal), [days]);

  const sourceColumns = useMemo(
    () => [
      { key: "source", header: "Джерело" },
      { key: "views", header: "Перегляди" },
      { key: "intents", header: "Наміри" },
      { key: "submits", header: "Заявки" },
      { key: "ctr_intent_to_submit", header: "CTR", render: (row) => formatPercent(row.ctr_intent_to_submit) },
    ],
    [],
  );
  const topColumns = useMemo(
    () => [
      { key: "title", header: "Оголошення" },
      { key: "views", header: "Перегляди" },
      { key: "intents", header: "Наміри" },
      { key: "submits", header: "Заявки" },
    ],
    [],
  );

  return (
    <Card
      title="Лід-воронка"
      description="Наміри → заявки за обране вікно"
      actions={
        <div className="row-actions">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Період">
            {[7, 30, 90].map((value) => (
              <option key={value} value={value}>
                {value} днів
              </option>
            ))}
          </select>
          <button type="button" className="btn btn-secondary" onClick={() => downloadFile("/reports/lead-funnel/export.csv", { days })}>
            <Icon name="download" size={15} />
            Експорт CSV
          </button>
        </div>
      }
    >
      {status === "loading" ? <Skeleton rows={4} /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
      {status === "success" && data ? (
        <>
          <div className="stats-grid stats-grid-compact">
            <div className="mini-stat">
              <span>Перегляди</span>
              <strong>{formatNumber(data.totals?.views ?? 0)}</strong>
            </div>
            <div className="mini-stat">
              <span>Наміри</span>
              <strong>{formatNumber(data.totals?.intents ?? 0)}</strong>
            </div>
            <div className="mini-stat">
              <span>Заявки</span>
              <strong>{formatNumber(data.totals?.submits ?? 0)}</strong>
            </div>
            <div className="mini-stat">
              <span>CTR намір → заявка</span>
              <strong>{formatPercent(data.totals?.ctr_intent_to_submit ?? 0)}</strong>
            </div>
          </div>
          <h4 className="subsection-title">За джерелом</h4>
          {data.by_source?.length ? (
            <DataTable columns={sourceColumns} rows={data.by_source} getRowId={(row) => row.source} caption="За джерелом" />
          ) : (
            <p className="empty-inline">Немає даних за джерелом.</p>
          )}
          <h4 className="subsection-title">Топ оголошень</h4>
          {data.top_listings?.length ? (
            <DataTable columns={topColumns} rows={data.top_listings} getRowId={(row) => row.listing_id} caption="Топ оголошень" />
          ) : (
            <p className="empty-inline">Недостатньо даних для рейтингу.</p>
          )}
        </>
      ) : null}
    </Card>
  );
}
