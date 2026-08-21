import React, { useMemo, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync, useDebouncedValue } from "../../lib/hooks.js";
import { PageHeader, Card } from "../../components/Layout.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { Skeleton, ErrorState, EmptyState, Pagination, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { formatDate, formatPrice, LISTING_STATUS_LABELS } from "../../lib/format.js";
import { ListingDetailDrawer } from "../listings/ListingDetailDrawer.jsx";

const PAGE_SIZE = 20;
const STATUS_TONE = { published: "green", draft: "neutral", pending: "amber", rejected: "red", archived: "neutral" };

export function PricesHistory({ staff }) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [drawerListingId, setDrawerListingId] = useState(null);
  const debouncedSearch = useDebouncedValue(search, 300);

  const { status, data, error, reload } = useAsync(
    (signal) => api.get("/listings", { search: debouncedSearch || undefined, limit: PAGE_SIZE, offset }, signal),
    [debouncedSearch, offset],
  );
  const rows = data?.listings || [];
  const total = data?.total || 0;

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
      { key: "price", header: "Поточна ціна", render: (row) => formatPrice(row.price) },
      {
        key: "status",
        header: "Статус",
        render: (row) => <StatusBadge tone={STATUS_TONE[row.status] || "neutral"}>{LISTING_STATUS_LABELS[row.status] || row.status}</StatusBadge>,
      },
      { key: "created_at", header: "Створено", render: (row) => formatDate(row.created_at) },
    ],
    [],
  );

  return (
    <div className="page">
      <PageHeader title="Ціни й історія" description="Оберіть оголошення, щоб переглянути історію змін полів і ціни." />
      <Card>
        <div className="table-toolbar">
          <label className="table-search">
            <Icon name="search" size={15} />
            <input
              type="search"
              placeholder="Пошук оголошень…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setOffset(0);
              }}
              aria-label="Пошук оголошень для перегляду історії"
            />
          </label>
          <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити">
            <Icon name="refresh" size={16} />
          </button>
        </div>

        {status === "loading" ? <Skeleton rows={5} label="Завантаження оголошень" /> : null}
        {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
        {status === "success" && rows.length === 0 ? <EmptyState icon="history" title="Оголошень не знайдено" /> : null}
        {status === "success" && rows.length > 0 ? (
          <>
            <DataTable columns={columns} rows={rows} getRowId={(row) => row.id} caption="Оголошення для перегляду історії" />
            <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        ) : null}
      </Card>

      <ListingDetailDrawer
        listingId={drawerListingId}
        open={drawerListingId != null}
        onClose={() => setDrawerListingId(null)}
        staff={staff}
        initialTab="history"
      />
    </div>
  );
}
