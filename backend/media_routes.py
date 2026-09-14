import datetime
import hashlib
import html
import io
import json
import os
import re
import sys
import time
from functools import wraps
from urllib.parse import unquote, urlparse, urlsplit

from flask import Blueprint, Response, current_app, g, jsonify, request

media_bp = Blueprint("media_bp", __name__)


def _get_app_module():
    """Dynamically get the main app module to access shared globals and helpers."""
    if "backend.app" in sys.modules:
        return sys.modules["backend.app"]
    if "app" in sys.modules:
        return sys.modules["app"]
    try:
        import app
        return app
    except ImportError:
        from backend import app
        return app


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        app_mod = _get_app_module()
        return app_mod.require_auth(f)(*args, **kwargs)
    return decorated


def _cloudinary_upload_preset() -> str:
    app_module = _get_app_module()
    if hasattr(app_module, "_cloudinary_upload_preset"):
        return app_module._cloudinary_upload_preset()
    return os.environ.get("CLOUDINARY_UPLOAD_PRESET", "").strip()


def generate_presigned_upload_url(
    filename: str,
    content_type: str,
    resource_type: str = "image",
    expires_in: int = 3600,
) -> dict | None:
    """
    Generate Presigned URL for direct browser → S3 upload.
    """
    app_module = _get_app_module()
    s3_enabled = getattr(app_module, "S3_ENABLED", False)
    if not s3_enabled:
        return None

    s3_bucket = getattr(app_module, "S3_BUCKET", "")
    s3_access_key = getattr(app_module, "S3_ACCESS_KEY", "")
    s3_secret_key = getattr(app_module, "S3_SECRET_KEY", "")
    s3_region = getattr(app_module, "S3_REGION", "eu-north-1")
    s3_endpoint = getattr(app_module, "S3_ENDPOINT", None)
    s3_public_base_url = getattr(app_module, "S3_PUBLIC_BASE_URL", "")
    cloudinary_url = getattr(app_module, "CLOUDINARY_URL", "")

    import uuid
    unique_id = uuid.uuid4().hex[:12]
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(filename or ""))[:180] or "media"
    user_id = getattr(g, "user_id", None)
    s3_key = f"listings/{user_id}/{unique_id}/{safe_filename}"

    # AWS S3 Presigned URL
    if s3_bucket and s3_access_key and s3_secret_key:
        if not s3_public_base_url:
            return None
        import boto3
        from botocore.config import Config

        s3_client = boto3.client(
            "s3",
            region_name=s3_region,
            aws_access_key_id=s3_access_key,
            aws_secret_access_key=s3_secret_key,
            endpoint_url=s3_endpoint,
            config=Config(signature_version="s3v4"),
        )

        try:
            uploaded_at = datetime.datetime.utcnow().isoformat()
            url = s3_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": s3_bucket,
                    "Key": s3_key,
                    "ContentType": content_type,
                    "Metadata": {
                        "user-id": str(user_id),
                        "uploaded-at": uploaded_at,
                    },
                },
                ExpiresIn=expires_in,
            )

            return {
                "uploadUrl": url,
                "key": s3_key,
                "bucket": s3_bucket,
                "region": s3_region,
                "method": "PUT",
                "storage": "aws_s3",
                "expiresIn": expires_in,
                "headers": {
                    "Content-Type": content_type,
                    "x-amz-meta-user-id": str(user_id),
                    "x-amz-meta-uploaded-at": uploaded_at,
                },
            }
        except Exception as e:
            print(f"Error generating S3 presigned URL: {e}")
            return None

    # Cloudinary Upload
    elif cloudinary_url:
        import cloudinary
        import cloudinary.uploader
        import cloudinary.utils

        try:
            parsed = urlparse(cloudinary_url)
            cloud_name = parsed.hostname or ""
            api_key = parsed.username or os.environ.get("CLOUDINARY_API_KEY", "").strip()
            api_secret = parsed.password or os.environ.get("CLOUDINARY_API_SECRET", "").strip()
            upload_preset = _cloudinary_upload_preset()

            print(f"[Cloudinary] cloud_name={cloud_name}, preset={upload_preset}, has_api_key={bool(api_key)}")

            if not cloud_name:
                return None

            safe_stem = os.path.splitext(safe_filename)[0] or "media"
            public_id = f"listings/{user_id}/{unique_id}/{safe_stem}"
            upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/{resource_type}/upload"

            if upload_preset:
                print(f"[Cloudinary] Using UNSIGNED upload preset: {upload_preset}")
                return {
                    "uploadUrl": upload_url,
                    "method": "POST",
                    "storage": "cloudinary",
                    "expiresIn": expires_in,
                    "cloudName": cloud_name,
                    "authType": "unsigned",
                    "uploadPreset": upload_preset,
                    "publicId": public_id,
                    "resourceType": resource_type,
                }

            if api_key and api_secret:
                print(f"[Cloudinary] Preset NOT available, using SIGNED uploads with credentials")
                timestamp = int(time.time())

                sig_params = {
                    "public_id": public_id,
                    "timestamp": timestamp,
                }
                signature = cloudinary.utils.api_sign_request(sig_params, api_secret)

                return {
                    "uploadUrl": upload_url,
                    "method": "POST",
                    "storage": "cloudinary",
                    "expiresIn": expires_in,
                    "cloudName": cloud_name,
                    "authType": "signed",
                    "apiKey": api_key,
                    "timestamp": timestamp,
                    "signature": signature,
                    "publicId": public_id,
                    "resourceType": resource_type,
                }

            return None
        except Exception as e:
            print(f"Error generating Cloudinary upload URL: {e}")
            return None

    return None


