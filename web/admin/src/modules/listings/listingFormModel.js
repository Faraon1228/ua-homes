export function buildListingPayload(form, { isCreate }) {
  const base = {
    title: form.title.trim(),
    city: form.city.trim(),
    district: form.district.trim(),
    price: Number(form.price),
    rooms: Number(form.rooms),
    area: Number(form.area),
    floor: form.floor !== "" ? Number(form.floor) : 1,
    total_floors: form.totalFloors !== "" ? Number(form.totalFloors) : 1,
    year_built: form.yearBuilt !== "" ? Number(form.yearBuilt) : null,
    e_oselya: !!form.eOselya,
    description: form.description || "",
    property_type: form.propertyType || "квартира",
    condition_type: form.conditionType || "вторинка",
    status: form.status || "draft",
    listing_status: form.listingStatus || "active",
    latitude: form.latitude !== "" ? Number(form.latitude) : null,
    longitude: form.longitude !== "" ? Number(form.longitude) : null,
    source: form.source || "owner",
  };
  if (isCreate) {
    return {
      ...base,
      hasPhotoTour: !!form.hasPhotoTour,
      hasVideoTour: !!form.hasVideoTour,
      highlights: form.highlights || [],
      captureMode: form.captureMode || "off_site",
    };
  }
  return {
    ...base,
    has_photo_tour: !!form.hasPhotoTour,
    has_video_tour: !!form.hasVideoTour,
    listing_highlights: form.highlights || [],
    capture_mode: form.captureMode || "off_site",
  };
}

export const EMPTY_LISTING_FORM = {
  title: "",
  city: "",
  district: "",
  price: "",
  rooms: "",
  area: "",
  floor: "1",
  totalFloors: "1",
  yearBuilt: "",
  eOselya: false,
  description: "",
  propertyType: "квартира",
  conditionType: "вторинка",
  status: "draft",
  listingStatus: "active",
  latitude: "",
  longitude: "",
  source: "owner",
  hasPhotoTour: false,
  hasVideoTour: false,
  highlights: [],
  captureMode: "off_site",
};

export function listingToForm(listing) {
  let highlights = [];
  const raw = listing.listing_highlights;
  if (Array.isArray(raw)) highlights = raw;
  else if (typeof raw === "string" && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) highlights = parsed;
    } catch {
      highlights = [];
    }
  }
  return {
    title: listing.title || "",
    city: listing.city || "",
    district: listing.district || "",
    price: String(listing.price ?? ""),
    rooms: String(listing.rooms ?? ""),
    area: String(listing.area ?? ""),
    floor: String(listing.floor ?? "1"),
    totalFloors: String(listing.total_floors ?? "1"),
    yearBuilt: listing.year_built != null ? String(listing.year_built) : "",
    eOselya: !!listing.e_oselya,
    description: listing.description || "",
    propertyType: listing.property_type || "квартира",
    conditionType: listing.condition_type || "вторинка",
    status: listing.status || "draft",
    listingStatus: listing.listing_status || "active",
    latitude: listing.latitude != null ? String(listing.latitude) : "",
    longitude: listing.longitude != null ? String(listing.longitude) : "",
    source: listing.source || "owner",
    hasPhotoTour: !!listing.has_photo_tour,
    hasVideoTour: !!listing.has_video_tour,
    highlights,
    captureMode: listing.capture_mode || "off_site",
  };
}
