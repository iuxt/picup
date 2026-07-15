# WebP Upload Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce uploaded image size and S3 traffic by producing WebP objects while passing through unchanged source WebP bytes without re-encoding.

**Architecture:** Keep the small application in `app.py`, but separate clipboard decoding, pixel processing, WebP payload preparation, and S3 upload into focused helpers. Preserve the source bytes and detected format, track whether resizing or watermarking changed pixels, then either pass through unchanged WebP bytes or encode the processed Pillow image at configurable quality.

**Tech Stack:** Python 3.10+ (Python 3.12 recommended), Flask 3.1.3, Pillow 11.3.0 with WebP support, boto3, unittest, macOS AppKit clipboard APIs

## Global Constraints

- Newly encoded images use lossy WebP with `quality=82` by default and fixed `method=6`.
- `WEBP_QUALITY` accepts only integers from `1` through `100`; invalid configuration fails during application startup.
- Source WebP bytes pass through only when no resize occurs and `WATERMARK_TEXT` is exactly the empty string.
- Any resize or non-empty watermark forces WebP re-encoding.
- Preserve alpha and ICC color profiles in newly encoded WebP; do not copy EXIF or XMP metadata.
- All new S3 objects use the `.webp` suffix and `image/webp` Content-Type.
- Preserve the existing longest-edge resize behavior, watermark positioning, year/month object path, HTTP response shape, clipboard URL copy, and macOS notification behavior.
- Do not add runtime dependencies, responsive variants, content classification, dual encoding, or migration of existing PNG objects.
- Keep production code in `app.py`; add focused test modules rather than restructuring the application.

## File Map

- Modify `app.py`: bounded quality configuration, clipboard value object and raw-byte preservation, WebP encoding and payload selection, byte-oriented S3 upload, and route integration.
- Create `tests/test_clipboard_image.py`: source byte/format preservation and WebP clipboard priority.
- Create `tests/test_webp_encoding.py`: encoding parameters, alpha/ICC behavior, passthrough decisions, and size logs.
- Modify `tests/test_image_resizing.py`: upload pipeline order, watermark disabling, and encode failure response.
- Modify `tests/test_upload_logging.py`: byte payload upload, `.webp` object keys, and Content-Type.
- Modify `readme.md`: document WebP output, `WEBP_QUALITY`, and the passthrough condition.

---

### Task 1: Bounded WebP quality configuration

**Files:**
- Modify: `app.py:24-56`
- Modify: `tests/test_image_resizing.py:8-40`

**Interfaces:**
- Consumes: `os.getenv(name)` and the existing import-time configuration pattern.
- Produces: `env_int_in_range(name: str, default: int, minimum: int, maximum: int) -> int` and module constant `WEBP_QUALITY: int`.

- [ ] **Step 1: Add failing bounded-quality tests**

Add this class after `ImageSizeConfigTest` in `tests/test_image_resizing.py`:

```python
class WebPQualityConfigTest(unittest.TestCase):
    def test_missing_value_uses_default(self):
        with patch.dict(app.os.environ, {}, clear=True):
            result = app.env_int_in_range("WEBP_QUALITY", 82, 1, 100)

        self.assertEqual(82, result)

    def test_boundary_and_configured_values_are_used(self):
        for value in ("1", "82", "100"):
            with self.subTest(value=value):
                with patch.dict(
                    app.os.environ,
                    {"WEBP_QUALITY": value},
                    clear=True,
                ):
                    result = app.env_int_in_range(
                        "WEBP_QUALITY",
                        82,
                        1,
                        100,
                    )

                self.assertEqual(int(value), result)

    def test_invalid_values_raise_configuration_error(self):
        for value in ("", "not-a-number", "0", "-1", "101"):
            with self.subTest(value=value):
                with patch.dict(
                    app.os.environ,
                    {"WEBP_QUALITY": value},
                    clear=True,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "WEBP_QUALITY must be an integer from 1 to 100",
                    ):
                        app.env_int_in_range(
                            "WEBP_QUALITY",
                            82,
                            1,
                            100,
                        )
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_resizing.WebPQualityConfigTest -v
```