def cleanup_listing_media(media_urls: list[str], user_id: int) -> list[str]:
    """Delete only storage objects that are namespaced to the listing owner."""
    app_module = _get_app_module()
    s3_bucket = getattr(app_module, "S3_BUCKET", "")
    s3_access_key = getattr(app_module, "S3_ACCESS_KEY", "")
    s3_secret_key = getattr(app_module, "S3_SECRET_KEY", "")
    s3_region = getattr(app_module, "S3_REGION", "eu-north-1")
    s3_endpoint = getattr(app_module, "S3_ENDPOINT", None)
    s3_public_base_url = getattr(app_module, "S3_PUBLIC_BASE_URL", "")
    cloudinary_url = getattr(app_module, "CLOUDINARY_URL", "")

    owned_prefix = f"listings/{user_id}/"
    s3_keys: list[str] = []
    cloudinary_assets: list[tuple[str, str]] = []

    for media_url in media_urls:
        url = str(media_url or "").strip()
        if not url:
            continue
        if s3_public_base_url and url.startswith(f"{s3_public_base_url}/"):
            key = unquote(url[len(s3_public_base_url) + 1 :])
            if key.startswith(owned_prefix):
                s3_keys.append(key)
            continue

        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.hostname != "res.cloudinary.com":
            continue
        for resource_type in ("image", "video"):
            marker = f"/{resource_type}/upload/"
            if marker not in parsed.path:
                continue
            public_id = parsed.path.split(marker, 1)[1]
            public_id = re.sub(r"^v\d+/", "", public_id)
            public_id = os.path.splitext(public_id)[0]
            if public_id.startswith(owned_prefix):
                cloudinary_assets.append((public_id, resource_type))
            break

    failures: list[str] = []
    if s3_keys:
        try:
            import boto3
            from botocore.config import Config

            s3 = boto3.client(
                "s3",
                region_name=s3_region,
                aws_access_key_id=s3_access_key,
                aws_secret_access_key=s3_secret_key,
                endpoint_url=s3_endpoint,
                config=Config(signature_version="s3v4"),
            )
            result = s3.delete_objects(
                Bucket=s3_bucket,
                Delete={"Objects": [{"Key": key} for key in sorted(set(s3_keys))], "Quiet": True},
            )
            failures.extend(str(item.get("Key") or "s3") for item in result.get("Errors", []))
        except Exception:
            failures.extend(s3_keys)

    if cloudinary_assets and cloudinary_url:
        try:
            import cloudinary
            import cloudinary.uploader

            cloudinary.config(secure=True)
            for public_id, resource_type in sorted(set(cloudinary_assets)):
                result = cloudinary.uploader.destroy(
                    public_id,
                    resource_type=resource_type,
                    invalidate=True,
                )
                if result.get("result") not in {"ok", "not found"}:
                    failures.append(public_id)
        except Exception:
            failures.extend(public_id for public_id, _ in cloudinary_assets)

    return list(dict.fromkeys(failures))


