# Image & Video Optimization Pipeline

## Architecture Overview

```
User Upload Flow:
1. Browser: GET /api/images/presigned-url
   → Backend: returns S3 upload URL (valid 1 hour)

2. Browser: PUT file directly to S3 (presigned URL)
   → S3: stores original image

3. Browser: POST /api/images/confirm-upload
   → Backend: verifies file exists, returns CDN URL

4. [NEW] Browser: POST /api/images/optimize
   → Backend: downloads from S3 → creates variants (WebP/AVIF) → uploads all → returns URLs

5. Browser: Create listing with all image URLs
   → Backend: stores listing with optimized image references
```

## Image Optimization Details

### What Happens

**Input:** Original uploaded image (JPEG, PNG, WebP)
- Size: ~1-5 MB
- Format: Any (will convert to RGB if needed)

**Processing:**
1. Resize to 3 dimensions:
   - **Thumbnail:** 150×100 px (micro previews)
   - **Medium:** 400×300 px (catalog cards)
   - **Large:** 1200×800 px (detail page)

2. Convert to modern formats:
   - **WebP:** ~50% smaller than JPEG, supported in 95% browsers
   - **AVIF:** ~30% smaller than WebP, emerging standard (Chrome/Firefox/Opera)

3. Optimize compression:
   - WebP quality: 80/100 (minimal visible loss)
   - AVIF quality: 75/100 (even more aggressive)

**Output:** 6 image URLs per original
```
photo-thumbnail.webp  (e.g., 15 KB)
photo-thumbnail.avif  (e.g., 12 KB)
photo-medium.webp     (e.g., 35 KB)
photo-medium.avif     (e.g., 28 KB)
photo-large.webp      (e.g., 120 KB)
photo-large.avif      (e.g., 90 KB)
```

### Performance Impact

| Metric | Original | WebP | AVIF | Ratio |
|---|---|---|---|---|
| 2MP JPEG (2.0 MB) | 2.0 MB | 1.0 MB | 0.7 MB | -65% |
| 4MP JPEG (3.5 MB) | 3.5 MB | 1.8 MB | 1.2 MB | -66% |
| Load time (4G) | 8s | 4s | 2.8s | -65% |

**For a listing with 8 photos:**
- Before: 8 × 2MB = 16 MB download
- After: 8 × 0.7MB = 5.6 MB download
- **Savings: 10.4 MB per listing (-65%)**

### Frontend Integration

```javascript
// After S3 upload succeeds
const uploader = new S3Uploader('/api-backend');

// 1. Upload original to S3
const result = await uploader.upload(file);
const originalUrl = result.url;  // https://bucket.../photo.jpg

// 2. Create optimized variants
const optimized = await fetch('/api-backend/images/optimize', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  credentials: 'include',
  body: JSON.stringify({ key: 'listings/123/abc/photo.jpg' })
}).then(r => r.json());

// optimized = {
//   thumbnail_webp: "https://bucket.../photo-thumbnail.webp",
//   thumbnail_avif: "https://bucket.../photo-thumbnail.avif",
//   medium_webp: "...",
//   medium_avif: "...",
//   large_webp: "...",
//   large_avif: "...",
//   metadata: { compression_ratio: 65, ... }
// }

// 3. Use in HTML with <picture> element
```

### HTML Usage (Picture Element)

```html
<!-- Responsive images with format fallback -->
<picture>
  <!-- Modern browsers: use AVIF -->
  <source srcset="photo-medium.avif 400w, photo-large.avif 1200w" type="image/avif">
  
  <!-- Fallback to WebP -->
  <source srcset="photo-medium.webp 400w, photo-large.webp 1200w" type="image/webp">
  
  <!-- Final fallback to original -->
  <img src="photo-original.jpg" alt="Listing" sizes="(max-width: 768px) 400px, 1200px">
</picture>
```

## Video Optimization (Future)

### Planned Architecture

