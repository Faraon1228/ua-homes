import React, { useEffect, useMemo, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync, useDebouncedValue } from "../../lib/hooks.js";
import { PageHeader, Card, Tabs, TabPanel } from "../../components/Layout.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { Skeleton, ErrorState, EmptyState, Pagination, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { ConfirmDialog } from "../../components/ConfirmDialog.jsx";
import { useToast } from "../../components/Toast.jsx";
import { formatDate, formatPrice, LISTING_STATUS_LABELS } from "../../lib/format.js";
import { hasPermission, PERMISSIONS } from "../../lib/session.js";
import { getPref, setPref } from "../../lib/prefs.js";
import { ListingForm } from "./ListingForm.jsx";
import { ListingDetailDrawer } from "./ListingDetailDrawer.jsx";
import { ImportExport } from "./ImportExport.jsx";

const TABS = [
  { id: "all", label: "Усі" },
  { id: "draft", label: "Чернетки" },
  { id: "archived", label: "Архів" },
  { id: "import-export", label: "Імпорт / Експорт" },
];
const PAGE_SIZE = 20;
const STATUS_TONE = { published: "green", draft: "neutral", pending: "amber", rejected: "red", archived: "neutral" };

export function Listings({ staff, openListingId, onConsumeOpenListingId, initialSearch, onConsumeInitialSearch }) {
  const [activeTab, setActiveTabState] = useState(() => getPref("listings.activeTab", "all"));
  function setActiveTab(nextTab) {
    setActiveTabState(nextTab);
    setPref("listings.activeTab", nextTab);
  }
  const [search, setSearch] = useState(initialSearch || "");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState(new Set());
  const [formListingId, setFormListingId] = useState(undefined); // undefined = closed, null = create
  const [drawerListingId, setDrawerListingId] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null); // { ids }
  const [deleting, setDeleting] = useState(false);
  const debouncedSearch = useDebouncedValue(search, 300);
  const toast = useToast();
  const canWrite = hasPermission(staff, PERMISSIONS.LISTINGS_WRITE);

  useEffect(() => {
    if (initialSearch) {
      setActiveTab("all");
      onConsumeInitialSearch?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (openListingId) {
      setDrawerListingId(openListingId);
      onConsumeOpenListingId?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openListingId]);

  useEffect(() => {
    setOffset(0);
    setSelected(new Set());
  }, [debouncedSearch, activeTab]);

  useEffect(() => {
    setSelected(new Set());
  }, [offset]);

  const statusFilter = activeTab === "draft" ? "draft" : activeTab === "archived" ? "archived" : "";

  const { status, data, error, reload } = useAsync(
    (signal) => {
      if (activeTab === "import-export") return Promise.resolve(null);
      return api.get(
        "/listings",
        { search: debouncedSearch || undefined, status: statusFilter || undefined, limit: PAGE_SIZE, offset },
        signal,
      );
    },
    [activeTab, statusFilter, debouncedSearch, offset],
  );

  const rows = data?.listings || [];
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

  async function handleDuplicate(id) {
    try {
      await api.post(`/listings/${id}/duplicate`, {});
      toast.success("Створено копію оголошення");
      reload();
    } catch (err) {
      toast.error(err.message);
    }
  }

  async function handlePublishToggle(listing) {
    const publish = listing.status !== "published";
    try {
      await api.post(`/listings/${listing.id}/publish`, { published: publish });
      toast.success(publish ? "Оголошення опубліковано" : "Оголошення знято з публікації");
      reload();
    } catch (err) {
      toast.error(err.message);
    }
  }

  async function handleConfirmDelete() {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      if (confirmDelete.ids.length === 1) {
        await api.del(`/listings/${confirmDelete.ids[0]}`);
      } else {
        await api.post("/listings/bulk-delete", { listing_ids: confirmDelete.ids });
      }
      toast.success("Видалено");
      setSelected(new Set());
      setConfirmDelete(null);
      reload();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setDeleting(false);
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
      { key: "specs", header: "Кімнати / м²", render: (row) => `${row.rooms} к. · ${row.area} м²` },
      {
        key: "status",
        header: "Статус",
        render: (row) => (
          <StatusBadge tone={STATUS_TONE[row.status] || "neutral"}>
            {LISTING_STATUS_LABELS[row.status] || row.status}
          </StatusBadge>
        ),
      },
      { key: "created_at", header: "Створено", render: (row) => formatDate(row.created_at) },
    ],
    [],
  );

  return (
    <div className="page">
      <PageHeader
        title="Оголошення"
        description="Повний перелік, чернетки, архів та імпорт/експорт CSV."
        actions={
          canWrite && formListingId === undefined ? (
            <button type="button" className="btn btn-primary" onClick={() => setFormListingId(null)}>
              <Icon name="plus" size={15} />
              Створити оголошення
            </button>
          ) : null
        }
      />

      {formListingId !== undefined ? (
        <Card title={formListingId ? "Редагування оголошення" : "Нове оголошення"}>
          <ListingForm
            listingId={formListingId}
            onCancel={() => setFormListingId(undefined)}
            onSaved={() => {
              setFormListingId(undefined);
              reload();
            }}
          />
        </Card>
      ) : (
        <>
          <Tabs idBase="listings" tabs={TABS} activeId={activeTab} onChange={setActiveTab} />
          <TabPanel id="import-export" idBase="listings" active={activeTab === "import-export"}>
            <ImportExport onImported={reload} />
          </TabPanel>
          {activeTab !== "import-export" ? (
            <Card>
              <div className="table-toolbar">
                <label className="table-search">
                  <Icon name="search" size={15} />
                  <input
                    type="search"
                    placeholder="Пошук за назвою, містом, районом…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    aria-label="Пошук оголошень"
                  />
                </label>
                {canWrite && selected.size > 0 ? (
                  <button
                    type="button"
                    className="btn btn-danger"
                    onClick={() => setConfirmDelete({ ids: Array.from(selected) })}
                  >
                    <Icon name="trash" size={15} />
                    Видалити ({selected.size})
                  </button>
                ) : null}
                <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити список">
                  <Icon name="refresh" size={16} />
                </button>
              </div>

              {status === "loading" ? <Skeleton rows={6} label="Завантаження оголошень" /> : null}
              {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
              {status === "success" && rows.length === 0 ? (
                <EmptyState icon="home" title="Оголошень не знайдено" description="Змініть фільтри або створіть нове оголошення." />
              ) : null}
              {status === "success" && rows.length > 0 ? (
                <>
                  <DataTable
                    columns={columns}
                    rows={rows}
                    getRowId={(row) => row.id}
                    selectable={canWrite}
                    selectedIds={selected}
                    onToggleRow={toggleRow}
                    onToggleAll={toggleAll}
                    caption="Список оголошень"
                    renderActions={(row) => (
                      <div className="row-actions">
                        <button type="button" className="btn btn-icon" onClick={() => setDrawerListingId(row.id)} aria-label="Переглянути">
                          <Icon name="eye" size={15} />
                        </button>
                        {canWrite ? (
                          <>
                            <button type="button" className="btn btn-icon" onClick={() => setFormListingId(row.id)} aria-label="Редагувати">
                              <Icon name="edit" size={15} />
                            </button>
                            <button type="button" className="btn btn-icon" onClick={() => handleDuplicate(row.id)} aria-label="Дублювати">
                              <Icon name="external" size={15} />
                            </button>
                            <button
                              type="button"
                              className="btn btn-icon"
                              onClick={() => handlePublishToggle(row)}
                              aria-label={row.status === "published" ? "Зняти з публікації" : "Опублікувати"}
                            >
                              <Icon name={row.status === "published" ? "eye" : "check"} size={15} />
                            </button>
                            <button
                              type="button"
                              className="btn btn-icon btn-icon-danger"
                              onClick={() => setConfirmDelete({ ids: [row.id] })}
                              aria-label="Видалити"
                            >
                              <Icon name="trash" size={15} />
                            </button>
                          </>
                        ) : null}
                      </div>
                    )}
                  />
                  <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
                </>
              ) : null}
            </Card>
          ) : null}
        </>
      )}

      <ListingDetailDrawer
        listingId={drawerListingId}
        open={drawerListingId != null}
        onClose={() => setDrawerListingId(null)}
        onChanged={reload}
        staff={staff}
        footer={
          canWrite
            ? (listing) =>
                listing && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => {
                      setFormListingId(listing.id);
                      setDrawerListingId(null);
                    }}
                  >
                    Редагувати
                  </button>
                )
            : undefined
        }
      />

      <ConfirmDialog
        open={!!confirmDelete}
        title={confirmDelete?.ids.length > 1 ? `Видалити ${confirmDelete.ids.length} оголошень?` : "Видалити оголошення?"}
        description="Цю дію неможливо скасувати."
        confirmLabel="Видалити"
        tone="danger"
        busy={deleting}
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