def _image_optimization_metadata(original_size: int, optimized_total: int) -> dict:
    compression_ratio = round((1 - optimized_total / (original_size * 3)) * 100)
    return {
        "original_size": original_size,
        "optimized_total": optimized_total,
        "compression_ratio": compression_ratio,
        "message": f"Created 3 WebP variants + AVIF. Compression: {compression_ratio}%",
    }


# ─── Routes ──────────────────────────────────────────────────────────────────

@media_bp.route("/api/images/presigned-url", methods=["POST"], endpoint="get_presigned_upload_url")
@media_bp.route("/api/media/presigned-url", methods=["POST"], endpoint="get_presigned_media_upload_url")
@require_auth
def get_presigned_upload_url_route():
    app_module = _get_app_module()

    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename", "")).strip()
    content_type = str(data.get("contentType", "")).strip()
    nonneg_int = getattr(app_module, "nonneg_int", int)
    file_size = nonneg_int(data.get("size")) if callable(nonneg_int) else None

    if not filename:
        return jsonify(error="Missing filename"), 400

    normalize_func = getattr(app_module, "normalize_media_content_type", None)
    normalized_content_type, resource_type = normalize_func(filename, content_type) if normalize_func else ("", "")
    if not normalized_content_type:
        return jsonify(error="Непідтримуваний формат. Дозволено фото JPG/PNG/WEBP/AVIF/HEIC та відео MP4/MOV/WEBM."), 400

    max_video_size = getattr(app_module, "MAX_VIDEO_UPLOAD_SIZE", 100 * 1024 * 1024)
    max_image_size = getattr(app_module, "MAX_UPLOAD_SIZE", 25 * 1024 * 1024)
    max_size = max_video_size if resource_type == "video" else max_image_size
    if file_size is not None and file_size > max_size:
        return jsonify(error=f"Файл завеликий. Максимум {max_size // 1_048_576} МБ."), 413

    # Delegate to app_module.generate_presigned_upload_url to allow mocks in tests
    gen_func = getattr(app_module, "generate_presigned_upload_url", generate_presigned_upload_url)
    presigned = gen_func(filename, normalized_content_type, resource_type)
    if not presigned:
        return jsonify(error="Сховище медіа не налаштоване."), 503

    presigned["contentType"] = normalized_content_type
    presigned["resourceType"] = resource_type
    presigned["maxSize"] = max_size
    return jsonify(presigned)


