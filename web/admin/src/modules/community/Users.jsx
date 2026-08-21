import React, { useMemo, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync, useDebouncedValue } from "../../lib/hooks.js";
import { PageHeader, Card } from "../../components/Layout.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { Skeleton, ErrorState, EmptyState, Pagination, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { ConfirmDialog } from "../../components/ConfirmDialog.jsx";
import { useToast } from "../../components/Toast.jsx";
import { formatDate, USER_ROLE_LABELS, USER_STATUS_LABELS } from "../../lib/format.js";
import { useSession } from "../../lib/session.js";

const PAGE_SIZE = 20;
const ROLE_OPTIONS = ["", "user", "agent", "moderator", "admin"];
const STATUS_TONE = { active: "green", inactive: "neutral", suspended: "red" };

export function Users({ focusUser, onConsumeFocusUser }) {
  const [roleFilter, setRoleFilter] = useState("");
  const [search, setSearch] = useState(focusUser?.email || focusUser?.name || "");
  const [offset, setOffset] = useState(0);
  const [pendingChange, setPendingChange] = useState(null);
  const [busy, setBusy] = useState(false);
  const debouncedSearch = useDebouncedValue(search, 300);
  const toast = useToast();
  const { staff } = useSession();

  React.useEffect(() => {
    if (focusUser) onConsumeFocusUser?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { status, data, error, reload } = useAsync(
    (signal) => api.get("/users", { role: roleFilter || undefined, search: debouncedSearch || undefined, limit: PAGE_SIZE, offset }, signal),
    [roleFilter, debouncedSearch, offset],
  );
  const rows = data?.users || [];
  const total = data?.total || 0;

  async function handleConfirm() {
    if (!pendingChange) return;
    setBusy(true);
    try {
      await api.put(`/users/${pendingChange.user.id}`, pendingChange.updates);
      toast.success("Дані користувача оновлено");
      setPendingChange(null);
      reload();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  const columns = useMemo(
    () => [
      { key: "name", header: "Ім'я", render: (row) => row.name || "—" },
      { key: "email", header: "Email" },
      {
        key: "role",
        header: "Роль",
        render: (row) => <StatusBadge tone="blue">{USER_ROLE_LABELS[row.role] || row.role}</StatusBadge>,
      },
      {
        key: "status",
        header: "Статус",
        render: (row) => <StatusBadge tone={STATUS_TONE[row.status] || "neutral"}>{USER_STATUS_LABELS[row.status] || row.status}</StatusBadge>,
      },
      { key: "created_at", header: "Зареєстровано", render: (row) => formatDate(row.created_at) },
    ],
    [],
  );

  return (
    <div className="page">
      <PageHeader title="Користувачі" description="Керування ролями та статусами облікових записів." />
      <Card>
        <div className="table-toolbar">
          <label className="table-search">
            <Icon name="search" size={15} />
            <input
              type="search"
              placeholder="Пошук за ім'ям або email…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setOffset(0);
              }}
              aria-label="Пошук користувачів"
            />
          </label>
          <select
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setOffset(0);
            }}
            aria-label="Фільтр за роллю"
          >
            {ROLE_OPTIONS.map((value) => (
              <option key={value || "all"} value={value}>
                {value ? USER_ROLE_LABELS[value] : "Усі ролі"}
              </option>
            ))}
          </select>
          <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити">
            <Icon name="refresh" size={16} />
          </button>
        </div>

        {status === "loading" ? <Skeleton rows={5} label="Завантаження користувачів" /> : null}
        {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
        {status === "success" && rows.length === 0 ? (
          <EmptyState icon="users" title="Користувачів не знайдено" />
        ) : null}
        {status === "success" && rows.length > 0 ? (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              getRowId={(row) => row.id}
              caption="Список користувачів"
              renderActions={(row) => (
                <div className="row-actions">
                  <select
                    aria-label={`Роль для ${row.email}`}
                    value={row.role}
                    disabled={row.id === staff?.id}
                    onChange={(e) => setPendingChange({ user: row, updates: { role: e.target.value } })}
                  >
                    {["user", "agent", "moderator", "admin"].map((value) => (
                      <option key={value} value={value}>
                        {USER_ROLE_LABELS[value]}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label={`Статус для ${row.email}`}
                    value={row.status}
                    disabled={row.id === staff?.id}
                    onChange={(e) => setPendingChange({ user: row, updates: { status: e.target.value } })}
                  >
                    {["active", "inactive", "suspended"].map((value) => (
                      <option key={value} value={value}>
                        {USER_STATUS_LABELS[value]}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            />
            <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        ) : null}
      </Card>

      <ConfirmDialog
        open={!!pendingChange}
        title="Змінити дані користувача?"
        description={
          pendingChange
            ? `${pendingChange.user.email}: ${Object.entries(pendingChange.updates)
                .map(([k, v]) => `${k} → ${v}`)
                .join(", ")}`
            : ""
        }
        confirmLabel="Зберегти"
        busy={busy}
        onConfirm={handleConfirm}
        onCancel={() => setPendingChange(null)}
      />
    </div>
  );
}
