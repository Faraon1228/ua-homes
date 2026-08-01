/**
 * Google Maps Integration for UA-Dim
 * Features:
 * - Display properties on map
 * - Marker clustering
 * - Info windows with property details
 * - Geo-search (radius-based filtering)
 * - Metro/Transport layer
 */

// Configuration
const GOOGLE_MAPS_CONFIG = {
  KEY: 'YOUR_GOOGLE_MAPS_API_KEY', // Set this!
  CENTER_UKRAINE: { lat: 48.8566, lng: 34.8025 }, // Ukraine center
  CENTER_KYIV: { lat: 50.4501, lng: 30.5234 },
  ZOOM_DEFAULT: 12,
  ZOOM_CITY: 13,
  ZOOM_DISTRICT: 14,
};

// Marker colors for different property types
const MARKER_COLORS = {
  apartment: '#1e40af',    // Blue
  house: '#16a34a',        // Green
  office: '#ea580c',       // Orange
  land: '#8b5cf6',         // Purple
};

/**
 * Initialize Google Map
 * @param {string} elementId - Container ID
 * @param {Array} properties - Property objects with lat/lng
 * @param {Object} options - Map options
 */
function initializePropertyMap(elementId, properties = [], options = {}) {
  const mapContainer = document.getElementById(elementId);
  
  if (!mapContainer) {
    console.error(`Element with ID "${elementId}" not found`);
    return null;
  }

  // Default map options
  const mapOptions = {
    zoom: options.zoom || GOOGLE_MAPS_CONFIG.ZOOM_DEFAULT,
    center: options.center || GOOGLE_MAPS_CONFIG.CENTER_KYIV,
    mapTypeControl: true,
    fullscreenControl: true,
    streetViewControl: false,
    styles: [
      {
        featureType: 'water',
        elementType: 'geometry',
        stylers: [{ color: '#c9c9c9' }],
      },
      {
        featureType: 'land',
        elementType: 'geometry',
        stylers: [{ color: '#f3f3f3' }],
      },
    ],
  };

  const map = new google.maps.Map(mapContainer, mapOptions);

  // Add properties to map
  if (properties && properties.length > 0) {
    addPropertiesToMap(map, properties);
  }

  return map;
}

/**
 * Add property markers to map
 * @param {google.maps.Map} map
 * @param {Array} properties
 */
function addPropertiesToMap(map, properties) {
  const markerClusterer = new MarkerClusterer({
    map: map,
    markers: [],
  });

  const infoWindows = [];

  properties.forEach((property) => {
    if (!property.latitude || !property.longitude) {
      console.warn(`Property ${property.id} missing coordinates`);
      return;
    }

    // Create custom marker
    const marker = new google.maps.Marker({
      position: {
        lat: parseFloat(property.latitude),
        lng: parseFloat(property.longitude),
      },
      title: property.title,
      map: map,
      icon: createMarkerIcon(property.type || 'apartment'),
    });

    // Create info window content
    const infoWindowContent = createInfoWindowContent(property);
    const infoWindow = new google.maps.InfoWindow({
      content: infoWindowContent,
      maxWidth: 300,
    });

    // Open info window on marker click
    marker.addListener('click', () => {
      // Close all other info windows
      infoWindows.forEach((iw) => iw.close());
      infoWindow.open(map, marker);
    });

    infoWindows.push(infoWindow);
    markerClusterer.addMarker(marker);
  });

  return markerClusterer;
}

/**
 * Create custom marker icon
 * @param {string} propertyType
 * @returns {google.maps.Icon}
 */
function createMarkerIcon(propertyType) {
  const color = MARKER_COLORS[propertyType] || MARKER_COLORS.apartment;

  return {
    path: google.maps.SymbolPath.CIRCLE,
    fillColor: color,
    fillOpacity: 0.8,
    strokeColor: '#fff',
    strokeWeight: 2,
    scale: 8,
  };
}

/**
 * Create info window HTML content
 * @param {Object} property
 * @returns {string}
 */