@media_bp.route("/api/images/confirm-upload", methods=["POST"], endpoint="confirm_uploaded_media")
@media_bp.route("/api/media/confirm-upload", methods=["POST"], endpoint="confirm_uploaded_media_alias")
@require_auth
def confirm_uploaded_media_route():
    app_module = _get_app_module()

    data = request.get_json(silent=True) or {}
    s3_key = str(data.get("key", "")).strip()
    etag = str(data.get("etag", "")).strip()
    cloudinary_url = str(data.get("url", "")).strip()
    public_id = str(data.get("publicId", "")).strip()
    resource_type = "video" if str(data.get("resourceType", "")).strip().lower() == "video" else "image"

    if not s3_key and not public_id and not cloudinary_url:
        return jsonify(error="Missing upload reference"), 400

    s3_bucket = getattr(app_module, "S3_BUCKET", "")
    s3_access_key = getattr(app_module, "S3_ACCESS_KEY", "")
    s3_secret_key = getattr(app_module, "S3_SECRET_KEY", "")
    s3_region = getattr(app_module, "S3_REGION", "eu-north-1")
    s3_endpoint = getattr(app_module, "S3_ENDPOINT", None)
    s3_public_base_url = getattr(app_module, "S3_PUBLIC_BASE_URL", "")
    cloudinary_config_url = getattr(app_module, "CLOUDINARY_URL", "")
    max_video_size = getattr(app_module, "MAX_VIDEO_UPLOAD_SIZE", 100 * 1024 * 1024)
    max_image_size = getattr(app_module, "MAX_UPLOAD_SIZE", 25 * 1024 * 1024)

    if s3_key:
        if not s3_key.startswith(f"listings/{g.user_id}/"):
            return jsonify(error="Unauthorized: file does not belong to you"), 403

        if s3_bucket and s3_access_key:
            try:
                import boto3
                s3 = boto3.client(
                    "s3",
                    region_name=s3_region,
                    aws_access_key_id=s3_access_key,
                    aws_secret_access_key=s3_secret_key,
                    endpoint_url=s3_endpoint,
                )
                response = s3.head_object(Bucket=s3_bucket, Key=s3_key)

                if etag and response.get("ETag", "").strip('"') != etag:
                    return jsonify(error="ETag mismatch - file may be corrupted"), 400
                normalize_func = getattr(app_module, "normalize_media_content_type", None)
                stored_type, stored_resource_type = normalize_func(
                    s3_key,
                    response.get("ContentType", ""),
                ) if normalize_func else ("", "")
                if not stored_type:
                    return jsonify(error="Непідтримуваний формат завантаженого файла"), 400
                max_size = max_video_size if stored_resource_type == "video" else max_image_size
                if int(response.get("ContentLength") or 0) > max_size:
                    return jsonify(error="Завантажений файл перевищує дозволений розмір"), 413
            except Exception as e:
                error_code = str(
                    getattr(e, "response", {}).get("Error", {}).get("Code", "")
                )
                if error_code in {"NoSuchKey", "NotFound", "404"}:
                    return jsonify(error="File not found in S3"), 404
                print(f"Error verifying S3 upload: {e}")
                return jsonify(error="Failed to verify upload"), 500

        if not s3_public_base_url:
            return jsonify(error="S3 delivery URL is not configured"), 503
        cdn_url = f"{s3_public_base_url}/{s3_key}"
        return jsonify({"url": cdn_url})

    if public_id:
        if not public_id.startswith(f"listings/{g.user_id}/"):
            return jsonify(error="Unauthorized: file does not belong to you"), 403

        cloud_name = ""
        if cloudinary_config_url:
            import cloudinary
            import cloudinary.api
            cloudinary.config(secure=True)
            cloud_name = getattr(cloudinary.config(), "cloud_name", None) or ""
            try:
                asset = cloudinary.api.resource(public_id, resource_type=resource_type)
            except Exception:
                return jsonify(error="Не вдалося перевірити завантажений Cloudinary-файл"), 400
            max_size = max_video_size if resource_type == "video" else max_image_size
            if int(asset.get("bytes") or 0) > max_size:
                return jsonify(error="Завантажений файл перевищує дозволений розмір"), 413
            actual_resource_type = str(asset.get("resource_type") or "").lower()
            if actual_resource_type and actual_resource_type != resource_type:
                return jsonify(error="Тип Cloudinary-файла не відповідає запиту"), 400
            cloudinary_url = str(asset.get("secure_url") or cloudinary_url).strip()

        if cloudinary_url:
            if cloud_name and f"/{cloud_name}/" not in cloudinary_url:
                return jsonify(error="Cloudinary URL does not match configured cloud"), 400
            expected_path = f"/{resource_type}/upload/"
            if expected_path not in cloudinary_url:
                return jsonify(error="Cloudinary media type does not match upload"), 400
            return jsonify({"url": cloudinary_url})

        if cloud_name:
            return jsonify({"url": f"https://res.cloudinary.com/{cloud_name}/{resource_type}/upload/{public_id}"})

        return jsonify(error="Cloudinary not configured"), 503

    return jsonify(error="Missing upload reference"), 400


