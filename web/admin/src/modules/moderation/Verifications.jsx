import React, { useMemo, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync } from "../../lib/hooks.js";
import { Card } from "../../components/Layout.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { Skeleton, ErrorState, EmptyState, Pagination, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { useToast } from "../../components/Toast.jsx";
import { formatDate, VERIFICATION_STATUS_LABELS } from "../../lib/format.js";

const PAGE_SIZE = 20;
const STATUS_FILTERS = [
  { value: "pending", label: "Очікують" },
  { value: "verified", label: "Підтверджені" },
  { value: "rejected", label: "Відхилені" },
  { value: "unverified", label: "Не перевірені" },
];
const STATUS_TONE = { verified: "green", pending: "amber", rejected: "red", unverified: "neutral" };

export function Verifications() {
  const [statusFilter, setStatusFilter] = useState("pending");
  const [offset, setOffset] = useState(0);
  const [busyId, setBusyId] = useState(null);
  const toast = useToast();

  const { status, data, error, reload } = useAsync(
    (signal) => api.get("/verifications", { status: statusFilter, limit: PAGE_SIZE, offset }, signal),
    [statusFilter, offset],
  );
  const rows = data?.verifications || [];
  const total = data?.total || 0;

  async function updateVerification(listingId, field, value) {
    setBusyId(listingId);
    try {
      await api.patch(`/verifications/${listingId}`, { [field]: value });
      toast.success("Статус верифікації оновлено");
      reload();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusyId(null);
    }
  }

  const columns = useMemo(
    () => [
      { key: "title", header: "Оголошення" },
      { key: "city", header: "Місто" },
      {
        key: "listing_verification_status",
        header: "Оголошення",
        render: (row) => (
          <StatusBadge tone={STATUS_TONE[row.listing_verification_status] || "neutral"}>
            {VERIFICATION_STATUS_LABELS[row.listing_verification_status] || "—"}
          </StatusBadge>
        ),
      },
      {
        key: "owner_verification_status",
        header: "Власник",
        render: (row) => (
          <StatusBadge tone={STATUS_TONE[row.owner_verification_status] || "neutral"}>
            {VERIFICATION_STATUS_LABELS[row.owner_verification_status] || "—"}
          </StatusBadge>
        ),
      },
      {
        key: "phone_verification_status",
        header: "Телефон",
        render: (row) => (
          <StatusBadge tone={STATUS_TONE[row.phone_verification_status] || "neutral"}>
            {VERIFICATION_STATUS_LABELS[row.phone_verification_status] || "—"}
          </StatusBadge>
        ),
      },
      { key: "created_at", header: "Створено", render: (row) => formatDate(row.created_at) },
    ],
    [],
  );

  return (
    <Card>
      <div className="table-toolbar">
        <div className="segmented" role="group" aria-label="Фільтр за статусом верифікації">
          {STATUS_FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`segmented-option${statusFilter === option.value ? " active" : ""}`}
              aria-pressed={statusFilter === option.value}
              onClick={() => {
                setStatusFilter(option.value);
                setOffset(0);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
        <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити">
          <Icon name="refresh" size={16} />
        </button>
      </div>

      {status === "loading" ? <Skeleton rows={5} label="Завантаження верифікацій" /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
      {status === "success" && rows.length === 0 ? (
        <EmptyState icon="shield" title="Немає записів" description="За обраним фільтром нічого не знайдено." />
      ) : null}
      {status === "success" && rows.length > 0 ? (
        <>
          <DataTable
            columns={columns}
            rows={rows}
            getRowId={(row) => row.id}
            caption="Черга верифікацій"
            renderActions={(row) => (
              <div className="row-actions">
                <button
                  type="button"
                  className="btn btn-icon"
                  disabled={busyId === row.id}
                  onClick={() => updateVerification(row.id, "listing_verification_status", "verified")}
                  aria-label="Підтвердити оголошення"
                >
                  <Icon name="check" size={15} />
                </button>
                <button
                  type="button"
                  className="btn btn-icon btn-icon-danger"
                  disabled={busyId === row.id}
                  onClick={() => updateVerification(row.id, "listing_verification_status", "rejected")}
                  aria-label="Відхилити оголошення"
                >
                  <Icon name="close" size={15} />
                </button>
                <button
                  type="button"
                  className="btn btn-icon"
                  disabled={busyId === row.id}
                  onClick={() => updateVerification(row.id, "owner_verification_status", "verified")}
                  aria-label="Підтвердити власника"
                >
                  <Icon name="check" size={15} />
                </button>
                <button
                  type="button"
                  className="btn btn-icon btn-icon-danger"
                  disabled={busyId === row.id}
                  onClick={() => updateVerification(row.id, "owner_verification_status", "rejected")}
                  aria-label="Відхилити власника"
                >
                  <Icon name="close" size={15} />
                </button>
                <button
                  type="button"
                  className="btn btn-icon"
                  disabled={busyId === row.id}
                  onClick={() => updateVerification(row.id, "phone_verification_status", "verified")}
                  aria-label="Підтвердити телефон"
                >
                  <Icon name="check" size={15} />
                </button>
                <button
                  type="button"
                  className="btn btn-icon btn-icon-danger"
                  disabled={busyId === row.id}
                  onClick={() => updateVerification(row.id, "phone_verification_status", "rejected")}
                  aria-label="Відхилити телефон"
                >
                  <Icon name="close" size={15} />
                </button>
              </div>
            )}
          />
          <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </>
      ) : null}
    </Card>
  );
}