function createInfoWindowContent(property) {
  const priceFormatted = new Intl.NumberFormat('uk-UA', {
    style: 'currency',
    currency: 'UAH',
    minimumFractionDigits: 0,
  }).format(property.price);

  const eOselyaBadge = property.eOselya
    ? '<span style="background: #1e40af; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; margin-left: 4px;">єОселя</span>'
    : '';

  return `
    <div style="font-family: Arial, sans-serif; padding: 8px; max-width: 280px;">
      <div style="display: flex; justify-content: space-between; align-items: start;">
        <h3 style="margin: 0 0 8px 0; font-size: 14px; font-weight: bold;">
          ${property.title}
        </h3>
        ${eOselyaBadge}
      </div>
      
      <div style="background: #f0f0f0; padding: 8px; border-radius: 4px; margin-bottom: 8px;">
        <div style="font-size: 16px; font-weight: bold; color: #1e40af;">
          ${priceFormatted}
        </div>
        <div style="font-size: 12px; color: #666; margin-top: 2px;">
          ${property.rooms || 'N/A'} кім | ${property.area || 'N/A'} м²
        </div>
      </div>

      <div style="font-size: 12px; color: #666; margin-bottom: 6px;">
        <div><strong>📍 ${property.district || 'Unknown'}, ${property.city || 'Unknown'}</strong></div>
        ${property.address ? `<div>${property.address}</div>` : ''}
        ${property.metroDistance ? `<div>🚇 ${property.metroDistance} м до метро</div>` : ''}
      </div>

      <button onclick="openPropertyDetails(${property.id})" style="
        width: 100%;
        padding: 8px;
        background: #1e40af;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-weight: bold;
        font-size: 12px;
      ">
        Дивитися деталі →
      </button>
    </div>
  `;
}

/**
 * Filter properties by radius (geo-search)
 * @param {google.maps.Map} map
 * @param {Object} center - {lat, lng}
 * @param {number} radiusMeters
 * @param {Array} properties
 * @returns {Array} Filtered properties
 */
function filterPropertiesByRadius(center, radiusMeters, properties) {
  const earthRadiusMeters = 6371000;

  return properties.filter((prop) => {
    if (!prop.latitude || !prop.longitude) return false;

    const lat1 = (center.lat * Math.PI) / 180;
    const lat2 = (prop.latitude * Math.PI) / 180;
    const dLat = ((prop.latitude - center.lat) * Math.PI) / 180;
    const dLng = ((prop.longitude - center.lng) * Math.PI) / 180;

    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1) *
        Math.cos(lat2) *
        Math.sin(dLng / 2) *
        Math.sin(dLng / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    const distance = earthRadiusMeters * c;

    return distance <= radiusMeters;
  });
}

/**
 * Geocode address to coordinates
 * @param {string} address
 * @returns {Promise<Object>} {lat, lng}
 */
async function geocodeAddress(address) {
  const geocoder = new google.maps.Geocoder();

  return new Promise((resolve, reject) => {
    geocoder.geocode({ address }, (results, status) => {
      if (status === 'OK') {
        const location = results[0].geometry.location;
        resolve({
          lat: location.lat(),
          lng: location.lng(),
        });
      } else {
        reject(new Error(`Geocoding failed: ${status}`));
      }
    });
  });
}

/**
 * Reverse geocode coordinates to address
 * @param {Object} location - {lat, lng}
 * @returns {Promise<string>} Address
 */
async function reverseGeocodeLocation(location) {
  const geocoder = new google.maps.Geocoder();

  return new Promise((resolve, reject) => {
    geocoder.geocode({ location }, (results, status) => {
      if (status === 'OK' && results[0]) {
        resolve(results[0].formatted_address);
      } else {
        reject(new Error(`Reverse geocoding failed: ${status}`));
      }
    });
  });
}

/**
 * Draw circle on map (for radius search)
 * @param {google.maps.Map} map
 * @param {Object} center - {lat, lng}
 * @param {number} radiusMeters
 */
function drawSearchRadius(map, center, radiusMeters) {
  return new google.maps.Circle({
    strokeColor: '#1e40af',
    strokeOpacity: 0.8,
    strokeWeight: 2,
    fillColor: '#1e40af',
    fillOpacity: 0.05,
    map: map,
    center: center,
    radius: radiusMeters,
  });
}

/**
 * Calculate distance between two coordinates
 * @param {Object} point1 - {lat, lng}
 * @param {Object} point2 - {lat, lng}
 * @returns {number} Distance in meters
 */
function calculateDistance(point1, point2) {
  const earthRadiusMeters = 6371000;

  const lat1 = (point1.lat * Math.PI) / 180;
  const lat2 = (point2.lat * Math.PI) / 180;
  const dLat = ((point2.lat - point1.lat) * Math.PI) / 180;
  const dLng = ((point2.lng - point1.lng) * Math.PI) / 180;

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1) *
      Math.cos(lat2) *
      Math.sin(dLng / 2) *
      Math.sin(dLng / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

  return earthRadiusMeters * c;
}

// Export functions
window.propertyMapFunctions = {
  initializePropertyMap,
  addPropertiesToMap,
  filterPropertiesByRadius,
  geocodeAddress,
  reverseGeocodeLocation,
  drawSearchRadius,
  calculateDistance,
};