@media_bp.route("/api/images/abort-upload", methods=["POST"], endpoint="abort_multipart_upload")
@require_auth
def abort_multipart_upload_route():
    app_module = _get_app_module()

    data = request.get_json(silent=True) or {}
    upload_id = str(data.get("uploadId", "")).strip()
    s3_key = str(data.get("key", "")).strip()

    if not s3_key or not upload_id:
        return jsonify(error="Missing uploadId or key"), 400

    if not s3_key.startswith(f"listings/{g.user_id}/"):
        return jsonify(error="Unauthorized"), 403

    s3_bucket = getattr(app_module, "S3_BUCKET", "")
    s3_access_key = getattr(app_module, "S3_ACCESS_KEY", "")
    s3_secret_key = getattr(app_module, "S3_SECRET_KEY", "")
    s3_region = getattr(app_module, "S3_REGION", "eu-north-1")
    s3_endpoint = getattr(app_module, "S3_ENDPOINT", None)

    if s3_bucket and s3_access_key:
        try:
            import boto3
            s3 = boto3.client(
                "s3",
                region_name=s3_region,
                aws_access_key_id=s3_access_key,
                aws_secret_access_key=s3_secret_key,
                endpoint_url=s3_endpoint,
            )
            s3.abort_multipart_upload(Bucket=s3_bucket, Key=s3_key, UploadId=upload_id)
        except Exception as e:
            print(f"Error aborting upload: {e}")

    return jsonify(status="ok")


