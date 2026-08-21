import React from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync } from "../../lib/hooks.js";
import { PageHeader, Card } from "../../components/Layout.jsx";
import { Skeleton, ErrorState, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { formatNumber } from "../../lib/format.js";

export function Health() {
  const { status, data, error, reload } = useAsync((signal) => api.get("/system/health", undefined, signal), []);

  return (
    <div className="page">
      <PageHeader title="Стан системи" description="Перевірка з'єднання з базою даних та ключові лічильники." />
      <Card
        actions={
          <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити стан системи">
            <Icon name="refresh" size={16} />
          </button>
        }
      >
        {status === "loading" ? <Skeleton rows={3} label="Перевірка стану системи" /> : null}
        {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
        {status === "success" && data ? (
          <>
            <div className="health-row">
              <StatusBadge tone={data.status === "ok" ? "green" : "red"}>{data.status === "ok" ? "Система в нормі" : "Збій"}</StatusBadge>
              <StatusBadge tone={data.database === "ok" ? "green" : "red"}>
                База даних: {data.database === "ok" ? "доступна" : "недоступна"}
              </StatusBadge>
            </div>
            <div className="stats-grid stats-grid-compact">
              <div className="mini-stat">
                <span>Користувачів</span>
                <strong>{formatNumber(data.counts?.users ?? 0)}</strong>
              </div>
              <div className="mini-stat">
                <span>Оголошень</span>
                <strong>{formatNumber(data.counts?.listings ?? 0)}</strong>
              </div>
              <div className="mini-stat">
                <span>Скарг очікує</span>
                <strong>{formatNumber(data.counts?.pending_reports ?? 0)}</strong>
              </div>
            </div>
            {data.request_id ? <p className="table-toolbar-hint">Request ID: {data.request_id}</p> : null}
          </>
        ) : null}
      </Card>
    </div>
  );
}
