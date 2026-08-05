"""
Image Optimization Pipeline

Converts uploaded images to multiple formats and sizes:
- WebP + AVIF (modern formats, 50% smaller than JPEG)
- 3 sizes: thumbnail (150x100), medium (400x300), large (1200x800)

Usage:
  optimizer = ImageOptimizer(s3_client, bucket='ua-dim-listings')
  result = await optimizer.optimize_and_upload(
    file_bytes=image_data,
    original_key='listings/123/abc123/photo.jpg'
  )
  
  Returns:
  {
    'thumbnail_webp': 'https://cdn.../listings/123/abc123/photo-thumb.webp',
    'medium_webp': 'https://cdn.../listings/123/abc123/photo-medium.webp',
    'large_webp': 'https://cdn.../listings/123/abc123/photo-large.webp',
    'thumbnail_avif': '...',
    'medium_avif': '...',
    'large_avif': '...',
    'metadata': { 'original_size': 1234567, 'optimized_size': 345678 }
  }

Requirements:
  pip install pillow
  # For AVIF support:
  pip install pillow-heif
"""

import io
import os
from typing import Optional, Dict, Any
from PIL import Image
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Try to import AVIF support
try:
    import pillow_heif
    HAS_AVIF = True
except ImportError:
    HAS_AVIF = False


class ImageOptimizer:
    """
    Optimizes images for web:
    - Converts to WebP + AVIF
    - Creates 3 sizes (thumbnail, medium, large)
    - Uploads to S3
    """
    
    # Image sizes (width, height)
    SIZES = {
        'thumbnail': (150, 100),
        'medium': (400, 300),
        'large': (1200, 800)
    }
    
    # Quality settings (0-100)
    QUALITY = {
        'webp': 80,
        'avif': 75,
        'jpeg': 85
    }
    
    def __init__(self, s3_client, bucket: str, cdn_url: str = None):
        self.s3_client = s3_client
        self.bucket = bucket
        self.cdn_url = cdn_url or f"https://{bucket}.s3.amazonaws.com"
        self.executor = ThreadPoolExecutor(max_workers=4)
    
    def _resize_image(self, img: Image.Image, size: tuple) -> Image.Image:
        """Resize image maintaining aspect ratio with padding."""
        img.thumbnail(size, Image.Resampling.LANCZOS)
        
        # Create new image with white background
        result = Image.new('RGB', size, (255, 255, 255))
        offset = (
            (size[0] - img.width) // 2,
            (size[1] - img.height) // 2
        )
        result.paste(img, offset)
        return result
    
    def _convert_to_webp(self, img: Image.Image, quality: int = 80) -> bytes:
        """Convert PIL Image to WebP bytes."""
        output = io.BytesIO()
        img.save(output, format='WEBP', quality=quality, method=6)
        return output.getvalue()
    
    def _convert_to_avif(self, img: Image.Image, quality: int = 75) -> Optional[bytes]:
        """Convert PIL Image to AVIF bytes (if supported)."""
        if not HAS_AVIF:
            return None
        
        try:
            output = io.BytesIO()
            img.save(output, format='AVIF', quality=quality)
            return output.getvalue()
        except Exception as e:
            print(f"AVIF conversion failed: {e}")
            return None
    
    def _get_output_key(self, original_key: str, size: str, format: str) -> str:
        """Generate S3 output key."""
        # listings/123/abc123/photo.jpg → listings/123/abc123/photo-medium.webp
        base, ext = os.path.splitext(original_key)
        return f"{base}-{size}.{format}"
    
    async def _upload_to_s3(self, key: str, data: bytes, content_type: str) -> str:
        """Upload image to S3 and return URL."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            lambda: self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                CacheControl='public, max-age=31536000, immutable'  # 1 year
            )
        )
        return f"{self.cdn_url}/{key}"
    
    async def optimize_and_upload(self, file_bytes: bytes, original_key: str) -> Dict[str, Any]:
        """
        Main pipeline: resize → convert → upload.
        
        Returns dict with URLs for all sizes/formats + metadata.
        """
        
        # Parse original image
        img = Image.open(io.BytesIO(file_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        original_size = len(file_bytes)
        results = {}
        upload_tasks = []
        
        # Generate all sizes in WebP + AVIF
        for size_name, size_dims in self.SIZES.items():
            # Resize image
            resized = self._resize_image(img.copy(), size_dims)
            
            # WebP version
            webp_data = self._convert_to_webp(resized, self.QUALITY['webp'])
            webp_key = self._get_output_key(original_key, size_name, 'webp')
            upload_tasks.append((
                self._upload_to_s3(webp_key, webp_data, 'image/webp'),
                f'{size_name}_webp'
            ))
            
            # AVIF version (if supported)
            avif_data = self._convert_to_avif(resized, self.QUALITY['avif'])
            if avif_data:
                avif_key = self._get_output_key(original_key, size_name, 'avif')
                upload_tasks.append((
                    self._upload_to_s3(avif_key, avif_data, 'image/avif'),
                    f'{size_name}_avif'
                ))
        
        # Execute all uploads concurrently
        for task, key in upload_tasks:
            url = await task
            results[key] = url
        
        # Calculate total optimized size
        optimized_size = sum(len(d) for d in [
            self._convert_to_webp(self._resize_image(img.copy(), size_dims), self.QUALITY['webp'])
            for size_dims in self.SIZES.values()
        ])
        
        results['metadata'] = {
            'original_size': original_size,
            'optimized_size': optimized_size,
            'compression_ratio': round((1 - optimized_size / original_size) * 100),
            'formats': ['webp', 'avif' if HAS_AVIF else None],
            'sizes': list(self.SIZES.keys())
        }
        
        return results


# Video optimization placeholder (FFmpeg-based)
class VideoOptimizer:
    """
    Compresses videos for streaming:
    - H.264 codec
    - 720p + 1080p variants
    - AAC audio
    
    Requires: ffmpeg binary installed
    
    Usage:
      optimizer = VideoOptimizer(s3_client)
      result = await optimizer.compress_and_upload(
        video_file='listing-tour.mp4',
        output_key='listings/123/abc123/tour'
      )
    """
    
    def __init__(self, s3_client, bucket: str):
        self.s3_client = s3_client
        self.bucket = bucket
    
    async def compress_and_upload(self, video_file: str, output_key: str) -> Dict[str, str]:
        """
        Compress video and upload variants.
        
        Returns:
        {
          '720p': 'https://cdn.../listings/123/abc123/tour-720p.mp4',
          '1080p': 'https://cdn.../listings/123/abc123/tour-1080p.mp4'
        }
        """
        # Implementation requires FFmpeg
        # For now, this is a placeholder
        raise NotImplementedError("Video compression requires FFmpeg integration")
