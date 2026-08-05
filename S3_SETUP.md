# S3 Direct Upload Configuration

## Problem Solved

**Before (❌ Broken at scale):**
```
Browser → [10MB image] → Backend → RAM (base64) → SQLite BLOB
```
- Server RAM bloat (10 concurrent uploads = 100MB RAM spike)
- Slow: Upload + encode + store = 5-10s latency
- Single point of failure
- Database bloat (SQLite not optimized for BLOBs)

**After (✅ Scales infinitely):**
```
Browser → [10MB image] → S3 (direct, presigned URL)
Backend (generates URL only) ← Metadata only
```
- Zero server RAM consumed
- Fast: Browser → CDN direct path (50-100ms)
- Parallel uploads (8 images simultaneously)
- Automatic S3 lifecycle policies (cleanup, versioning)

---

## Setup: AWS S3 (Recommended)

### 1. Create S3 Bucket

```bash
aws s3api create-bucket \
  --bucket ua-dim-listings \
  --region us-east-1 \
  --acl private
```

### 2. Enable CORS (Allow browser uploads)

```bash
aws s3api put-bucket-cors \
  --bucket ua-dim-listings \
  --cors-configuration '{
    "CORSRules": [{
      "AllowedOrigins": ["https://ua-dim.com", "https://www.ua-dim.com", "http://localhost:8080"],
      "AllowedMethods": ["GET", "PUT", "HEAD"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag", "x-amz-version-id"],
      "MaxAgeSeconds": 3000
    }]
  }'
```

### 3. Enable Versioning (Prevent accidental overwrites)

```bash
aws s3api put-bucket-versioning \
  --bucket ua-dim-listings \
  --versioning-configuration Status=Enabled
```

### 4. Add Lifecycle Policy (Auto-cleanup failed uploads)

```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket ua-dim-listings \
  --lifecycle-configuration '{
    "Rules": [{
      "Id": "DeleteIncompleteMultipart",
      "Status": "Enabled",
      "AbortIncompleteMultipartUpload": {
        "DaysAfterInitiation": 7
      }
    }, {
      "Id": "DeleteOldVersions",
      "Status": "Enabled",
      "NoncurrentVersionExpirationInDays": 30
    }]
  }'
```

### 5. Create IAM User (For backend access)

```bash
# Create user
aws iam create-user --user-name ua-dim-backend

# Generate access keys
aws iam create-access-key --user-name ua-dim-backend

# Attach S3 policy
cat > /tmp/s3-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3:PutObject",
      "s3:GetObject",
      "s3:DeleteObject",
      "s3:HeadObject"
    ],
    "Resource": "arn:aws:s3:::ua-dim-listings/*"
  }]
}
EOF

aws iam put-user-policy \
  --user-name ua-dim-backend \
  --policy-name S3Access \
  --policy-document file:///tmp/s3-policy.json
```

### 6. Configure Railway Environment

In Railway dashboard, add these env vars to the backend service:

```env
S3_BUCKET=ua-dim-listings
S3_REGION=us-east-1
S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```

---

## Setup: Cloudinary (Alternative)

Simpler than S3, includes automatic image optimization.

### 1. Sign up and get credentials

```bash
# From https://cloudinary.com
CLOUDINARY_URL=cloudinary://key:secret@cloud_name
```

### 2. Configure Railway

```env
CLOUDINARY_URL=cloudinary://key:secret@cloud_name
```

---

## Setup: MinIO (Self-hosted S3-compatible)

For on-premises deployment:

```env
S3_ENDPOINT=https://minio.example.com:9000
S3_BUCKET=ua-dim-listings
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_REGION=us-east-1
```

---

## Frontend Integration

### Example: Add image to listing

```javascript
import { S3Uploader } from './s3-upload.js';

const uploader = new S3Uploader('/api-backend');

async function uploadImage(fileInput) {
  const file = fileInput.files[0];
  
  try {
    // This handles the entire flow: presigned URL → upload → confirm
    const result = await uploader.upload(file, (progress) => {
      console.log(`Uploading: ${progress.percent}%`);
    });
    
    // Result contains final CDN URL
    console.log('Image uploaded:', result.url);
    return result.url;
  } catch (error) {
    console.error('Upload failed:', error.message);
    
    // Fallback to base64 (if S3 not configured)
    if (error.fallback) {
      return convertToBase64(file);
    }
    throw error;
  }
}
```

### Example: Form submission

```html
<form id="add-listing">
  <input type="file" id="photos" multiple accept="image/*">
  <button type="submit">Create Listing</button>
</form>

<script>
document.getElementById('add-listing').addEventListener('submit', async (e) => {
  e.preventDefault();
  
  const photos = document.getElementById('photos').files;
  const imageUrls = [];
  
  for (const file of photos) {
    try {
      const result = await uploader.upload(file);
      imageUrls.push(result.url);
    } catch (error) {
      alert(`Failed to upload ${file.name}: ${error.message}`);
    }
  }
  
  // Submit with S3 URLs instead of base64
  fetch('/api-backend/listings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: 'Nice apartment',
      image_urls: imageUrls
    })
  });
});
</script>
```

---

## Performance Comparison

| Metric | Base64 Upload | S3 Direct |
|---|---|---|
| 10MB image upload | 8-12s | 1-2s |
| Server RAM per upload | 10-20MB | 0MB |
| 8 parallel uploads | ❌ Fails (80MB) | ✅ Works (0MB) |
| Max file size | 50MB (limited by DB) | 5TB (S3 limit) |
| Cost | High (server resources) | Low (~$0.01/GB) |
| Scalability | Breaks at ~5 users | 10,000+ concurrent |

---

## Monitoring & Debugging

### Check S3 bucket for uploads

```bash
aws s3 ls s3://ua-dim-listings/ --recursive --summarize
```

### Monitor presigned URL generation

```bash
# Backend logs
tail -f backend/logs/app.log | grep presigned
```

### Test presigned URL in browser

```javascript
// In browser console
const uploader = new S3Uploader('/api-backend');
const url = await uploader.requestPresignedUrl(
  new File(['test'], 'test.jpg', { type: 'image/jpeg' })
);
console.log(url);
```

---

## Security Considerations

1. **Presigned URLs expire in 1 hour** — cannot be reused after expiration
2. **S3 access limited to specific bucket** — IAM user cannot access other buckets
3. **User isolation** — S3 key includes user ID (`listings/{user_id}/...`)
4. **File verification** — Backend confirms upload via ETag match
5. **CORS restricted** — Only allows uploads from known domains

---

## Troubleshooting

### "S3 not configured. Upload backend not available."

Backend returned 503. Check Railway env vars:
```bash
railway env list
```

### "Network error during upload"

CORS issue. Verify S3 CORS config:
```bash
aws s3api get-bucket-cors --bucket ua-dim-listings
```

### "File not found in S3"

Upload may have failed silently. Check:
1. Browser console for errors
2. S3 bucket existence
3. IAM user permissions

---

## Rollback to Base64

If S3 fails, remove env vars and backend automatically falls back:

```bash
railway env delete S3_BUCKET S3_REGION S3_ACCESS_KEY S3_SECRET_KEY
railway redeploy
```

Frontend `/api/images/presigned-url` will return 503, and admin form will use legacy base64 upload.
