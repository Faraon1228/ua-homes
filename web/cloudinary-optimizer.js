/**
 * Cloudinary Image Optimization Helper
 * 
 * Cloudinary automatically optimizes images using URL transformations.
 * No API calls needed - just modify the URL!
 * 
 * Example:
 *   Original: https://res.cloudinary.com/cloud/image/upload/v123/photo.jpg
 *   Optimized for medium (400px, WebP):
 *     https://res.cloudinary.com/cloud/image/upload/w_400,f_auto,q_auto/v123/photo.jpg
 * 
 * Query builder:
 *   w_400        = width 400px
 *   h_300        = height 300px
 *   c_fill       = crop to exact size
 *   f_auto       = auto format (WebP/AVIF/original)
 *   q_auto       = auto quality
 *   dpr_auto     = device pixel ratio
 */

class CloudinaryOptimizer {
  constructor(cloudName = 'dummycloud') {
    this.cloudName = cloudName;
    this.baseUrl = `https://res.cloudinary.com/${cloudName}/image/upload`;
  }

  /**
   * Transform URL for specific size + format
   */
  getOptimizedUrl(imageUrl, { width = null, height = null, quality = 'auto', format = 'auto' } = {}) {
    // If not a Cloudinary URL, return original
    if (!imageUrl || !imageUrl.includes('cloudinary.com')) {
      return imageUrl;
    }

    // Extract public_id from URL
    // https://res.cloudinary.com/cloud/image/upload/v123/path/to/photo.jpg
    // → v123/path/to/photo.jpg
    const match = imageUrl.match(/\/image\/upload\/(.+)$/);
    if (!match) return imageUrl;

    const publicId = match[1];
    const transforms = [];

    if (width) transforms.push(`w_${width}`);
    if (height) transforms.push(`h_${height}`);
    
    transforms.push(`c_fill`); // Crop to exact dimensions
    transforms.push(`f_${format}`); // Format: auto|webp|avif|jpg
    transforms.push(`q_${quality}`); // Quality: auto|80|90|100
    transforms.push(`dpr_auto`); // Device pixel ratio

    const transformString = transforms.join(',');
    return `${this.baseUrl}/${transformString}/${publicId}`;
  }

  /**
   * Get all variants (thumbnail, medium, large)
   */
  getImageVariants(imageUrl) {
    if (!imageUrl) return null;

    return {
      thumbnail: this.getOptimizedUrl(imageUrl, { width: 150, height: 100, format: 'auto' }),
      medium: this.getOptimizedUrl(imageUrl, { width: 400, height: 300, format: 'auto' }),
      large: this.getOptimizedUrl(imageUrl, { width: 1200, height: 800, format: 'auto' }),
      original: imageUrl
    };
  }
}

// Export as global
window.CloudinaryOptimizer = CloudinaryOptimizer;

// Usage:
// const optimizer = new CloudinaryOptimizer('your-cloud-name');
// const variants = optimizer.getImageVariants('https://res.cloudinary.com/..../photo.jpg');
// console.log(variants.medium); // Auto-optimized for 400x300, WebP/AVIF on modern browsers
