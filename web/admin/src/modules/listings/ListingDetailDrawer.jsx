import React, { useCallback, useEffect, useRef, useState } from "../../react-shim.js";
import { api } from "../../lib/apiClient.js";
import { useAsync } from "../../lib/hooks.js";
import { Drawer } from "../../components/Drawer.jsx";
import { Skeleton, ErrorState } from "../../components/States.jsx";
import { Tabs, TabPanel } from "../../components/Layout.jsx";
import { Icon } from "../../components/icons.jsx";
import {
  formatDate,
  formatPrice,
  LISTING_STATUS_LABELS,
  MODERATION_STATUS_LABELS,
  VERIFICATION_STATUS_LABELS,
} from "../../lib/format.js";
import { useToast } from "../../components/Toast.jsx";
import { hasPermission, PERMISSIONS } from "../../lib/session.js";

/**
 * Shared listing detail drawer reused by Moderation, Listings and
 * Prices/History screens: single entity-detail pattern for the whole panel.
 */
export function ListingDetailDrawer({ listingId, open, onClose, onChanged, staff, footer, initialTab = "details" }) {
  const [tab, setTab] = useState(initialTab);

  useEffect(() => {
    if (open) setTab(initialTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, listingId]);
  const { status, data, error, reload } = useAsync(
    (signal) => (listingId ? api.get(`/listings/${listingId}`, undefined, signal) : Promise.resolve(null)),
    [listingId, open],
  );
  const listing = data?.listing;
  const canWrite = hasPermission(staff, PERMISSIONS.LISTINGS_WRITE);
  const toast = useToast();
  const fileInputRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  const historyQuery = useAsync(
    (signal) =>
      tab === "history" && listingId
        ? api.get(`/listings/${listingId}/history`, undefined, signal)
        : Promise.resolve(null),
    [tab, listingId],
  );

  const handleUpload = useCallback(
    async (event) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file || !listingId) return;
      setUploading(true);
      try {
        const formData = new FormData();
        formData.append("image", file);
        await api.upload(`/listings/${listingId}/images`, formData);
        toast.success("Фото завантажено");
        reload();
        onChanged?.();
      } catch (err) {
        toast.error(err.message);
      } finally {
        setUploading(false);
      }
    },
    [listingId, reload, onChanged, toast],
  );

  const handleDeleteImage = useCallback(
    async (imageId) => {
      try {
        await api.del(`/listings/${listingId}/images/${imageId}`);
        toast.success("Фото видалено");
        reload();
        onChanged?.();
      } catch (err) {
        toast.error(err.message);
      }
    },
    [listingId, reload, onChanged, toast],
  );

  return (
    <Drawer open={open} onClose={onClose} title={listing ? listing.title : "Оголошення"} footer={footer?.(listing)} wide>
      {status === "loading" ? <Skeleton rows={5} label="Завантаження оголошення" /> : null}
      {status === "error" ? <ErrorState message={error?.message} onRetry={reload} /> : null}
      {status === "success" && listing ? (
        <>
          <Tabs
            idBase="listing-detail"
            activeId={tab}
            onChange={setTab}
            tabs={[
              { id: "details", label: "Деталі" },
              { id: "photos", label: "Фото" },
              { id: "history", label: "Історія цін" },
            ]}
          />
          <TabPanel id="details" idBase="listing-detail" active={tab === "details"}>
            <dl className="detail-grid">
              <div>
                <dt>Місто / район</dt>
                <dd>
                  {listing.city}, {listing.district}
                </dd>
              </div>
              <div>
                <dt>Ціна</dt>
                <dd>{formatPrice(listing.price)}</dd>
              </div>
              <div>
                <dt>Кімнати / площа</dt>
                <dd>
                  {listing.rooms} к. · {listing.area} м²
                </dd>
              </div>
              <div>
                <dt>Поверх</dt>
                <dd>
                  {listing.floor} / {listing.total_floors}
                </dd>
              </div>
              <div>
                <dt>Статус</dt>
                <dd>{LISTING_STATUS_LABELS[listing.status] || listing.status}</dd>
              </div>
              <div>
                <dt>Модерація</dt>
                <dd>{MODERATION_STATUS_LABELS[listing.moderation_status] || listing.moderation_status || "—"}</dd>
              </div>
              <div>
                <dt>Тип / стан</dt>
                <dd>
                  {listing.property_type} · {listing.condition_type}
                </dd>
              </div>
              <div>
                <dt>Джерело</dt>
                <dd>{listing.source || "—"}</dd>
              </div>
              <div>
                <dt>Створено</dt>
                <dd>{formatDate(listing.created_at)}</dd>
              </div>
              <div>
                <dt>Перегляди</dt>
                <dd>{listing.views ?? 0}</dd>
              </div>
            </dl>
            {listing.description ? (
              <div className="detail-description">
                <h4>Опис</h4>
                <p>{listing.description}</p>
              </div>
            ) : null}
          </TabPanel>
          <TabPanel id="photos" idBase="listing-detail" active={tab === "photos"}>
            <div className="photo-grid">
              {(listing.images || []).map((image) => (
                <figure key={image.id} className="photo-tile">
                  <img src={image.image_url} alt="" loading="lazy" />
                  {canWrite ? (
                    <button
                      type="button"
                      className="btn btn-icon photo-remove"
                      onClick={() => handleDeleteImage(image.id)}
                      aria-label="Видалити фото"
                    >
                      <Icon name="trash" size={14} />
                    </button>
                  ) : null}
                </figure>
              ))}
              {!(listing.images || []).length ? <p className="empty-inline">Фото ще не додано.</p> : null}
            </div>
            {canWrite ? (
              <div className="photo-upload">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  id="listing-photo-upload"
                  className="sr-only"
                  onChange={handleUpload}
                />
                <label htmlFor="listing-photo-upload" className="btn btn-secondary">
                  <Icon name="upload" size={15} />
                  {uploading ? "Завантаження…" : "Додати фото"}
                </label>
              </div>
            ) : null}
          </TabPanel>
          <TabPanel id="history" idBase="listing-detail" active={tab === "history"}>
            {historyQuery.status === "loading" ? <Skeleton rows={3} /> : null}
            {historyQuery.status === "error" ? (
              <ErrorState message={historyQuery.error?.message} onRetry={historyQuery.reload} />
            ) : null}
            {historyQuery.status === "success" ? (
              historyQuery.data?.history?.length ? (
                <ul className="history-list">
                  {historyQuery.data.history.map((entry, index) => (
                    <li key={index} className="history-row">
                      <span className="history-field">{entry.field_name}</span>
                      <span className="history-change">
                        {entry.old_value ?? "—"} → {entry.new_value ?? "—"}
                      </span>
                      <span className="history-meta">
                        {formatDate(entry.changed_at)} · {entry.changed_by || "система"}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-inline">Змін ще не зафіксовано.</p>
              )
            ) : null}
          </TabPanel>
          {listing.owner_verification_status || listing.phone_verification_status ? (
            <p className="verification-inline">
              Власник: {VERIFICATION_STATUS_LABELS[listing.owner_verification_status] || "—"} · Телефон:{" "}
              {VERIFICATION_STATUS_LABELS[listing.phone_verification_status] || "—"}
            </p>
          ) : null}
        </>
      ) : null}
    </Drawer>
  );
}
