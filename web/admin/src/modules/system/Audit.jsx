import React, { useMemo, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync } from "../../lib/hooks.js";
import { PageHeader, Card, Tabs, TabPanel } from "../../components/Layout.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { Skeleton, ErrorState, EmptyState, Pagination } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { formatDate } from "../../lib/format.js";

const PAGE_SIZE = 20;
const TABS = [
  { id: "actions", label: "Дії адміністраторів" },
  { id: "moderation", label: "Історія модерації" },
];

export function Audit() {
  const [tab, setTab] = useState("actions");
  return (
    <div className="page">
      <PageHeader title="Аудит" description="Журнал дій персоналу та історія рішень модерації." />
      <Tabs idBase="audit" tabs={TABS} activeId={tab} onChange={setTab} />
      <TabPanel id="actions" idBase="audit" active={tab === "actions"}>
        <AdminAuditLog />
      </TabPanel>
      <TabPanel id="moderation" idBase="audit" active={tab === "moderation"}>
        <ModerationLog />
      </TabPanel>
    </div>
  );
}

function AdminAuditLog() {
  const [offset, setOffset] = useState(0);
  const { status, data, error, reload } = useAsync((signal) => api.get("/audit", { limit: PAGE_SIZE, offset }, signal), [offset]);
  const rows = data?.audit || [];
  const total = data?.total || 0;

  const columns = useMemo(
    () => [
      { key: "actor_name", header: "Персонал", render: (row) => row.actor_name || `#${row.actor_id}` },
      { key: "action", header: "Дія" },
      { key: "resource_type", header: "Ресурс", render: (row) => `${row.resource_type}${row.resource_id ? ` #${row.resource_id}` : ""}` },
      { key: "created_at", header: "Час", render: (row) => formatDate(row.created_at) },
    ],
    [],
  );

  return (
    <Card
      actions={
        <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити журнал">
          <Icon name="refresh" size={16} />
        </button>
      }
    >
      {status === "loading" ? <Skeleton rows={5} label="Завантаження журналу дій" /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
      {status === "success" && rows.length === 0 ? <EmptyState icon="list" title="Записів немає" /> : null}
      {status === "success" && rows.length > 0 ? (
        <>
          <DataTable columns={columns} rows={rows} getRowId={(row) => row.id} caption="Журнал дій адміністраторів" />
          <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </>
      ) : null}
    </Card>
  );
}

function ModerationLog() {
  const [offset, setOffset] = useState(0);
  const { status, data, error, reload } = useAsync((signal) => api.get("/moderation/logs", { limit: PAGE_SIZE, offset }, signal), [offset]);
  const rows = data?.logs || [];
  const total = data?.total || 0;

  const columns = useMemo(
    () => [
      { key: "title", header: "Оголошення" },
      { key: "action", header: "Дія" },
      { key: "reason", header: "Причина", render: (row) => row.reason || "—" },
      { key: "admin_name", header: "Персонал", render: (row) => row.admin_name || "—" },
      { key: "created_at", header: "Час", render: (row) => formatDate(row.created_at) },
    ],
    [],
  );

  return (
    <Card
      actions={
        <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити історію модерації">
          <Icon name="refresh" size={16} />
        </button>
      }
    >
      {status === "loading" ? <Skeleton rows={5} label="Завантаження історії модерації" /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
      {status === "success" && rows.length === 0 ? <EmptyState icon="shield" title="Записів немає" /> : null}
      {status === "success" && rows.length > 0 ? (
        <>
          <DataTable columns={columns} rows={rows} getRowId={(row) => row.id} caption="Історія модерації" />
          <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </>
      ) : null}
    </Card>
  );
}
