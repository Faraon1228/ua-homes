import React, { useMemo, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync } from "../../lib/hooks.js";
import { Card } from "../../components/Layout.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { Skeleton, ErrorState, EmptyState, Pagination, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { useToast } from "../../components/Toast.jsx";
import { formatDate, REPORT_STATUS_LABELS } from "../../lib/format.js";
import { ListingDetailDrawer } from "../listings/ListingDetailDrawer.jsx";

const PAGE_SIZE = 20;
const STATUS_TONE = { pending: "amber", reviewing: "blue", resolved: "green", dismissed: "neutral" };
const NEXT_STATUS = {
  pending: [
    { value: "reviewing", label: "На розгляд" },
    { value: "dismissed", label: "Відхилити" },
  ],
  reviewing: [
    { value: "resolved", label: "Вирішено" },
    { value: "dismissed", label: "Відхилити" },
  ],
};

export function ListingReports({ staff }) {
  const [offset, setOffset] = useState(0);
  const [busyId, setBusyId] = useState(null);
  const [drawerListingId, setDrawerListingId] = useState(null);
  const toast = useToast();

  const { status, data, error, reload } = useAsync(
    (signal) => api.get("/reports/listings", { limit: PAGE_SIZE, offset }, signal),
    [offset],
  );
  const rows = data?.reports || [];
  const total = data?.total || 0;

  async function updateStatus(reportId, nextStatus) {
    setBusyId(reportId);
    try {
      await api.patch(`/reports/listings/${reportId}`, { status: nextStatus });
      toast.success("Статус скарги оновлено");
      reload();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusyId(null);
    }
  }

  const columns = useMemo(
    () => [
      {
        key: "listing_title",
        header: "Оголошення",
        render: (row) => (
          <button type="button" className="link-button" onClick={() => setDrawerListingId(row.listing_id)}>
            {row.listing_title}
          </button>
        ),
      },
      { key: "reason_code", header: "Причина" },
      { key: "details", header: "Деталі" },
      {
        key: "status",
        header: "Статус",
        render: (row) => <StatusBadge tone={STATUS_TONE[row.status] || "neutral"}>{REPORT_STATUS_LABELS[row.status] || row.status}</StatusBadge>,
      },
      { key: "created_at", header: "Створено", render: (row) => formatDate(row.created_at) },
    ],
    [],
  );

  return (
    <Card>
      <div className="table-toolbar">
        <p className="table-toolbar-hint">Скарги користувачів на оголошення</p>
        <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити">
          <Icon name="refresh" size={16} />
        </button>
      </div>

      {status === "loading" ? <Skeleton rows={5} label="Завантаження скарг" /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
      {status === "success" && rows.length === 0 ? (
        <EmptyState icon="alert" title="Скарг немає" description="Наразі жодних скарг на оголошення не надходило." />
      ) : null}
      {status === "success" && rows.length > 0 ? (
        <>
          <DataTable
            columns={columns}
            rows={rows}
            getRowId={(row) => row.id}
            caption="Скарги на оголошення"
            renderActions={(row) => (
              <div className="row-actions">
                {(NEXT_STATUS[row.status] || []).map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className="btn btn-secondary btn-compact"
                    disabled={busyId === row.id}
                    onClick={() => updateStatus(row.id, option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            )}
          />
          <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </>
      ) : null}

      <ListingDetailDrawer
        listingId={drawerListingId}
        open={drawerListingId != null}
        onClose={() => setDrawerListingId(null)}
        staff={staff}
      />
    </Card>
  );
}
