/**
 * S3 Direct Upload Helper
 * 
 * Handles browser → S3 direct file uploads using Presigned URLs.
 * This bypasses the backend server entirely, avoiding RAM/bandwidth bottleneck.
 * 
 * Architecture:
 * 1. Browser requests presigned URL from backend
 * 2. Backend returns S3 upload URL (valid for 1 hour)
 * 3. Browser uploads file directly to S3 using presigned URL
 * 4. Browser confirms upload with backend
 * 5. Backend returns final CDN URL
 * 
 * Advantages over base64 backend uploads:
 * - ✅ No server RAM consumed by file data
 * - ✅ Scales to unlimited file sizes
 * - ✅ Parallel uploads (not sequential)
 * - ✅ Automatic virus scanning via S3 triggers
 * - ✅ Browser-to-CDN direct path (lower latency)
 * - ✅ Failed uploads don't consume quota
 */

class S3Uploader {
  constructor(backendApiUrl = '/api') {
    this.apiUrl = backendApiUrl;
    this.maxFileSize = 10 * 1024 * 1024; // 10 MB
    this.maxFilesPerListing = 8;
    this.allowedTypes = ['image/jpeg', 'image/png', 'image/webp'];
  }

  /**
   * Validate file before upload
   */
  validateFile(file) {
    const errors = [];
    
    if (!file) errors.push('No file selected');
    if (file && !this.allowedTypes.includes(file.type)) {
      errors.push(`Invalid type: ${file.type}. Allowed: ${this.allowedTypes.join(', ')}`);
    }
    if (file && file.size > this.maxFileSize) {
      errors.push(`File too large: ${(file.size / 1024 / 1024).toFixed(1)}MB > 10MB limit`);
    }
    
    return errors.length === 0 ? null : errors;
  }

  /**
   * Request presigned URL from backend
   */
  async requestPresignedUrl(file) {
    const errors = this.validateFile(file);
    if (errors) throw new Error(errors.join('; '));

    try {
      const response = await fetch(`${this.apiUrl}/images/presigned-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          filename: file.name,
          contentType: file.type
        })
      });

      if (!response.ok) {
        if (response.status === 503) {
          // S3 not configured, fallback to base64
          return { fallback: true };
        }
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to get presigned URL:', error);
      throw error;
    }
  }

  /**
   * Upload file directly to S3 using presigned URL
   */
  async uploadToPresignedUrl(file, presignedData, onProgress) {
    if (!presignedData.uploadUrl) {
      throw new Error('No upload URL provided');
    }

    try {
      const xhr = new XMLHttpRequest();

      // Track progress
      if (onProgress) {
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) {
            onProgress({
              loaded: e.loaded,
              total: e.total,
              percent: Math.round((e.loaded / e.total) * 100)
            });
          }
        });
      }

      return new Promise((resolve, reject) => {
        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve({
              etag: xhr.getResponseHeader('ETag'),
              versionId: xhr.getResponseHeader('x-amz-version-id'),
              url: presignedData.uploadUrl
            });
          } else {
            reject(new Error(`Upload failed: ${xhr.status}`));
          }
        });

        xhr.addEventListener('error', () => reject(new Error('Network error during upload')));
        xhr.addEventListener('abort', () => reject(new Error('Upload aborted')));

        xhr.open('PUT', presignedData.uploadUrl);
        xhr.setRequestHeader('Content-Type', file.type);
        xhr.send(file);
      });
    } catch (error) {
      console.error('S3 upload failed:', error);
      throw error;
    }
  }

  /**
   * Confirm upload with backend and get final CDN URL
   */
  async confirmUpload(presignedData, uploadResult) {
    try {
      const response = await fetch(`${this.apiUrl}/images/confirm-upload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          key: presignedData.key,
          etag: uploadResult.etag
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to confirm upload:', error);
      throw error;
    }
  }

  /**
   * Abort multipart upload (on user cancel)
   */
  async abortUpload(presignedData) {
    if (!presignedData.uploadId) return; // Single-part upload, no cleanup needed

    try {
      await fetch(`${this.apiUrl}/images/abort-upload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          key: presignedData.key,
          uploadId: presignedData.uploadId
        })
      });
    } catch (error) {
      console.error('Failed to abort upload:', error);
    }
  }

  /**
   * Full upload flow: request → upload → confirm
   * 
   * Returns: { url: "https://cdn.example.com/listings/..." }
   * Throws: Error with detailed message
   */
  async upload(file, onProgress = null) {
    try {
      // Step 1: Get presigned URL
      const presignedData = await this.requestPresignedUrl(file);
      
      if (presignedData.fallback) {
        console.warn('S3 not configured, falling back to base64 encoding');
        return null; // Caller should handle base64 fallback
      }

      // Step 2: Upload file directly to S3
      const uploadResult = await this.uploadToPresignedUrl(file, presignedData, onProgress);

      // Step 3: Confirm with backend
      const confirmResult = await this.confirmUpload(presignedData, uploadResult);

      return confirmResult;
    } catch (error) {
      console.error('Full upload failed:', error);
      throw error;
    }
  }
}

// Export for use in listing forms
window.S3Uploader = S3Uploader;

// Helper for easy integration
window.createS3Uploader = (apiUrl = '/api') => new S3Uploader(apiUrl);

export { S3Uploader };