Expected: three tests report `ERROR` with `AttributeError: module 'app' has no attribute 'env_int_in_range'`.

- [ ] **Step 3: Implement bounded integer parsing and the module constant**

Add this function after `env_positive_int()` in `app.py`:

```python
def env_int_in_range(name, default, minimum, maximum):
    """Read an integer environment setting constrained to an inclusive range."""
    value = os.getenv(name)
    if value is None:
        return default

    try:
        parsed_value = int(value)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be an integer from {minimum} to {maximum}, "
            f"got {value!r}"
        ) from exc

    if not minimum <= parsed_value <= maximum:
        raise RuntimeError(
            f"{name} must be an integer from {minimum} to {maximum}, "
            f"got {value!r}"
        )

    return parsed_value
```

Add the WebP constant immediately after `MAX_IMAGE_DIMENSION`:

```python
WEBP_QUALITY = env_int_in_range('WEBP_QUALITY', 82, 1, 100)
```

- [ ] **Step 4: Run configuration tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_image_resizing.ImageSizeConfigTest \
  tests.test_image_resizing.WebPQualityConfigTest -v
```

Expected: all six tests pass and the command ends with `OK`.

- [ ] **Step 5: Commit bounded WebP configuration**

```bash
git add app.py tests/test_image_resizing.py
git commit -m "feat: add WebP quality configuration"
```

---

### Task 2: Preserve clipboard source bytes and format

**Files:**
- Modify: `app.py:1-100`
- Create: `tests/test_clipboard_image.py`

**Interfaces:**
- Consumes: Pillow `Image.open()` and the raw bytes returned by AppKit `NSData`.
- Produces: immutable `ClipboardImage(image: Image.Image, raw_bytes: bytes, source_format: str)`, `decode_clipboard_image(raw_bytes: bytes) -> ClipboardImage`, `CLIPBOARD_IMAGE_TYPES: tuple`, and `get_clipboard_image() -> Optional[ClipboardImage]`.

- [ ] **Step 1: Create failing clipboard decoding tests**

Create `tests/test_clipboard_image.py` with:

```python
import io
import unittest

from PIL import Image

import app


def image_bytes(image_format):
    output = io.BytesIO()
    Image.new("RGBA", (2, 2), (10, 20, 30, 0)).save(
        output,
        format=image_format,
    )
    return output.getvalue()


