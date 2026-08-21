import React, { useMemo, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync, useDebouncedValue } from "../../lib/hooks.js";
import { PageHeader, Card } from "../../components/Layout.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { Skeleton, ErrorState, EmptyState, Pagination, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { Drawer } from "../../components/Drawer.jsx";
import { FormField } from "../../components/FormField.jsx";
import { useToast } from "../../components/Toast.jsx";

const PAGE_SIZE = 20;

const EMPTY_FORM = { slug: "", name: "", city: "", kind: "agency", specialization: "", avg_response_minutes: "", team_size: "", completed_deals: "" };

export function Agencies() {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [formAgency, setFormAgency] = useState(undefined); // undefined = closed, null = create
  const debouncedSearch = useDebouncedValue(search, 300);
  const toast = useToast();

  const { status, data, error, reload } = useAsync(
    (signal) => api.get("/agencies", { search: debouncedSearch || undefined, limit: PAGE_SIZE, offset }, signal),
    [debouncedSearch, offset],
  );
  const rows = data?.agencies || [];
  const total = data?.total || 0;

  async function toggleVerified(agency) {
    try {
      await api.post(`/agencies/${agency.slug}/verify`, { verified: !agency.is_verified });
      toast.success(agency.is_verified ? "Верифікацію знято" : "Агенцію верифіковано");
      reload();
    } catch (err) {
      toast.error(err.message);
    }
  }

  const columns = useMemo(
    () => [
      { key: "name", header: "Назва" },
      { key: "city", header: "Місто" },
      { key: "kind", header: "Тип", render: (row) => (row.kind === "developer" ? "Забудовник" : "Агенція") },
      { key: "team_size", header: "Команда", render: (row) => row.team_size ?? "—" },
      { key: "completed_deals", header: "Угод", render: (row) => row.completed_deals ?? "—" },
      {
        key: "is_verified",
        header: "Верифікація",
        render: (row) => <StatusBadge tone={row.is_verified ? "green" : "neutral"}>{row.is_verified ? "Підтверджено" : "Не підтверджено"}</StatusBadge>,
      },
    ],
    [],
  );

  return (
    <div className="page">
      <PageHeader
        title="Агенції"
        description="Профілі агенцій та забудовників, верифікація."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setFormAgency(null)}>
            <Icon name="plus" size={15} />
            Додати агенцію
          </button>
        }
      />
      <Card>
        <div className="table-toolbar">
          <label className="table-search">
            <Icon name="search" size={15} />
            <input
              type="search"
              placeholder="Пошук за назвою, slug, містом…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setOffset(0);
              }}
              aria-label="Пошук агенцій"
            />
          </label>
          <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити">
            <Icon name="refresh" size={16} />
          </button>
        </div>

        {status === "loading" ? <Skeleton rows={5} label="Завантаження агенцій" /> : null}
        {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
        {status === "success" && rows.length === 0 ? <EmptyState icon="building" title="Агенцій не знайдено" /> : null}
        {status === "success" && rows.length > 0 ? (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              getRowId={(row) => row.slug}
              caption="Список агенцій"
              renderActions={(row) => (
                <div className="row-actions">
                  <button type="button" className="btn btn-icon" onClick={() => setFormAgency(row)} aria-label="Редагувати">
                    <Icon name="edit" size={15} />
                  </button>
                  <button type="button" className="btn btn-icon" onClick={() => toggleVerified(row)} aria-label={row.is_verified ? "Зняти верифікацію" : "Верифікувати"}>
                    <Icon name={row.is_verified ? "close" : "check"} size={15} />
                  </button>
                </div>
              )}
            />
            <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        ) : null}
      </Card>

      <AgencyDrawer agency={formAgency} onClose={() => setFormAgency(undefined)} onSaved={() => { setFormAgency(undefined); reload(); }} />
    </div>
  );
}

function AgencyDrawer({ agency, onClose, onSaved }) {
  const isCreate = agency === null;
  const open = agency !== undefined;
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  React.useEffect(() => {
    if (agency && agency !== null) {
      setForm({
        slug: agency.slug,
        name: agency.name || "",
        city: agency.city || "",
        kind: agency.kind || "agency",
        specialization: agency.specialization || "",
        avg_response_minutes: agency.avg_response_minutes != null ? String(agency.avg_response_minutes) : "",
        team_size: agency.team_size != null ? String(agency.team_size) : "",
        completed_deals: agency.completed_deals != null ? String(agency.completed_deals) : "",
      });
    } else if (agency === null) {
      setForm(EMPTY_FORM);
    }
  }, [agency]);

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    const numericFields = ["avg_response_minutes", "team_size", "completed_deals"];
    const payload = { name: form.name, city: form.city, kind: form.kind, specialization: form.specialization };
    numericFields.forEach((field) => {
      if (form[field] !== "") payload[field] = Number(form[field]);
    });
    try {
      if (isCreate) {
        await api.post("/agencies", { ...payload, slug: form.slug });
        toast.success("Агенцію створено");
      } else {
        await api.patch(`/agencies/${form.slug}`, payload);
        toast.success("Дані агенції оновлено");
      }
      onSaved();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer open={open} onClose={onClose} title={isCreate ? "Нова агенція" : `Редагування: ${form.name}`}>
      {open ? (
        <form onSubmit={handleSubmit} noValidate>
          {isCreate ? (
            <FormField label="Slug (унікальний ідентифікатор)" required>
              <input type="text" value={form.slug} onChange={(e) => update("slug", e.target.value.toLowerCase())} required pattern="[a-z0-9]+(-[a-z0-9]+)*" />
            </FormField>
          ) : null}
          <FormField label="Назва" required>
            <input type="text" value={form.name} onChange={(e) => update("name", e.target.value)} required maxLength={160} />
          </FormField>
          <FormField label="Місто" required>
            <input type="text" value={form.city} onChange={(e) => update("city", e.target.value)} required maxLength={120} />
          </FormField>
          <FormField label="Тип">
            <select value={form.kind} onChange={(e) => update("kind", e.target.value)}>
              <option value="agency">Агенція</option>
              <option value="developer">Забудовник</option>
            </select>
          </FormField>
          <FormField label="Спеціалізація">
            <input type="text" value={form.specialization} onChange={(e) => update("specialization", e.target.value)} maxLength={500} />
          </FormField>
          <FormField label="Розмір команди">
            <input type="number" min="0" value={form.team_size} onChange={(e) => update("team_size", e.target.value)} />
          </FormField>
          <FormField label="Завершені угоди">
            <input type="number" min="0" value={form.completed_deals} onChange={(e) => update("completed_deals", e.target.value)} />
          </FormField>
          <FormField label="Середній час відповіді, хв">
            <input type="number" min="0" value={form.avg_response_minutes} onChange={(e) => update("avg_response_minutes", e.target.value)} />
          </FormField>
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>
              Скасувати
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Збереження…" : "Зберегти"}
            </button>
          </div>
        </form>
      ) : null}
    </Drawer>
  );
}
