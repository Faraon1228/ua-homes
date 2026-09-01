import React, { useMemo, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync, useDebouncedValue } from "../../lib/hooks.js";
import { PageHeader, Card } from "../../components/Layout.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { Skeleton, ErrorState, EmptyState, Pagination, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { Drawer } from "../../components/Drawer.jsx";
import { useToast } from "../../components/Toast.jsx";
import { formatDate, LEAD_STATUS_LABELS } from "../../lib/format.js";

const PAGE_SIZE = 20;
const STATUS_TONE = { new: "blue", viewed: "amber", responded: "green", closed: "neutral" };
const STATUS_OPTIONS = ["", "new", "viewed", "responded", "closed"];

export function Requests() {
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [activeLead, setActiveLead] = useState(null);
  const debouncedSearch = useDebouncedValue(search, 300);
  const toast = useToast();

  const { status, data, error, reload } = useAsync(
    (signal) =>
      api.get(
        "/leads",
        { status: statusFilter || undefined, search: debouncedSearch || undefined, limit: PAGE_SIZE, offset },
        signal,
      ),
    [statusFilter, debouncedSearch, offset],
  );
  const rows = data?.leads || [];
  const total = data?.total || 0;

  const columns = useMemo(
    () => [
      {
        key: "name",
        header: "Контакт",
        render: (row) => (
          <button type="button" className="link-button" onClick={() => setActiveLead(row)}>
            {row.name || row.email || row.phone || `#${row.id}`}
          </button>
        ),
      },
      { key: "listing_title", header: "Оголошення", render: (row) => row.listing_title || "—" },
      { key: "source", header: "Джерело" },
      {
        key: "status",
        header: "Статус",
        render: (row) => <StatusBadge tone={STATUS_TONE[row.status] || "neutral"}>{LEAD_STATUS_LABELS[row.status] || row.status}</StatusBadge>,
      },
      { key: "created_at", header: "Отримано", render: (row) => formatDate(row.created_at) },
    ],
    [],
  );

  return (
    <div className="page">
      <PageHeader title="Заявки" description="Звернення потенційних клієнтів (лід-форми)." />
      <Card>
        <div className="table-toolbar">
          <label className="table-search">
            <Icon name="search" size={15} />
            <input
              type="search"
              placeholder="Пошук за іменем, email, телефоном…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setOffset(0);
              }}
              aria-label="Пошук заявок"
            />
          </label>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setOffset(0);
            }}
            aria-label="Фільтр за статусом заявки"
          >
            {STATUS_OPTIONS.map((value) => (
              <option key={value || "all"} value={value}>
                {value ? LEAD_STATUS_LABELS[value] : "Усі статуси"}
              </option>
            ))}
          </select>
          <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити">
            <Icon name="refresh" size={16} />
          </button>
        </div>

        {status === "loading" ? <Skeleton rows={5} label="Завантаження заявок" /> : null}
        {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
        {status === "success" && rows.length === 0 ? (
          <EmptyState icon="inbox" title="Заявок немає" description="Нових звернень за цим фільтром не знайдено." />
        ) : null}
        {status === "success" && rows.length > 0 ? (
          <>
            <DataTable columns={columns} rows={rows} getRowId={(row) => row.id} caption="Заявки клієнтів" />
            <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        ) : null}
      </Card>

      <LeadDrawer lead={activeLead} onClose={() => setActiveLead(null)} onUpdated={reload} toast={toast} />
    </div>
  );
}

function LeadDrawer({ lead, onClose, onUpdated, toast }) {
  const [responseMessage, setResponseMessage] = useState("");
  const [saving, setSaving] = useState(false);

  React.useEffect(() => {
    setResponseMessage(lead?.response_message || "");
  }, [lead?.id, lead?.response_message]);

  async function updateStatus(nextStatus) {
    if (!lead) return;
    if (nextStatus === "responded" && !responseMessage.trim()) {
      toast.error("Додайте текст відповіді перед позначенням «Опрацьовано»");
      return;
    }
    setSaving(true);
    try {
      await api.patch(`/leads/${lead.id}`, { status: nextStatus, response_message: responseMessage || undefined });
      toast.success("Заявку оновлено");
      onUpdated();
      onClose();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer open={!!lead} onClose={onClose} title={lead ? lead.name || lead.email || `Заявка #${lead.id}` : "Заявка"}>
      {lead ? (
        <>
          <dl className="detail-grid">
            <div>
              <dt>Телефон</dt>
              <dd>{lead.phone || "—"}</dd>
            </div>
            <div>
              <dt>Email</dt>
              <dd>{lead.email || "—"}</dd>
            </div>
            <div>
              <dt>Оголошення</dt>
              <dd>{lead.listing_title || "—"}</dd>
            </div>
            <div>
              <dt>Місто / район</dt>
              <dd>
                {lead.city || "—"}, {lead.district || "—"}
              </dd>
            </div>
            <div>
              <dt>Джерело</dt>
              <dd>{lead.source}</dd>
            </div>
            <div>
              <dt>Отримано</dt>
              <dd>{formatDate(lead.created_at)}</dd>
            </div>
          </dl>
          {lead.message ? (
            <div className="detail-description">
              <h4>Повідомлення</h4>
              <p>{lead.message}</p>
            </div>
          ) : null}
          <label className="form-field">
            <span className="form-label">Відповідь</span>
            <textarea
              rows={4}
              maxLength={1200}
              value={responseMessage}
              onChange={(e) => setResponseMessage(e.target.value)}
            />
          </label>
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={() => updateStatus("viewed")} disabled={saving}>
              Переглянуто
            </button>
            <button type="button" className="btn btn-primary" onClick={() => updateStatus("responded")} disabled={saving}>
              Опрацьовано
            </button>
            <button type="button" className="btn btn-danger" onClick={() => updateStatus("closed")} disabled={saving}>
              Закрити
            </button>
          </div>
        </>
      ) : null}
    </Drawer>
  );
}