```
User Upload Video Flow:
1. Browser: GET /api/videos/presigned-url → returns S3 URL (15 min timeout)
2. Browser: PUT video directly to S3
3. Browser: POST /api/videos/confirm-upload
4. Backend: Triggers async FFmpeg job
5. Backend: Creates variants (720p + 1080p H.264)
6. Backend: Uploads to S3 + returns M3U8 HLS playlist
7. Frontend: Plays HLS stream with quality selector
```

### Specifications

**Codec:**
- Video: H.264 (maximum compatibility)
- Audio: AAC-LC (48 kHz)

**Bitrates:**
- 720p: 2.5 Mbps video + 128 kbps audio
- 1080p: 6 Mbps video + 128 kbps audio

**Container:** MP4 (single file) or HLS (segmented for streaming)

**Processing:**
- Runs async on backend (doesn't block upload)
- Can integrate with Mux, Cloudflare Stream, or self-hosted FFmpeg
- Stores HLS playlist on S3 for CDN delivery

**Example Response:**
```json
{
  "hlsPlaylist": "https://cdn.../listings/123/abc/tour.m3u8",
  "variants": {
    "720p": "https://cdn.../listings/123/abc/tour-720p.mp4",
    "1080p": "https://cdn.../listings/123/abc/tour-1080p.mp4"
  },
  "duration": 125,
  "metadata": {
    "width": 1920,
    "height": 1080,
    "bitrate": 8000,
    "format": "h.264/aac"
  }
}
```

## Configuration

### Enable Image Optimization

1. Install dependencies:
```bash
pip install Pillow pillow-heif
```

2. Deploy to Railway:
```bash
git push
# Railway auto-redeploy with Pillow support
```

3. Test:
```bash
curl -X POST https://ua-dim.com/api-backend/images/optimize \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{"key": "listings/123/abc/photo.jpg"}'
```

### Disable Image Optimization (Fallback)

If Pillow fails to install, `/api/images/optimize` returns 503 and frontend falls back to original image.

## Monitoring

### Check S3 for variants
```bash
aws s3 ls s3://ua-dim-listings/listings/ --recursive | grep "\-thumbnail\|\-medium\|\-large"
```

### Monitor backend logs
```bash
tail -f backend/logs/app.log | grep "Image optimization"
```

### S3 Storage Costs

Estimate for 1000 listings × 8 images = 8000 total images:

| Format | Size | Count | Total |
|---|---|---|---|
| Original (JPEG) | 1.0 MB | 8,000 | 8.0 TB |
| Thumbnail WebP | 0.015 MB | 8,000 | 120 GB |
| Thumbnail AVIF | 0.012 MB | 8,000 | 96 GB |
| Medium WebP | 0.035 MB | 8,000 | 280 GB |
| Medium AVIF | 0.028 MB | 8,000 | 224 GB |
| Large WebP | 0.12 MB | 8,000 | 960 GB |
| Large AVIF | 0.09 MB | 8,000 | 720 GB |
| **Total** | - | - | **~11 TB** |

**Monthly S3 Cost (us-east-1):**
- Storage: 11 TB × $0.023/GB = **$253/month**
- GET requests: 10M × $0.0004/1K = **$4/month**
- PUT requests: 60K × $0.005/1K = **$0.30/month**
- **Total: ~$260/month**

With CloudFront CDN: +$0.085/GB delivered (optional, for faster global delivery)

## Troubleshooting

### "Image optimization not available"
Pillow not installed. Run: `pip install Pillow`

### "AVIF conversion skipped"
Optional library not available. AVIF variants won't be created, but WebP will work.

### Optimization fails silently
Check backend logs: `railway logs`

### Images not appearing in listing
Verify URLs in database:
```sql
SELECT image_urls FROM listings WHERE id = 123;
```

Should contain array of WebP/AVIF URLs.

---

## Next Steps

- [ ] Enable S3 on Railway with credentials
- [ ] Test image optimization pipeline
- [ ] Update frontend to use WebP/AVIF URLs
- [ ] Implement video optimization (FFmpeg integration)
- [ ] Set up CloudFront CDN for global delivery
- [ ] Monitor S3 costs vs. performance gains
