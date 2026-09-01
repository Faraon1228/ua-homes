import React, { useEffect, useMemo, useRef, useState } from "../react-shim.js";

let leafletLoader = null;

function ensureLeafletLoaded() {
  if (window.L?.map) return Promise.resolve(window.L);
  if (leafletLoader) return leafletLoader;

  leafletLoader = new Promise((resolve, reject) => {
    if (!document.getElementById("uah-leaflet-css")) {
      const link = document.createElement("link");
      link.id = "uah-leaflet-css";
      link.rel = "stylesheet";
      link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(link);
    }

    const existingScript = document.getElementById("uah-leaflet-js");
    if (existingScript) {
      existingScript.addEventListener("load", () => resolve(window.L), { once: true });
      existingScript.addEventListener(
        "error",
        () => reject(new Error("Не вдалося завантажити карту")),
        { once: true },
      );
      return;
    }

    const script = document.createElement("script");
    script.id = "uah-leaflet-js";
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.async = true;
    script.onload = () => resolve(window.L);
    script.onerror = () => reject(new Error("Не вдалося завантажити карту"));
    document.head.appendChild(script);
  });

  return leafletLoader;
}

let leafletDivIcon = null;

function getMarkerDivIcon(Leaflet) {
  // CSP blocks Leaflet's default marker PNGs from unpkg.com — use an inline SVG divIcon instead.
  if (!leafletDivIcon) {
    leafletDivIcon = Leaflet.divIcon({
      className: "",
      html:
        '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="40" viewBox="0 0 28 40" aria-hidden="true">' +
        '<path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.3 21.7 0 14 0z" fill="#1d4ed8"/>' +
        '<circle cx="14" cy="14" r="6" fill="#ffffff"/></svg>',
      iconSize: [28, 40],
      iconAnchor: [14, 40],
      popupAnchor: [0, -36],
    });
  }
  return leafletDivIcon;
}

function hasMapCoordinates(property) {
  const latitude = Number(property?.latitude);
  const longitude = Number(property?.longitude);
  return (
    Number.isFinite(latitude) &&
    Number.isFinite(longitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180 &&
    !(latitude === 0 && longitude === 0)
  );
}

export default function ListingsMapView({ properties, onShowList }) {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const markersLayerRef = useRef(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState("");
  const mappedProperties = useMemo(
    () => properties.filter(hasMapCoordinates),
    [properties],
  );
  const missingCoordinatesCount = properties.length - mappedProperties.length;

  useEffect(() => {
    let cancelled = false;
    ensureLeafletLoaded()
      .then((Leaflet) => {
        if (cancelled || !mapContainerRef.current || mapRef.current) return;
        const map = Leaflet.map(mapContainerRef.current, {
          zoomControl: true,
        }).setView([49.0, 31.2], 6);
        Leaflet.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 18,
          attribution: "&copy; OpenStreetMap",
        }).addTo(map);
        mapRef.current = map;
        markersLayerRef.current = Leaflet.layerGroup().addTo(map);
        setMapReady(true);
        window.requestAnimationFrame(() => map.invalidateSize());
      })
      .catch((error) => {
        if (!cancelled) {
          setMapError(error.message || "Не вдалося завантажити карту");
        }
      });

    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
      markersLayerRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!mapReady || !mapRef.current || !markersLayerRef.current || !window.L) return;
    const markersLayer = markersLayerRef.current;
    markersLayer.clearLayers();
    const bounds = [];

    mappedProperties.forEach((property) => {
      const point = [Number(property.latitude), Number(property.longitude)];
      const marker = window.L.marker(point, {
        icon: getMarkerDivIcon(window.L),
        title: property.title,
        alt: `${property.title}, ${property.city}, ${property.district}`,
        keyboard: false,
      });
      const popup = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = property.title;
      const details = document.createElement("p");
      details.style.margin = "6px 0 0";
      details.textContent = `$${property.price.toLocaleString("uk-UA")} · ${property.city}, ${property.district}`;
      popup.append(title, details);
      marker.bindPopup(popup);
      markersLayer.addLayer(marker);
      bounds.push(point);
    });

    if (bounds.length) {
      mapRef.current.fitBounds(bounds, { padding: [32, 32], maxZoom: 14 });
    } else {
      mapRef.current.setView([49.0, 31.2], 6);
    }
    window.requestAnimationFrame(() => mapRef.current?.invalidateSize());
  }, [mapReady, mappedProperties]);

  return (
    <div
      id="listings-map"
      aria-busy={!mapReady && !mapError}
      className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm"
    >
      <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-black text-slate-900">
            На карті {mappedProperties.length} з {properties.length} об&apos;єктів
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {!properties.length
              ? "Немає результатів для відображення."
              : missingCoordinatesCount
                ? `${missingCoordinatesCount} без координат залишаються доступними у списку.`
                : "Усі результати мають координати."}
          </p>
        </div>
        {missingCoordinatesCount ? (
          <button
            type="button"
            onClick={onShowList}
            className="self-start rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-bold text-blue-700 sm:self-auto"
          >
            Показати весь список
          </button>
        ) : null}
      </div>
      <p id="map-access-help" className="sr-only">
        Оголошення на карті доступні як посилання нижче та в режимі списку.
      </p>
      <ul className="sr-only">
        {mappedProperties.map((property) => (
          <li key={`map-access-${property.id}`}>
            <a href={`/listing/${property.id}`}>
              {property.title}, {property.city}, {property.district}
            </a>
          </li>
        ))}
      </ul>
      {mapError ? (
        <div role="alert" className="px-5 py-16 text-center">
          <p className="font-bold text-rose-700">{mapError}</p>
          <button
            type="button"
            onClick={onShowList}
            className="mt-4 rounded-xl bg-slate-900 px-4 py-2 text-sm font-bold text-white"
          >
            Повернутися до списку
          </button>
        </div>
      ) : (
        <div className="relative">
          <div
            ref={mapContainerRef}
            className="h-[420px] w-full sm:h-[520px]"
            role="region"
            aria-label={`Карта результатів: координати мають ${mappedProperties.length} із ${properties.length}`}
            aria-describedby="map-access-help"
          />
          {!mapReady ? (
            <div className="absolute inset-0 grid place-items-center bg-slate-50">
              <p role="status" className="text-sm font-semibold text-slate-600">
                Завантажуємо карту…
              </p>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
