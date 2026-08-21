import React, { useEffect, useMemo, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync, useDebouncedValue } from "../../lib/hooks.js";
import { Card } from "../../components/Layout.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { Skeleton, ErrorState, EmptyState, Pagination, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { useToast } from "../../components/Toast.jsx";
import { formatDate, formatPrice, MODERATION_STATUS_LABELS } from "../../lib/format.js";
import { ModerationActionDialog } from "./ModerationActionDialog.jsx";
import { ListingDetailDrawer } from "../listings/ListingDetailDrawer.jsx";

const PAGE_SIZE = 20;

export function ModerationListings({ staff }) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState(new Set());
  const [pendingAction, setPendingAction] = useState(null); // { action, ids }
  const [busy, setBusy] = useState(false);
  const [drawerListingId, setDrawerListingId] = useState(null);
  const debouncedSearch = useDebouncedValue(search, 300);
  const toast = useToast();

  useEffect(() => {
    setOffset(0);
    setSelected(new Set());
  }, [debouncedSearch]);

  useEffect(() => {
    setSelected(new Set());
  }, [offset]);

  const { status, data, error, reload } = useAsync(
    (signal) => api.get("/moderation/queue", { search: debouncedSearch || undefined, limit: PAGE_SIZE, offset }, signal),
    [debouncedSearch, offset],
  );
  const rows = data?.queue || [];
  const total = data?.total || 0;

  function toggleRow(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function toggleAll(shouldSelect) {
    setSelected(shouldSelect ? new Set(rows.map((r) => r.id)) : new Set());
  }

  async function handleConfirmAction(reason) {
    if (!pendingAction) return;
    setBusy(true);
    try {
      if (pendingAction.ids.length === 1) {
        await api.post(`/listings/${pendingAction.ids[0]}/moderate`, { action: pendingAction.action, reason: reason || undefined });
      } else {
        await api.post("/listings/bulk-moderate", {
          listing_ids: pendingAction.ids,
          action: pendingAction.action,
          reason: reason || undefined,
        });
      }
      toast.success("Дію застосовано");
      setSelected(new Set());
      setPendingAction(null);
      reload();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  const columns = useMemo(
    () => [
      {
        key: "title",
        header: "Оголошення",
        render: (row) => (
          <button type="button" className="link-button" onClick={() => setDrawerListingId(row.id)}>
            {row.title}
          </button>
        ),
      },
      { key: "location", header: "Локація", render: (row) => `${row.city}, ${row.district}` },
      { key: "price", header: "Ціна", render: (row) => formatPrice(row.price) },
      {
        key: "moderation_status",
        header: "Статус",
        render: (row) => (
          <StatusBadge tone="amber">{MODERATION_STATUS_LABELS[row.moderation_status] || row.status}</StatusBadge>
        ),
      },
      { key: "created_at", header: "Створено", render: (row) => formatDate(row.created_at) },
    ],
    [],
  );

  return (
    <Card testId="moderation-queue">
      <div className="table-toolbar">
        <label className="table-search">
          <Icon name="search" size={15} />
          <input
            type="search"
            placeholder="Пошук за назвою, містом…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Пошук у черзі модерації"
            data-testid="moderation-search-input"
          />
        </label>
        {selected.size > 0 ? (
          <div className="row-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPendingAction({ action: "approve", ids: Array.from(selected) })}
              data-testid="moderation-bulk-approve"
            >
              Схвалити ({selected.size})
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => setPendingAction({ action: "reject", ids: Array.from(selected) })}
              data-testid="moderation-bulk-reject"
            >
              Відхилити ({selected.size})
            </button>
          </div>
        ) : null}
        <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити чергу" data-testid="moderation-refresh">
          <Icon name="refresh" size={16} />
        </button>
      </div>

      {status === "loading" ? (
        <Skeleton rows={5} label="Завантаження черги модерації" testId="moderation-queue-loading" />
      ) : null}
      {status === "error" ? (
        <ErrorState message={error?.message} onRetry={reload} testId="moderation-queue-error" />
      ) : null}
      {status === "success" && rows.length === 0 ? (
        <EmptyState
          icon="shield"
          title="Черга порожня"
          description="Немає оголошень, що очікують модерації."
          testId="moderation-queue-empty"
        />
      ) : null}
      {status === "success" && rows.length > 0 ? (
        <>
          <DataTable
            columns={columns}
            rows={rows}
            getRowId={(row) => row.id}
            selectable
            selectedIds={selected}
            onToggleRow={toggleRow}
            onToggleAll={toggleAll}
            caption="Черга модерації оголошень"
            testId="moderation-queue-table"
            renderActions={(row) => (
              <div className="row-actions">
                <button
                  type="button"
                  className="btn btn-icon"
                  onClick={() => setPendingAction({ action: "approve", ids: [row.id] })}
                  aria-label="Схвалити"
                  data-testid={`moderation-approve-${row.id}`}
                >
                  <Icon name="check" size={15} />
                </button>
                <button
                  type="button"
                  className="btn btn-icon btn-icon-danger"
                  onClick={() => setPendingAction({ action: "reject", ids: [row.id] })}
                  aria-label="Відхилити"
                  data-testid={`moderation-reject-${row.id}`}
                >
                  <Icon name="close" size={15} />
                </button>
                <button
                  type="button"
                  className="btn btn-icon"
                  onClick={() => setPendingAction({ action: "changes_requested", ids: [row.id] })}
                  aria-label="Запросити правки"
                  data-testid={`moderation-changes-${row.id}`}
                >
                  <Icon name="edit" size={15} />
                </button>
              </div>
            )}
          />
          <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} testId="moderation-queue-pagination" />
        </>
      ) : null}

      <ModerationActionDialog
        open={!!pendingAction}
        action={pendingAction?.action}
        count={pendingAction?.ids.length}
        busy={busy}
        onConfirm={handleConfirmAction}
        onCancel={() => setPendingAction(null)}
      />

      <ListingDetailDrawer
        listingId={drawerListingId}
        open={drawerListingId != null}
        onClose={() => setDrawerListingId(null)}
        onChanged={reload}
        staff={staff}
      />
    </Card>
  );
}
