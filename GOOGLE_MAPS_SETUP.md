# 🗺️ Google Maps Integration Guide

## Step 1: Get Google Maps API Key

1. Go to: https://console.cloud.google.com
2. Create a new project named "UA Homes"
3. Enable these APIs:
   - Maps JavaScript API
   - Places API
   - Geocoding API
4. Create an API Key (Credentials → Create Credentials → API Key)
5. Restrict to: JavaScript origins → Add `https://ua-homes.netlify.app`

**Cost:** $200/month free, then ~$7 per 1000 requests

---

## Step 2: Add to HTML (real-estate-demo.html)

Replace `YOUR_GOOGLE_MAPS_API_KEY` with your actual key:

```html
<!-- Add this in <head> section -->
<script src="https://maps.googleapis.com/maps/api/js?key=YOUR_GOOGLE_MAPS_API_KEY&libraries=marker,clustering"></script>
<script src="https://unpkg.com/@googlemaps/markerclusterer@2.0.0/dist/index.min.js"></script>

<!-- Add before closing </body> -->
<script src="property-map.js"></script>
```

---

## Step 3: Add Map Container to UI

Add this HTML where you want the map (usually in the listings section):

```html
<!-- Map section (add after filters) -->
<section class="bg-white mt-8 rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
  <div class="flex justify-between items-center p-4 border-b border-gray-200">
    <h2 class="text-lg font-bold">🗺️ Квартири на карті</h2>
    <button onclick="toggleMapView()" class="text-blue-600 hover:text-blue-700 font-medium text-sm">
      Перемкнути вид
    </button>
  </div>
  <div id="propertyMap" style="width: 100%; height: 500px; background: #f0f0f0;"></div>
</section>
```

---

## Step 4: Initialize Map in JavaScript

```javascript
// Initialize map after page loads
document.addEventListener('DOMContentLoaded', function() {
  // Fetch listings from API
  fetch('/api/map/listings?city=Київ')
    .then(res => res.json())
    .then(data => {
      // Initialize map with listings
      const map = propertyMapFunctions.initializePropertyMap(
        'propertyMap',
        data.listings,
        {
          zoom: 12,
          center: { lat: 50.4501, lng: 30.5234 } // Kyiv
        }
      );
    })
    .catch(err => console.error('Map error:', err));
});

// Toggle between list and map view
function toggleMapView() {
  const grid = document.querySelector('[grid layout]');
  const map = document.getElementById('propertyMap');
  
  if (map.style.display === 'none') {
    map.style.display = 'block';
    grid.style.display = 'none';
  } else {
    map.style.display = 'none';
    grid.style.display = 'grid';
  }
}

// Open property details when clicking "View Details" in info window
function openPropertyDetails(propertyId) {
  window.location.href = `/real-estate-demo.html?property=${propertyId}`;
  // Or open modal:
  // fetchAndShowPropertyModal(propertyId);
}
```

---

## Step 5: Geo-Search Feature

Add radius search to filters:

```javascript
// Get user's location
function geoSearch(radiusKm = 5) {
  navigator.geolocation.getCurrentPosition(
    function(position) {
      const lat = position.coords.latitude;
      const lng = position.coords.longitude;
      
      // Fetch listings within radius
      fetch(`/api/map/listings?lat=${lat}&lng=${lng}&radius=${radiusKm * 1000}`)
        .then(res => res.json())
        .then(data => {
          console.log(`Found ${data.count} listings within ${radiusKm}km`);
          // Update map with filtered listings
          propertyMapFunctions.initializePropertyMap(
            'propertyMap',
            data.listings
          );
          
          // Show radius circle on map
          const map = propertyMapFunctions.drawSearchRadius(
            map,
            { lat, lng },
            radiusKm * 1000
          );
        });
    },
    function(error) {
      console.error('Geolocation error:', error);
      alert('Будь ласка, дозвольте доступ до вашої локації');
    }
  );
}

// Add button to trigger geo-search
// <button onclick="geoSearch(5)">🎯 Пошук навколо мене (5 км)</button>
```

---

## Step 6: Update Backend (Already Done!)

The backend now has a new endpoint:
```
GET /api/map/listings?city=Київ&minPrice=100000&maxPrice=500000&lat=50.45&lng=30.52&radius=5000
```

Returns listings with coordinates for map display.

---

## Step 7: Deploy & Test

1. Replace API key in HTML
2. Deploy to Netlify (automatically)
3. Test in browser: Open DevTools → Map should appear
4. Click markers to see property details

---

## Features Included

✅ Marker clustering (thousands of markers)
✅ Info windows with property details
✅ Geo-search by radius
✅ Distance calculation
✅ Custom marker colors by property type
✅ Toggle between list and map view
✅ Click property to view details

---

## Next Steps

1. **Real Data:** Replace mock data with real listings from:
   - OLX.ua API
   - Яких.ua API
   - Direct from real estate agents
   - CSV import via admin panel

2. **Advanced Features:**
   - Heatmap (concentration of properties)
   - Transit overlay (metro stations)
   - School/Park/Hospital filters
   - Street view integration
   - 3D building view

3. **Mobile Optimization:**
   - Smaller map for mobile (300px height)
   - Tap to expand
   - Location tracking

---

## Troubleshooting

**Map not showing?**
- Check API key is valid
- Check domain is whitelisted in Google Console
- Open DevTools → Console for errors

**Markers not appearing?**
- Check listings have latitude/longitude
- Verify coordinates are in correct format
- Check SQL queries return data

**Slow performance?**
- Use marker clustering (included)
- Limit to 500 listings at a time
- Implement pagination
- Cache results

---

**Remember:** Keep API key safe! Rotate regularly!