@media_bp.route("/api/images/optimize", methods=["POST"], endpoint="optimize_image")
@require_auth
def optimize_image_route():
    app_module = _get_app_module()

    has_img_opt = getattr(app_module, "HAS_IMAGE_OPTIMIZATION", False)
    if not has_img_opt:
        return jsonify(error="Image optimization not available (Pillow not installed)"), 503

    data = request.get_json(silent=True) or {}
    s3_key = str(data.get("key", "")).strip()

    if not s3_key:
        return jsonify(error="Missing S3 key"), 400

    if not s3_key.startswith(f"listings/{g.user_id}/"):
        return jsonify(error="Unauthorized: image does not belong to you"), 403

    s3_bucket = getattr(app_module, "S3_BUCKET", "")
    s3_access_key = getattr(app_module, "S3_ACCESS_KEY", "")
    s3_secret_key = getattr(app_module, "S3_SECRET_KEY", "")
    s3_region = getattr(app_module, "S3_REGION", "eu-north-1")
    s3_endpoint = getattr(app_module, "S3_ENDPOINT", None)

    if not s3_bucket or not s3_access_key:
        return jsonify(error="S3 not configured"), 503

    try:
        from PIL import Image
        import boto3
        s3_client = boto3.client(
            "s3",
            region_name=s3_region,
            aws_access_key_id=s3_access_key,
            aws_secret_access_key=s3_secret_key,
            endpoint_url=s3_endpoint,
        )

        response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        image_bytes = response["Body"].read()
        original_size = len(image_bytes)

        img = Image.open(io.BytesIO(image_bytes))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        sizes = {
            "thumbnail": (150, 100),
            "medium": (400, 300),
            "large": (1200, 800),
        }

        results = {}
        total_optimized = 0

        for size_name, (width, height) in sizes.items():
            resized = img.copy()
            resized.thumbnail((width, height), Image.Resampling.LANCZOS)

            padded = Image.new("RGB", (width, height), (255, 255, 255))
            offset = ((width - resized.width) // 2, (height - resized.height) // 2)
            padded.paste(resized, offset)

            webp_buffer = io.BytesIO()
            padded.save(webp_buffer, format="WEBP", quality=80, method=6)
            webp_data = webp_buffer.getvalue()
            total_optimized += len(webp_data)

            output_key = s3_key.replace(".jpg", f"-{size_name}.webp").replace(".png", f"-{size_name}.webp")
            s3_client.put_object(
                Bucket=s3_bucket,
                Key=output_key,
                Body=webp_data,
                ContentType="image/webp",
                CacheControl="public, max-age=31536000, immutable",
            )

            results[f"{size_name}_webp"] = f"https://{s3_bucket}.s3.{s3_region}.amazonaws.com/{output_key}"

            try:
                avif_buffer = io.BytesIO()
                padded.save(avif_buffer, format="AVIF", quality=75)
                avif_data = avif_buffer.getvalue()
                total_optimized += len(avif_data)

                avif_key = output_key.replace(".webp", ".avif")
                s3_client.put_object(
                    Bucket=s3_bucket,
                    Key=avif_key,
                    Body=avif_data,
                    ContentType="image/avif",
                    CacheControl="public, max-age=31536000, immutable",
                )

                results[f"{size_name}_avif"] = f"https://{s3_bucket}.s3.{s3_region}.amazonaws.com/{avif_key}"
            except Exception as e:
                print(f"AVIF conversion skipped: {e}")

        results["metadata"] = _image_optimization_metadata(original_size, total_optimized)
        return jsonify(results)

    except Exception as e:
        print(f"Image optimization error: {e}")
        return jsonify(error=f"Failed to optimize image: {str(e)}"), 500


@media_bp.route("/api/demo-images/<path:seed>.svg", methods=["GET"])
def generate_demo_svg(seed: str):
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    palette = [
        ("#0f172a", "#1d4ed8"),
        ("#1e293b", "#2563eb"),
        ("#172554", "#0ea5e9"),
        ("#111827", "#7c3aed"),
        ("#0f172a", "#0891b2"),
        ("#1f2937", "#0f766e"),
    ]
    accent_pairs = [
        ("#e2e8f0", "#cbd5e1"),
        ("#dbeafe", "#bfdbfe"),
        ("#dcfce7", "#bbf7d0"),
        ("#fae8ff", "#e9d5ff"),
        ("#fef3c7", "#fde68a"),
        ("#fee2e2", "#fecaca"),
    ]
    bg_start, bg_end = palette[int(digest[0], 16) % len(palette)]
    card_fill, card_stroke = accent_pairs[int(digest[1], 16) % len(accent_pairs)]
    seed_label = html.escape(seed[:28].upper())
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" role="img" aria-label="UA-Dim demo image {seed_label}">
<defs>
  <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
    <stop offset="0%" stop-color="{bg_start}"/>
    <stop offset="100%" stop-color="{bg_end}"/>
  </linearGradient>
</defs>
<rect width="1200" height="800" fill="url(#bg)"/>
<rect x="54" y="54" width="1092" height="692" rx="40" fill="rgba(255,255,255,.08)" stroke="rgba(255,255,255,.18)" stroke-width="4"/>
<rect x="106" y="122" width="420" height="42" rx="21" fill="rgba(255,255,255,.14)"/>
<text x="134" y="151" fill="#ffffff" font-family="Arial,sans-serif" font-size="28" font-weight="700">UA-Dim • Demo listing</text>
<rect x="106" y="206" width="456" height="320" rx="34" fill="{card_fill}" opacity=".95"/>
<rect x="642" y="206" width="454" height="178" rx="34" fill="rgba(255,255,255,.12)"/>
<rect x="642" y="408" width="454" height="118" rx="28" fill="rgba(255,255,255,.08)"/>
<rect x="642" y="552" width="454" height="118" rx="28" fill="rgba(255,255,255,.08)"/>
<path d="M144 466 256 338l112 96 124-154 146 186Z" fill="{card_stroke}" opacity=".95"/>
<circle cx="222" cy="292" r="46" fill="#ffffff" opacity=".72"/>
<rect x="742" y="246" width="206" height="34" rx="17" fill="rgba(255,255,255,.22)"/>
<rect x="742" y="298" width="298" height="26" rx="13" fill="rgba(255,255,255,.16)"/>
<rect x="742" y="444" width="236" height="26" rx="13" fill="rgba(255,255,255,.16)"/>
<rect x="742" y="587" width="236" height="26" rx="13" fill="rgba(255,255,255,.16)"/>
<text x="106" y="610" fill="#ffffff" font-family="Arial,sans-serif" font-size="52" font-weight="700">Надійне фото з домену UA-Dim</text>
<text x="106" y="662" fill="rgba(255,255,255,.76)" font-family="Arial,sans-serif" font-size="28">Без зовнішніх CDN • стабільно для production і preview</text>
<text x="106" y="712" fill="rgba(255,255,255,.64)" font-family="Arial,sans-serif" font-size="22">Seed: {seed_label}</text>
</svg>"""
    response = Response(svg, mimetype="image/svg+xml")
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
