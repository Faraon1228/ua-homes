import React, { useEffect, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { FormField } from "../../components/FormField.jsx";
import { Skeleton } from "../../components/States.jsx";
import { Icon } from "../../components/icons.jsx";
import { useToast } from "../../components/Toast.jsx";
import { loadUaCenters } from "../../lib/uaCenters.js";
import { buildListingPayload, EMPTY_LISTING_FORM, listingToForm } from "./listingFormModel.js";

const STATUS_OPTIONS = [
  { value: "draft", label: "Чернетка" },
  { value: "pending", label: "На розгляді" },
  { value: "published", label: "Опубліковано" },
  { value: "rejected", label: "Відхилено" },
  { value: "archived", label: "Архів" },
];
const LIFECYCLE_OPTIONS = [
  { value: "active", label: "Активне" },
  { value: "sold", label: "Продано" },
  { value: "removed", label: "Знято" },
];
const SOURCE_OPTIONS = [
  { value: "owner", label: "Власник" },
  { value: "agent", label: "Агент" },
  { value: "developer", label: "Забудовник" },
];

export function ListingForm({ listingId, onSaved, onCancel }) {
  const isCreate = !listingId;
  const [form, setForm] = useState(EMPTY_LISTING_FORM);
  const [loading, setLoading] = useState(!isCreate);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});
  const [centers, setCenters] = useState({ allCenters: [], regionData: {} });
  const [highlightDraft, setHighlightDraft] = useState("");
  const toast = useToast();

  useEffect(() => {
    loadUaCenters().then(setCenters);
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!isCreate) {
      setLoading(true);
      api
        .get(`/listings/${listingId}`)
        .then((data) => {
          if (!cancelled) setForm(listingToForm(data.listing));
        })
        .catch((err) => !cancelled && toast.error(err.message))
        .finally(() => !cancelled && setLoading(false));
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listingId]);

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function validate() {
    const nextErrors = {};
    if (!form.title.trim()) nextErrors.title = "Вкажіть заголовок";
    if (!form.city.trim()) nextErrors.city = "Вкажіть місто";
    if (!form.district.trim()) nextErrors.district = "Вкажіть район";
    if (!form.price || Number(form.price) <= 0) nextErrors.price = "Ціна має бути більшою за нуль";
    if (form.rooms === "" || Number(form.rooms) < 0) nextErrors.rooms = "Вкажіть кількість кімнат";
    if (!form.area || Number(form.area) <= 0) nextErrors.area = "Площа має бути більшою за нуль";
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!validate()) {
      toast.error("Перевірте обов'язкові поля форми");
      return;
    }
    setSaving(true);
    try {
      const payload = buildListingPayload(form, { isCreate });
      if (isCreate) {
        const result = await api.post("/listings", payload);
        toast.success("Оголошення створено");
        onSaved(result.id);
      } else {
        await api.put(`/listings/${listingId}`, payload);
        toast.success("Зміни збережено");
        onSaved(listingId);
      }
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  function addHighlight() {
    const value = highlightDraft.trim();
    if (!value) return;
    if (!form.highlights.includes(value)) {
      update("highlights", [...form.highlights, value]);
    }
    setHighlightDraft("");
  }

  function removeHighlight(value) {
    update(
      "highlights",
      form.highlights.filter((h) => h !== value),
    );
  }

  if (loading) return <Skeleton rows={6} label="Завантаження форми оголошення" />;

  return (
    <form className="listing-form" onSubmit={handleSubmit} noValidate>
      <datalist id="ua-city-options">
        {(centers.allCenters || []).map((city) => (
          <option key={city} value={city} />
        ))}
      </datalist>

      <div className="form-grid">
        <FormField label="Заголовок" error={errors.title} required>
          <input
            type="text"
            value={form.title}
            maxLength={200}
            onChange={(e) => update("title", e.target.value)}
            required
          />
        </FormField>
        <FormField label="Місто" error={errors.city} required hint="Почніть вводити — підкажемо варіанти">
          <input
            type="text"
            list="ua-city-options"
            value={form.city}
            maxLength={100}
            onChange={(e) => update("city", e.target.value)}
            required
          />
        </FormField>
        <FormField label="Район" error={errors.district} required>
          <input
            type="text"
            value={form.district}
            maxLength={100}
            onChange={(e) => update("district", e.target.value)}
            required
          />
        </FormField>
        <FormField label="Ціна, $" error={errors.price} required>
          <input
            type="number"
            min="1"
            value={form.price}
            onChange={(e) => update("price", e.target.value)}
            required
          />
        </FormField>
        <FormField label="Кімнати" error={errors.rooms} required>
          <input type="number" min="0" value={form.rooms} onChange={(e) => update("rooms", e.target.value)} required />
        </FormField>
        <FormField label="Площа, м²" error={errors.area} required>
          <input
            type="number"
            min="1"
            step="0.1"
            value={form.area}
            onChange={(e) => update("area", e.target.value)}
            required
          />
        </FormField>
        <FormField label="Поверх">
          <input type="number" min="0" value={form.floor} onChange={(e) => update("floor", e.target.value)} />
        </FormField>
        <FormField label="Поверховість">
          <input
            type="number"
            min="1"
            value={form.totalFloors}
            onChange={(e) => update("totalFloors", e.target.value)}
          />
        </FormField>
        <FormField label="Рік будівництва">
          <input type="number" value={form.yearBuilt} onChange={(e) => update("yearBuilt", e.target.value)} />
        </FormField>
        <FormField label="Тип нерухомості">
          <input type="text" value={form.propertyType} onChange={(e) => update("propertyType", e.target.value)} />
        </FormField>
        <FormField label="Стан">
          <input type="text" value={form.conditionType} onChange={(e) => update("conditionType", e.target.value)} />
        </FormField>
        <FormField label="Джерело">
          <select value={form.source} onChange={(e) => update("source", e.target.value)}>
            {SOURCE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Статус публікації">
          <select value={form.status} onChange={(e) => update("status", e.target.value)}>
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Стан оголошення">
          <select value={form.listingStatus} onChange={(e) => update("listingStatus", e.target.value)}>
            {LIFECYCLE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Широта" hint="Необов'язково">
          <input type="number" step="any" value={form.latitude} onChange={(e) => update("latitude", e.target.value)} />
        </FormField>
        <FormField label="Довгота" hint="Необов'язково">
          <input type="number" step="any" value={form.longitude} onChange={(e) => update("longitude", e.target.value)} />
        </FormField>
      </div>

      <FormField label="Опис">
        <textarea rows={4} maxLength={2000} value={form.description} onChange={(e) => update("description", e.target.value)} />
      </FormField>

      <fieldset className="form-checkbox-row">
        <legend className="sr-only">Додаткові позначки</legend>
        <label className="checkbox-field">
          <input type="checkbox" checked={form.eOselya} onChange={(e) => update("eOselya", e.target.checked)} />
          єОселя
        </label>
        <label className="checkbox-field">
          <input type="checkbox" checked={form.hasPhotoTour} onChange={(e) => update("hasPhotoTour", e.target.checked)} />
          Фототур
        </label>
        <label className="checkbox-field">
          <input type="checkbox" checked={form.hasVideoTour} onChange={(e) => update("hasVideoTour", e.target.checked)} />
          Відеотур
        </label>
      </fieldset>

      <FormField label="Ключові переваги">
        <div className="tag-editor">
          <div className="tag-list">
            {form.highlights.map((tag) => (
              <span key={tag} className="tag-chip">
                {tag}
                <button type="button" onClick={() => removeHighlight(tag)} aria-label={`Видалити мітку ${tag}`}>
                  <Icon name="close" size={12} />
                </button>
              </span>
            ))}
          </div>
          <div className="tag-input-row">
            <input
              type="text"
              value={highlightDraft}
              placeholder="Наприклад: ремонт, тераса"
              onChange={(e) => setHighlightDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addHighlight();
                }
              }}
            />
            <button type="button" className="btn btn-secondary" onClick={addHighlight}>
              Додати
            </button>
          </div>
        </div>
      </FormField>

      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={saving}>
          Скасувати
        </button>
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving ? "Збереження…" : isCreate ? "Створити оголошення" : "Зберегти зміни"}
        </button>
      </div>
    </form>
  );
}