class ClipboardImageDecodingTest(unittest.TestCase):
    def test_webp_source_bytes_and_format_are_preserved(self):
        raw_bytes = image_bytes("WEBP")

        result = app.decode_clipboard_image(raw_bytes)

        self.assertIsInstance(result, app.ClipboardImage)
        self.assertEqual(raw_bytes, result.raw_bytes)
        self.assertEqual("WEBP", result.source_format)
        self.assertEqual((2, 2), result.image.size)

    def test_non_webp_format_is_detected_from_decoded_bytes(self):
        raw_bytes = image_bytes("PNG")

        result = app.decode_clipboard_image(raw_bytes)

        self.assertEqual(raw_bytes, result.raw_bytes)
        self.assertEqual("PNG", result.source_format)

    def test_webp_clipboard_types_are_tried_before_png_and_tiff(self):
        self.assertEqual(
            ("org.webmproject.webp", "public.webp"),
            app.CLIPBOARD_IMAGE_TYPES[:2],
        )
        self.assertLess(
            app.CLIPBOARD_IMAGE_TYPES.index("public.webp"),
            app.CLIPBOARD_IMAGE_TYPES.index("public.png"),
        )
        self.assertLess(
            app.CLIPBOARD_IMAGE_TYPES.index("public.png"),
            app.CLIPBOARD_IMAGE_TYPES.index("public.tiff"),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run clipboard tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_clipboard_image -v
```

Expected: tests report `ERROR` because `ClipboardImage`, `decode_clipboard_image`, and `CLIPBOARD_IMAGE_TYPES` do not exist.

- [ ] **Step 3: Add the clipboard value object and decoder**

Add this import near the top of `app.py`:

```python
from dataclasses import dataclass
```

Add these definitions before `get_clipboard_image()`:

```python
CLIPBOARD_IMAGE_TYPES = (
    "org.webmproject.webp",
    "public.webp",
    "public.png",
    "public.tiff",
    "public.image",
    "NSBitmapImageRep",
)


@dataclass(frozen=True)
class ClipboardImage:
    image: Image.Image
    raw_bytes: bytes
    source_format: str


def decode_clipboard_image(raw_bytes):
    """Decode clipboard bytes while retaining their original representation."""
    with io.BytesIO(raw_bytes) as image_data:
        image = Image.open(image_data)
        source_format = (image.format or "").upper()
        image.load()

    return ClipboardImage(
        image=image,
        raw_bytes=raw_bytes,
        source_format=source_format,
    )
```

- [ ] **Step 4: Update the AppKit reader to return `ClipboardImage`**

Replace `get_clipboard_image()` with:

```python
def get_clipboard_image():
    """获取剪贴板中的图片及其原始字节和格式。"""
    try:
        from AppKit import NSPasteboard

        pasteboard = NSPasteboard.generalPasteboard()
        items = pasteboard.pasteboardItems()
        if not items:
            return None

        for item in items:
            types = item.types()
            for data_type in CLIPBOARD_IMAGE_TYPES:
                if data_type not in types:
                    continue

                try:
                    data = item.dataForType_(data_type)
                    if data:
                        raw_bytes = bytes(data.bytes())
                        return decode_clipboard_image(raw_bytes)
                except Exception:
                    continue

        return None
    except Exception as e:
        logger.exception("获取剪贴板图片失败 | error=%s", e)
        return None
```

- [ ] **Step 5: Run clipboard tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_clipboard_image -v
```

Expected: all three tests pass and the command ends with `OK`.

- [ ] **Step 6: Commit source preservation**

```bash
git add app.py tests/test_clipboard_image.py
git commit -m "feat: preserve clipboard image source data"
```

---

### Task 3: Prepare WebP upload payloads

**Files:**
- Modify: `app.py:100-178`
- Create: `tests/test_webp_encoding.py`

**Interfaces:**
- Consumes: `ClipboardImage` from Task 2, a processed Pillow image, a `pixels_changed` flag, and an integer WebP quality.
- Produces: immutable `UploadPayload(data: bytes, filename: str, content_type: str, processing: str)`, `encode_webp(image: Image.Image, quality: int) -> bytes`, and `prepare_upload_payload(source: ClipboardImage, processed_image: Image.Image, pixels_changed: bool, quality: int) -> UploadPayload`.

- [ ] **Step 1: Create failing WebP encoding and payload tests**

Create `tests/test_webp_encoding.py` with:

```python
import io
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import app


class WebPEncodingTest(unittest.TestCase):
    def test_encoded_bytes_are_readable_webp(self):
        encoded = app.encode_webp(
            Image.new("RGB", (8, 8), "navy"),
            82,
        )

        with Image.open(io.BytesIO(encoded)) as result:
            self.assertEqual("WEBP", result.format)
            self.assertEqual((8, 8), result.size)

    def test_encoder_uses_quality_method_and_only_icc_metadata(self):
        image = Mock()
        image.info = {
            "icc_profile": b"icc-profile",
            "exif": b"private-exif",
            "xmp": b"private-xmp",
        }

        result = app.encode_webp(image, 73)

        self.assertEqual(b"", result)
        options = image.save.call_args.kwargs
        self.assertEqual("WEBP", options["format"])
        self.assertEqual(73, options["quality"])
        self.assertEqual(6, options["method"])
        self.assertEqual(b"icc-profile", options["icc_profile"])
        self.assertNotIn("exif", options)
        self.assertNotIn("xmp", options)

    def test_alpha_is_preserved(self):
        source = Image.new("RGBA", (4, 4), (255, 0, 0, 0))

        encoded = app.encode_webp(source, 82)

        with Image.open(io.BytesIO(encoded)) as result:
            result.load()
            self.assertEqual("RGBA", result.mode)
            self.assertEqual(0, result.getpixel((0, 0))[3])


class UploadPayloadDecisionTest(unittest.TestCase):
    def make_source(self, source_format="WEBP", raw_bytes=b"source-webp"):
        return app.ClipboardImage(
            image=Image.new("RGB", (2, 2), "white"),
            raw_bytes=raw_bytes,
            source_format=source_format,
        )

    def test_unchanged_webp_passes_through_exact_bytes(self):
        source = self.make_source()

        with patch.object(app, "encode_webp") as encode_mock:
            payload = app.prepare_upload_payload(
                source,
                source.image,
                pixels_changed=False,
                quality=82,
            )

        self.assertEqual(source.raw_bytes, payload.data)
        self.assertEqual("passthrough", payload.processing)
        self.assertEqual("clipboard.webp", payload.filename)
        self.assertEqual("image/webp", payload.content_type)
        encode_mock.assert_not_called()

    def test_changed_webp_and_non_webp_are_encoded(self):
        cases = (("WEBP", True), ("PNG", False))
        for source_format, pixels_changed in cases:
            with self.subTest(
                source_format=source_format,
                pixels_changed=pixels_changed,
            ):
                source = self.make_source(source_format=source_format)
                processed = Image.new("RGB", (2, 2), "gray")
                with patch.object(
                    app,
                    "encode_webp",
                    return_value=b"encoded-webp",
                ) as encode_mock:
                    payload = app.prepare_upload_payload(
                        source,
                        processed,
                        pixels_changed=pixels_changed,
                        quality=82,
                    )

                self.assertEqual(b"encoded-webp", payload.data)
                self.assertEqual("encoded", payload.processing)
                encode_mock.assert_called_once_with(processed, 82)

    def test_size_log_reports_actual_reduction(self):
        source = self.make_source(
            source_format="PNG",
            raw_bytes=b"0123456789",
        )
        with (
            patch.object(app, "encode_webp", return_value=b"1234"),
            self.assertLogs("picup.app", level="INFO") as captured,
        ):
            app.prepare_upload_payload(
                source,
                source.image,
                pixels_changed=False,
                quality=82,
            )

        self.assertIn("source_format=PNG", captured.output[0])
        self.assertIn("processing=encoded", captured.output[0])
        self.assertIn("input_bytes=10", captured.output[0])
        self.assertIn("output_bytes=4", captured.output[0])
        self.assertIn("reduction_pct=60.0", captured.output[0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run WebP tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_webp_encoding -v
```

Expected: tests report `ERROR` because `encode_webp`, `UploadPayload`, and `prepare_upload_payload` do not exist.

- [ ] **Step 3: Implement WebP encoding and payload selection**

Add these definitions after `add_watermark()` and before `upload_to_s3()` in `app.py`:

```python
@dataclass(frozen=True)
class UploadPayload:
    data: bytes
    filename: str
    content_type: str
    processing: str


def encode_webp(image, quality):
    """Encode a Pillow image as lossy WebP with size-focused settings."""
    output = io.BytesIO()
    save_options = {
        "format": "WEBP",
        "quality": quality,
        "method": 6,
    }
    icc_profile = image.info.get("icc_profile")
    if icc_profile:
        save_options["icc_profile"] = icc_profile

    image.save(output, **save_options)
    return output.getvalue()


def prepare_upload_payload(
    source,
    processed_image,
    pixels_changed,
    quality,
):
    """Pass through unchanged WebP or encode the processed image as WebP."""
    if source.source_format == "WEBP" and not pixels_changed:
        data = source.raw_bytes
        processing = "passthrough"
    else:
        data = encode_webp(processed_image, quality)
        processing = "encoded"

    input_bytes = len(source.raw_bytes)
    output_bytes = len(data)
    reduction_pct = (
        (input_bytes - output_bytes) / input_bytes * 100
        if input_bytes
        else 0.0
    )
    logger.info(
        "图片已准备 | source_format=%s | processing=%s | "
        "input_bytes=%s | output_bytes=%s | reduction_pct=%.1f",
        source.source_format or "UNKNOWN",
        processing,
        input_bytes,
        output_bytes,
        reduction_pct,
    )

    return UploadPayload(
        data=data,
        filename="clipboard.webp",
        content_type="image/webp",
        processing=processing,
    )
```

- [ ] **Step 4: Run WebP tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_webp_encoding -v
```

Expected: all six tests pass and the command ends with `OK`.

- [ ] **Step 5: Commit WebP payload preparation**

```bash
git add app.py tests/test_webp_encoding.py
git commit -m "feat: prepare optimized WebP payloads"
```

---

### Task 4: Upload prepared bytes with WebP metadata

**Files:**
- Modify: `app.py:178-253`
- Modify: `tests/test_upload_logging.py:1-81`

**Interfaces:**
- Consumes: `UploadPayload` from Task 3 and existing S3 configuration constants.
- Produces: `upload_to_s3(payload: UploadPayload) -> Optional[str]`; uploads `payload.data` using `payload.filename` and `payload.content_type`.

- [ ] **Step 1: Replace upload tests with byte-payload expectations**

Replace `tests/test_upload_logging.py` with:

```python
import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app


class UploadLoggingTest(unittest.TestCase):
    def make_payload(self):
        return app.UploadPayload(
            data=b"webp-payload",
            filename="clipboard.webp",
            content_type="image/webp",
            processing="encoded",
        )

    def test_success_uploads_bytes_and_logs_same_object_key(self):
        s3_client = Mock()
        payload = self.make_payload()

        with (
            patch.multiple(
                app,
                S3_BUCKET="images",
                S3_REGION="cn-test-1",
                S3_ENDPOINT=None,
            ),
            patch.object(app.boto3, "client", return_value=s3_client),
            patch.object(app.time, "time", return_value=1720942221),
            patch.object(app.time, "perf_counter", side_effect=[10.0, 10.125]),
            patch.object(
                app.uuid,
                "uuid4",
                return_value=SimpleNamespace(hex="abc123"),
            ),
            self.assertLogs("picup.app", level="INFO") as captured,
        ):
            result = app.upload_to_s3(payload)

        upload_call = s3_client.upload_fileobj.call_args
        uploaded_stream, bucket, object_key = upload_call.args
        self.assertEqual(b"webp-payload", uploaded_stream.read())
        self.assertEqual("images", bucket)
        self.assertRegex(
            object_key,
            re.compile(r"^\d{4}/\d{2}/1720942221_abc123_clipboard\.webp$"),
        )
        self.assertEqual(
            {"ContentType": "image/webp"},
            upload_call.kwargs["ExtraArgs"],
        )
        self.assertEqual(
            result,
            f"https://images.s3.cn-test-1.amazonaws.com/{object_key}",
        )
        start_message, success_message = captured.output
        self.assertIn(f"开始上传 | object_key={object_key}", start_message)
        self.assertIn(f"上传成功 | object_key={object_key}", success_message)
        self.assertIn("duration_ms=125", success_message)

    def test_failure_logs_webp_object_key_and_reason(self):
        s3_client = Mock()
        s3_client.upload_fileobj.side_effect = RuntimeError("network down")
        payload = self.make_payload()

        with (
            patch.multiple(
                app,
                S3_BUCKET="images",
                S3_REGION="cn-test-1",
                S3_ENDPOINT=None,
            ),
            patch.object(app.boto3, "client", return_value=s3_client),
            patch.object(app.time, "time", return_value=1720942221),
            patch.object(app.time, "perf_counter", return_value=10.0),
            patch.object(
                app.uuid,
                "uuid4",
                return_value=SimpleNamespace(hex="abc123"),
            ),
            self.assertLogs("picup.app", level="ERROR") as captured,
        ):
            result = app.upload_to_s3(payload)

        object_key = s3_client.upload_fileobj.call_args.args[2]
        self.assertIsNone(result)
        self.assertTrue(object_key.endswith("clipboard.webp"))
        self.assertIn(f"上传失败 | object_key={object_key}", captured.output[0])
        self.assertIn("error=network down", captured.output[0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run upload tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_upload_logging -v
```

Expected: both tests fail because the current `upload_to_s3()` expects an image and a filename and still writes PNG metadata.

- [ ] **Step 3: Replace image encoding inside `upload_to_s3()` with payload bytes**

Replace `upload_to_s3()` in `app.py` with:

```python
def upload_to_s3(payload):
    """上传已经准备好的图片字节到 S3。"""
    unique_filename = None
    try:
        if not S3_BUCKET or not S3_REGION:
            logger.error("上传失败 | object_key=- | error=S3 配置不完整")
            return None

        no_proxy = Config(proxies={})
        s3 = boto3.client(
            's3',
            region_name=S3_REGION,
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            config=no_proxy
        )

        image_stream = io.BytesIO(payload.data)

        from datetime import datetime
        now = datetime.now()
        year_month = f"{now.year}/{now.month:02d}"
        unique_filename = (
            f"{year_month}/{int(time.time())}_{uuid.uuid4().hex}_"
            f"{payload.filename}"
        )

        logger.info("开始上传 | object_key=%s", unique_filename)
        started_at = time.perf_counter()
        s3.upload_fileobj(
            image_stream,
            S3_BUCKET,
            unique_filename,
            ExtraArgs={'ContentType': payload.content_type}
        )

        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "上传成功 | object_key=%s | duration_ms=%.0f",
            unique_filename,
            duration_ms,
        )

        if S3_ENDPOINT:
            return f"{S3_ENDPOINT}/{S3_BUCKET}/{unique_filename}"
        return (
            f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/"
            f"{unique_filename}"
        )
    except NoCredentialsError:
        logger.error(
            "上传失败 | object_key=%s | error=S3 凭证错误",
            unique_filename or "-",
        )
        return None
    except Exception as e:
        logger.exception(
            "上传失败 | object_key=%s | error=%s",
            unique_filename or "-",
            e,
        )
        return None
```

- [ ] **Step 4: Run upload tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_upload_logging -v
```

Expected: both tests pass and the command ends with `OK`.

- [ ] **Step 5: Commit byte-oriented S3 upload**

```bash
git add app.py tests/test_upload_logging.py
git commit -m "feat: upload WebP byte payloads"
```

---

### Task 5: Integrate passthrough and encoding into `/upload`

**Files:**
- Modify: `app.py:276-308`
- Modify: `tests/test_image_resizing.py:89-124`

**Interfaces:**
- Consumes: `ClipboardImage`, `resize_image_if_needed()`, `add_watermark()`, `prepare_upload_payload()`, `WEBP_QUALITY`, and `upload_to_s3(payload)`.
- Produces: `/upload` data flow `clipboard -> resize -> optional watermark -> prepare payload -> S3`, with an explicit `pixels_changed: bool` decision.

- [ ] **Step 1: Replace the upload pipeline test with WebP-aware failing tests**

Replace `UploadResizePipelineTest` in `tests/test_image_resizing.py` with:

```python
class UploadResizePipelineTest(unittest.TestCase):
    def make_source(self, source_format="PNG"):
        return app.ClipboardImage(
            image=Image.new("RGB", (4000, 2000), "white"),
            raw_bytes=b"source-image",
            source_format=source_format,
        )

    def make_payload(self, processing="encoded"):
        return app.UploadPayload(
            data=b"webp-payload",
            filename="clipboard.webp",
            content_type="image/webp",
            processing=processing,
        )

    def test_upload_resizes_then_watermarks_then_prepares_and_uploads(self):
        source = self.make_source()
        resized_image = Image.new("RGB", (1920, 960), "white")
        watermarked_image = Image.new("RGB", (1920, 960), "gray")
        payload = self.make_payload()
        url = "https://example.test/clipboard.webp"
        pipeline = Mock()
        pipeline.resize.return_value = resized_image
        pipeline.watermark.return_value = watermarked_image
        pipeline.prepare.return_value = payload
        pipeline.upload.return_value = url

        with (
            patch.multiple(
                app,
                MAX_IMAGE_DIMENSION=1920,
                WEBP_QUALITY=82,
                WATERMARK_TEXT="PicUp",
            ),
            patch.object(app, "get_clipboard_image", return_value=source),
            patch.object(app, "resize_image_if_needed", pipeline.resize),
            patch.object(app, "add_watermark", pipeline.watermark),
            patch.object(app, "prepare_upload_payload", pipeline.prepare),
            patch.object(app, "upload_to_s3", pipeline.upload),
            patch.object(app, "copy_to_clipboard") as copy_mock,
            patch.object(app, "show_notification") as notification_mock,
        ):
            response = app.app.test_client().post("/upload")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"success": True, "result": url}, response.get_json())
        self.assertEqual(
            [
                call.resize(source.image, 1920),
                call.watermark(resized_image),
                call.prepare(source, watermarked_image, True, 82),
                call.upload(payload),
            ],
            pipeline.mock_calls,
        )
        copy_mock.assert_called_once_with(url)
        notification_mock.assert_called_once()

    def test_empty_watermark_and_no_resize_allow_passthrough_decision(self):
        source = app.ClipboardImage(
            image=Image.new("RGB", (1200, 800), "white"),
            raw_bytes=b"source-webp",
            source_format="WEBP",
        )
        payload = self.make_payload(processing="passthrough")
        pipeline = Mock()
        pipeline.resize.return_value = source.image
        pipeline.prepare.return_value = payload
        pipeline.upload.return_value = "https://example.test/clipboard.webp"

        with (
            patch.multiple(
                app,
                MAX_IMAGE_DIMENSION=1920,
                WEBP_QUALITY=82,
                WATERMARK_TEXT="",
            ),
            patch.object(app, "get_clipboard_image", return_value=source),
            patch.object(app, "resize_image_if_needed", pipeline.resize),
            patch.object(app, "add_watermark") as watermark_mock,
            patch.object(app, "prepare_upload_payload", pipeline.prepare),
            patch.object(app, "upload_to_s3", pipeline.upload),
            patch.object(app, "copy_to_clipboard"),
            patch.object(app, "show_notification"),
        ):
            response = app.app.test_client().post("/upload")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            [
                call.resize(source.image, 1920),
                call.prepare(source, source.image, False, 82),
                call.upload(payload),
            ],
            pipeline.mock_calls,
        )
        watermark_mock.assert_not_called()

    def test_encoding_failure_returns_500_without_uploading(self):
        source = app.ClipboardImage(
            image=Image.new("RGB", (1200, 800), "white"),
            raw_bytes=b"source-png",
            source_format="PNG",
        )
        with (
            patch.multiple(
                app,
                MAX_IMAGE_DIMENSION=1920,
                WEBP_QUALITY=82,
                WATERMARK_TEXT="",
            ),
            patch.object(app, "get_clipboard_image", return_value=source),
            patch.object(
                app,
                "resize_image_if_needed",
                return_value=source.image,
            ),
            patch.object(
                app,
                "prepare_upload_payload",
                side_effect=OSError("WebP encode failed"),
            ),
            patch.object(app, "upload_to_s3") as upload_mock,
        ):
            response = app.app.test_client().post("/upload")

        self.assertEqual(500, response.status_code)
        self.assertEqual(
            {"success": False, "message": "WebP encode failed"},
            response.get_json(),
        )
        upload_mock.assert_not_called()
```

- [ ] **Step 2: Run pipeline tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_resizing.UploadResizePipelineTest -v
```

Expected: tests fail because `/upload` still treats `get_clipboard_image()` as a Pillow image, always calls `add_watermark()`, and passes the old image/filename arguments to `upload_to_s3()`.

- [ ] **Step 3: Implement the WebP-aware route pipeline**

Replace `/upload` in `app.py` with:

```python
@app.route('/upload', methods=['POST'])
def upload():
    """上传剪贴板图片到 S3。"""
    try:
        source = get_clipboard_image()
        if not source:
            logger.warning("剪贴板中没有图片")
            return jsonify({'success': False, 'message': '剪贴板中没有图片'}), 400

        resized_image = resize_image_if_needed(
            source.image,
            MAX_IMAGE_DIMENSION,
        )
        pixels_changed = resized_image is not source.image
        processed_image = resized_image

        if WATERMARK_TEXT:
            processed_image = add_watermark(resized_image)
            pixels_changed = True

        payload = prepare_upload_payload(
            source,
            processed_image,
            pixels_changed,
            WEBP_QUALITY,
        )
        url = upload_to_s3(payload)
        if not url:
            return jsonify({'success': False, 'message': '上传到 S3 失败'}), 500

        copy_to_clipboard(url)
        show_notification('上传成功', f'图片已上传到 S3\nURL 已复制到剪贴板')
        return jsonify({'success': True, 'result': url})
    except Exception as e:
        logger.exception("上传过程中出错 | error=%s", e)
        return jsonify({'success': False, 'message': str(e)}), 500
```

- [ ] **Step 4: Run pipeline and image processing tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_resizing -v
```

Expected: all image configuration, resizing, and upload pipeline tests pass and the command ends with `OK`.

- [ ] **Step 5: Commit route integration**

```bash
git add app.py tests/test_image_resizing.py
git commit -m "feat: integrate WebP upload pipeline"
```

---

### Task 6: Document behavior and run full verification

**Files:**
- Modify: `readme.md:25-39`
- Verify: `app.py`, `tests/test_clipboard_image.py`, `tests/test_webp_encoding.py`, `tests/test_image_resizing.py`, `tests/test_upload_logging.py`, `tests/test_logging_config.py`, `tests/test_operational_logging.py`

**Interfaces:**
- Consumes: completed WebP upload behavior from Tasks 1-5.
- Produces: user-facing configuration documentation and a verified release candidate with no uncommitted changes from this task.

- [ ] **Step 1: Document WebP output and configuration**

Replace the environment example in `readme.md` with:

```env
PICUP_HOST=127.0.0.1
PICUP_PORT=36677
PICUP_THREADS=4
MAX_IMAGE_DIMENSION=1920
WEBP_QUALITY=82
```

Replace the paragraph following the example with:

```markdown
`MAX_IMAGE_DIMENSION` 是上传图片允许的最长边像素数，默认 `1920`。超过限制的图片会等比例缩小，小图不会放大。

上传图片统一使用 WebP，`WEBP_QUALITY` 控制重新编码质量，默认 `82`，允许范围为 `1` 到 `100`。WebP 编码固定使用压缩方法 `6`，以较长的本地编码时间换取更小的 S3 对象。

当剪贴板提供的是原始 WebP、图片不需要缩放且 `WATERMARK_TEXT` 为空时，PicUp 会直接上传原始字节，不重复编码。默认水印文字为 `PicUp`，因此默认配置仍会重新编码图片。
```

- [ ] **Step 2: Run the complete unit test suite**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected: every discovered test passes and the command ends with `OK`.

- [ ] **Step 3: Verify a representative lossy WebP is smaller than PNG**

Run this in-memory comparison without creating repository files:

```bash
.venv/bin/python - <<'PY'
import io
from PIL import Image

state = 1
pixels = bytearray()
for _ in range(512 * 512):
    state = (1103515245 * state + 12345) & 0x7fffffff
    value = (state >> 16) & 0xff
    pixels.extend((value, (value * 3) % 256, (value * 7) % 256))

image = Image.frombytes("RGB", (512, 512), bytes(pixels))
png = io.BytesIO()
webp = io.BytesIO()
image.save(png, format="PNG")
image.save(webp, format="WEBP", quality=82, method=6)
print(f"png_bytes={len(png.getvalue())}")
print(f"webp_bytes={len(webp.getvalue())}")
assert len(webp.getvalue()) < len(png.getvalue())
PY
```

Expected: both sizes print, `webp_bytes` is smaller than `png_bytes`, and the command exits successfully.

- [ ] **Step 4: Check formatting, references, and worktree state**

Run:

```bash
git diff --check
rg -n "clipboard\.png|image/png|format='PNG'|format=\"PNG\"" \
  app.py tests/test_image_resizing.py tests/test_upload_logging.py readme.md
git status --short
```

Expected: `git diff --check` is silent; the search exits with status `1` and prints no stale PNG upload behavior; `git status --short` lists only the intended `readme.md` change before the final task commit.

- [ ] **Step 5: Commit documentation**

```bash
git add readme.md
git commit -m "docs: document WebP upload settings"
```

- [ ] **Step 6: Confirm final repository state and commit history**

Run:

```bash
git status --short
git log -6 --oneline
```

Expected: status is clean and the six most recent commits include the five implementation commits plus `docs: document WebP upload settings`.
