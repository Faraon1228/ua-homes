import React, { useMemo, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync, useDebouncedValue } from "../../lib/hooks.js";
import { PageHeader, Card } from "../../components/Layout.jsx";
import { DataTable } from "../../components/DataTable.jsx";
import { Skeleton, ErrorState, EmptyState, Pagination, StatusBadge } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { Drawer } from "../../components/Drawer.jsx";
import { FormField } from "../../components/FormField.jsx";
import { ConfirmDialog } from "../../components/ConfirmDialog.jsx";
import { useToast } from "../../components/Toast.jsx";

const PAGE_SIZE = 20;
const EMPTY_FORM = {
  slug: "",
  name: "",
  city: "",
  specialization: "",
  status: "active",
  avg_response_minutes: "",
  team_size: "",
  completed_deals: "",
};
const STATUS_LABELS = { active: "Активний", suspended: "Призупинений" };
const STATUS_TONES = { active: "green", suspended: "red" };

const DIRECTORY_CONFIG = {
  agency: {
    endpoint: "/agencies",
    responseKey: "agencies",
    title: "Агенції",
    description: "Профілі агенцій, статуси та верифікація.",
    addLabel: "Додати агенцію",
    createdMessage: "Агенцію створено",
    emptyLabel: "Агенцій не знайдено",
    caption: "Список агенцій",
  },
  developer: {
    endpoint: "/developers",
    responseKey: "developers",
    title: "Забудовники",
    description: "Окремий реєстр забудовників, їхні статуси та верифікація.",
    addLabel: "Додати забудовника",
    createdMessage: "Забудовника створено",
    emptyLabel: "Забудовників не знайдено",
    caption: "Список забудовників",
  },
};

export function Agencies() {
  return <OrganizationDirectory kind="agency" />;
}

export function OrganizationDirectory({ kind }) {
  const config = DIRECTORY_CONFIG[kind];
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [verifiedFilter, setVerifiedFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [formOrganization, setFormOrganization] = useState(undefined);
  const [deleteOrganization, setDeleteOrganization] = useState(null);
  const [busy, setBusy] = useState(false);
  const debouncedSearch = useDebouncedValue(search, 300);
  const toast = useToast();

  const { status, data, error, reload } = useAsync(
    (signal) =>
      api.get(
        config.endpoint,
        {
          search: debouncedSearch || undefined,
          status: statusFilter || undefined,
          verified: verifiedFilter || undefined,
          limit: PAGE_SIZE,
          offset,
        },
        signal,
      ),
    [config.endpoint, debouncedSearch, statusFilter, verifiedFilter, offset],
  );
  const rows = data?.[config.responseKey] || [];
  const total = data?.total || 0;

  async function toggleVerified(organization) {
    try {
      await api.post(`${config.endpoint}/${organization.slug}/verify`, {
        verified: !organization.is_verified,
        revision: organization.revision,
      });
      toast.success(organization.is_verified ? "Верифікацію знято" : "Організацію верифіковано");
      reload();
    } catch (err) {
      toast.error(err.message);
    }
  }

  async function handleDelete() {
    if (!deleteOrganization) return;
    setBusy(true);
    try {
      await api.del(`${config.endpoint}/${deleteOrganization.slug}`, {
        revision: deleteOrganization.revision,
      });
      toast.success("Організацію видалено");
      setDeleteOrganization(null);
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
        key: "name",
        header: "Назва",
        render: (row) => (
          <button
            type="button"
            className="link-button"
            onClick={() => setFormOrganization(row)}
            aria-label={`Відкрити ${row.name}`}
          >
            {row.name}
          </button>
        ),
      },
      { key: "city", header: "Місто" },
      {
        key: "status",
        header: "Статус",
        render: (row) => (
          <StatusBadge tone={STATUS_TONES[row.status] || "neutral"}>
            {STATUS_LABELS[row.status] || row.status}
          </StatusBadge>
        ),
      },
      { key: "active_listings", header: "Активні оголошення", render: (row) => row.active_listings ?? 0 },
      {
        key: "is_verified",
        header: "Верифікація",
        render: (row) => (
          <StatusBadge tone={row.is_verified ? "green" : "neutral"}>
            {row.is_verified ? "Підтверджено" : "Не підтверджено"}
          </StatusBadge>
        ),
      },
    ],
    [],
  );

  return (
    <div className="page" data-testid={`${kind}-directory`}>
      <PageHeader
        title={config.title}
        description={config.description}
        actions={
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setFormOrganization(null)}
            data-testid={`add-${kind}`}
          >
            <Icon name="plus" size={15} />
            {config.addLabel}
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
              onChange={(event) => {
                setSearch(event.target.value);
                setOffset(0);
              }}
              aria-label={`Пошук: ${config.title.toLowerCase()}`}
            />
          </label>
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value);
              setOffset(0);
            }}
            aria-label="Фільтр за статусом організації"
          >
            <option value="">Усі статуси</option>
            <option value="active">Активні</option>
            <option value="suspended">Призупинені</option>
          </select>
          <select
            value={verifiedFilter}
            onChange={(event) => {
              setVerifiedFilter(event.target.value);
              setOffset(0);
            }}
            aria-label="Фільтр за верифікацією"
          >
            <option value="">Усі верифікації</option>
            <option value="true">Підтверджені</option>
            <option value="false">Не підтверджені</option>
          </select>
          <button type="button" className="btn btn-icon" onClick={reload} aria-label="Оновити">
            <Icon name="refresh" size={16} />
          </button>
        </div>

        {status === "loading" ? <Skeleton rows={5} label={`Завантаження: ${config.title.toLowerCase()}`} /> : null}
        {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
        {status === "success" && rows.length === 0 ? <EmptyState icon="building" title={config.emptyLabel} /> : null}
        {status === "success" && rows.length > 0 ? (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              getRowId={(row) => row.slug}
              caption={config.caption}
              renderActions={(row) => (
                <div className="row-actions">
                  <button
                    type="button"
                    className="btn btn-icon"
                    onClick={() => setFormOrganization(row)}
                    aria-label={`Редагувати ${row.name}`}
                  >
                    <Icon name="edit" size={15} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-icon"
                    onClick={() => toggleVerified(row)}
                    disabled={row.status !== "active" && !row.is_verified}
                    aria-label={row.is_verified ? `Зняти верифікацію ${row.name}` : `Верифікувати ${row.name}`}
                  >
                    <Icon name={row.is_verified ? "close" : "check"} size={15} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-icon"
                    onClick={() => setDeleteOrganization(row)}
                    disabled={row.status !== "suspended" || row.is_verified}
                    aria-label={`Видалити ${row.name}`}
                  >
                    <Icon name="trash" size={15} />
                  </button>
                </div>
              )}
            />
            <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        ) : null}
      </Card>

      <OrganizationDrawer
        organization={formOrganization}
        kind={kind}
        config={config}
        onClose={() => setFormOrganization(undefined)}
        onSaved={() => {
          setFormOrganization(undefined);
          reload();
        }}
      />
      <ConfirmDialog
        open={!!deleteOrganization}
        title={`Видалити ${deleteOrganization?.name || "організацію"}?`}
        description="Цю дію неможливо скасувати. Видалення доступне лише для призупиненого, неверифікованого профілю без пов’язаних користувачів чи оголошень."
        confirmLabel="Видалити"
        tone="danger"
        busy={busy}
        onConfirm={handleDelete}
        onCancel={() => setDeleteOrganization(null)}
        testId={`delete-${kind}-dialog`}
      />
    </div>
  );
}

function OrganizationDrawer({ organization, kind, config, onClose, onSaved }) {
  const isCreate = organization === null;
  const open = organization !== undefined;
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  React.useEffect(() => {
    if (organization && organization !== null) {
      setForm({
        slug: organization.slug,
        name: organization.name || "",
        city: organization.city || "",
        specialization: organization.specialization || "",
        status: organization.status || "active",
        avg_response_minutes: organization.avg_response_minutes != null ? String(organization.avg_response_minutes) : "",
        team_size: organization.team_size != null ? String(organization.team_size) : "",
        completed_deals: organization.completed_deals != null ? String(organization.completed_deals) : "",
      });
    } else if (organization === null) {
      setForm(EMPTY_FORM);
    }
  }, [organization]);

  function update(field, value) {
    setForm((previous) => ({ ...previous, [field]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    const payload = {
      name: form.name,
      city: form.city,
      specialization: form.specialization,
      status: form.status,
    };
    ["avg_response_minutes", "team_size", "completed_deals"].forEach((field) => {
      if (form[field] !== "") payload[field] = Number(form[field]);
    });
    try {
      if (isCreate) {
        await api.post(config.endpoint, { ...payload, slug: form.slug, kind });
        toast.success(config.createdMessage);
      } else {
        await api.patch(`${config.endpoint}/${form.slug}`, {
          ...payload,
          revision: organization.revision,
        });
        toast.success("Дані організації оновлено");
      }
      onSaved();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={isCreate ? config.addLabel : `Редагування: ${form.name}`}
    >
      {open ? (
        <form onSubmit={handleSubmit} noValidate data-testid={`${kind}-form`}>
          {isCreate ? (
            <FormField label="Slug (унікальний ідентифікатор)" required>
              <input
                type="text"
                value={form.slug}
                onChange={(event) => update("slug", event.target.value.toLowerCase())}
                required
                pattern="[a-z0-9]+(-[a-z0-9]+)*"
                data-testid={`${kind}-slug`}
              />
            </FormField>
          ) : null}
          <FormField label="Назва" required>
            <input type="text" value={form.name} onChange={(event) => update("name", event.target.value)} required maxLength={160} />
          </FormField>
          <FormField label="Місто" required>
            <input type="text" value={form.city} onChange={(event) => update("city", event.target.value)} required maxLength={120} />
          </FormField>
          {!isCreate ? (
            <FormField label="Статус">
              <select value={form.status} onChange={(event) => update("status", event.target.value)}>
                <option value="active">Активний</option>
                <option value="suspended">Призупинений</option>
              </select>
            </FormField>
          ) : null}
          <FormField label="Спеціалізація">
            <input type="text" value={form.specialization} onChange={(event) => update("specialization", event.target.value)} maxLength={500} />
          </FormField>
          <FormField label="Розмір команди">
            <input type="number" min="0" value={form.team_size} onChange={(event) => update("team_size", event.target.value)} />
          </FormField>
          <FormField label="Завершені угоди">
            <input type="number" min="0" value={form.completed_deals} onChange={(event) => update("completed_deals", event.target.value)} />
          </FormField>
          <FormField label="Середній час відповіді, хв">
            <input type="number" min="0" value={form.avg_response_minutes} onChange={(event) => update("avg_response_minutes", event.target.value)} />
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
