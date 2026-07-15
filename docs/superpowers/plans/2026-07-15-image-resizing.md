# PicUp Image Resizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically resize oversized clipboard images before watermarking and S3 upload so the longest edge is at most a configurable 1920 pixels.

**Architecture:** Keep configuration and image processing in `app.py`, matching the existing small single-module application. Add one positive-integer environment parser and one focused `resize_image_if_needed(image, max_dimension)` function, then insert that function between clipboard acquisition and watermarking; test configuration, pure resizing behavior, logging, and pipeline order independently.

**Tech Stack:** Python 3.9/3.12, Pillow 11.3, Flask 3.1, standard-library `unittest` and `unittest.mock`

## Global Constraints

- `MAX_IMAGE_DIMENSION` defaults to the exact value `1920` and must be a positive integer.
- Resize against a `MAX_IMAGE_DIMENSION × MAX_IMAGE_DIMENSION` bounding box while preserving aspect ratio; never crop, stretch, or enlarge an image.
- Use Pillow Lanczos resampling and preserve the source image mode, including RGBA transparency.
- Resize before watermarking and before the existing PNG serialization and S3 upload.
- Emit one `INFO` log only when resizing occurs, including original size, resized size, and the configured maximum.
- Preserve `/upload` and `/health` response semantics, S3 naming and Content-Type, watermark settings, clipboard behavior, and notifications.
- Add no runtime dependency and do not add alternate output formats or responsive-image variants.

---

### Task 1: Positive image-size configuration

**Files:**
- Modify: `app.py:21-31`
- Modify: `readme.md:20-30`
- Create: `tests/test_image_resizing.py`

**Interfaces:**
- Consumes: `os.environ` after the existing `load_dotenv()` call.
- Produces: `env_positive_int(name, default) -> int` and module constant `MAX_IMAGE_DIMENSION: int`.

- [ ] **Step 1: Write failing configuration tests**

Create `tests/test_image_resizing.py`:

```python
import unittest
from unittest.mock import patch

import app


class ImageSizeConfigTest(unittest.TestCase):
    def test_missing_value_uses_default(self):
        with patch.dict(app.os.environ, {}, clear=True):
            result = app.env_positive_int("MAX_IMAGE_DIMENSION", 1920)

        self.assertEqual(1920, result)

    def test_positive_integer_value_is_used(self):
        with patch.dict(
            app.os.environ,
            {"MAX_IMAGE_DIMENSION": "2560"},
            clear=True,
        ):
            result = app.env_positive_int("MAX_IMAGE_DIMENSION", 1920)

        self.assertEqual(2560, result)

    def test_invalid_values_raise_configuration_error(self):
        for value in ("", "not-a-number", "0", "-1"):
            with self.subTest(value=value):
                with patch.dict(
                    app.os.environ,
                    {"MAX_IMAGE_DIMENSION": value},
                    clear=True,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "MAX_IMAGE_DIMENSION must be a positive integer",
                    ):
                        app.env_positive_int("MAX_IMAGE_DIMENSION", 1920)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the configuration tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_resizing.ImageSizeConfigTest -v
```

Expected: three tests report `ERROR` with `AttributeError: module 'app' has no attribute 'env_positive_int'`.

- [ ] **Step 3: Implement strict positive-integer configuration**

In `app.py`, insert this helper immediately after `app = Flask(__name__)`:

```python
def env_positive_int(name, default):
    """Read a positive integer environment setting."""
    value = os.getenv(name)
    if value is None:
        return default

    try:
        parsed_value = int(value)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be a positive integer, got {value!r}"
        ) from exc

    if parsed_value < 1:
        raise RuntimeError(
            f"{name} must be a positive integer, got {value!r}"
        )

    return parsed_value
```

After the existing S3 constants, add:

```python
# 图片尺寸配置
MAX_IMAGE_DIMENSION = env_positive_int('MAX_IMAGE_DIMENSION', 1920)
```

- [ ] **Step 4: Document the new environment setting**

Extend the `.env` example in `readme.md` to include the exact setting and explanation:

```env
PICUP_HOST=127.0.0.1
PICUP_PORT=36677
PICUP_THREADS=4
MAX_IMAGE_DIMENSION=1920
```

Immediately after that block, add:

```markdown
`MAX_IMAGE_DIMENSION` 是上传图片允许的最长边像素数，默认 `1920`。超过限制的图片会等比例缩小，小图不会放大。
```

- [ ] **Step 5: Run the configuration tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_resizing.ImageSizeConfigTest -v
```

Expected: three tests report `ok`; the command ends with `OK`.

- [ ] **Step 6: Run the full existing suite**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all nine tests pass; the command ends with `OK`.

- [ ] **Step 7: Commit the configuration slice**

```bash
git add app.py readme.md tests/test_image_resizing.py
git commit -m "feat: add image size configuration"
```

---

### Task 2: Proportional high-quality image resizing

**Files:**
- Modify: `app.py:34-76`
- Modify: `tests/test_image_resizing.py`

**Interfaces:**
- Consumes: a Pillow `Image.Image` and positive integer `max_dimension`.
- Produces: `resize_image_if_needed(image, max_dimension) -> Image.Image`; returns the original image when already within bounds and a resized copy when over the limit.

- [ ] **Step 1: Add failing resizing and logging tests**

Add `from PIL import Image` after the mock import in `tests/test_image_resizing.py`, then add this class before the `if __name__ == "__main__"` block:

```python
class ImageResizingTest(unittest.TestCase):
    def test_landscape_image_is_resized_by_longest_edge(self):
        image = Image.new("RGB", (4000, 2000), "white")

        result = app.resize_image_if_needed(image, 1920)

        self.assertEqual((1920, 960), result.size)

    def test_portrait_image_is_resized_by_longest_edge(self):
        image = Image.new("RGB", (2000, 4000), "white")

        result = app.resize_image_if_needed(image, 1920)

        self.assertEqual((960, 1920), result.size)

    def test_image_at_or_below_limit_is_not_enlarged(self):
        for size in ((1920, 1080), (1200, 800)):
            with self.subTest(size=size):
                image = Image.new("RGB", size, "white")

                with patch.object(app.logger, "info") as info_mock:
                    result = app.resize_image_if_needed(image, 1920)

                self.assertIs(image, result)
                self.assertEqual(size, result.size)
                info_mock.assert_not_called()

    def test_rgba_mode_and_transparency_are_preserved(self):
        image = Image.new("RGBA", (4000, 2000), (255, 0, 0, 0))

        result = app.resize_image_if_needed(image, 1920)

        self.assertEqual("RGBA", result.mode)
        self.assertEqual(0, result.getpixel((0, 0))[3])

    def test_resize_log_contains_original_target_and_limit(self):
        image = Image.new("RGB", (4000, 2000), "white")

        with self.assertLogs("picup.app", level="INFO") as captured:
            app.resize_image_if_needed(image, 1920)

        self.assertIn(
            "图片已缩放 | original_size=4000x2000 | "
            "resized_size=1920x960 | max_dimension=1920",
            captured.output[0],
        )
```

- [ ] **Step 2: Run the resizing tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_resizing.ImageResizingTest -v
```

Expected: five tests report `ERROR` with `AttributeError: module 'app' has no attribute 'resize_image_if_needed'`.

- [ ] **Step 3: Implement the focused resizing function**

In `app.py`, insert this function between `get_clipboard_image()` and `add_watermark()`:

```python
def resize_image_if_needed(image, max_dimension):
    """Shrink an oversized image proportionally without enlarging small images."""
    original_width, original_height = image.size
    if max(original_width, original_height) <= max_dimension:
        return image

    resized_image = image.copy()
    resized_image.thumbnail(
        (max_dimension, max_dimension),
        Image.Resampling.LANCZOS,
    )
    resized_width, resized_height = resized_image.size
    logger.info(
        "图片已缩放 | original_size=%sx%s | resized_size=%sx%s | "
        "max_dimension=%s",
        original_width,
        original_height,
        resized_width,
        resized_height,
        max_dimension,
    )
    return resized_image
```

- [ ] **Step 4: Run the image-resizing module tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_resizing -v
```

Expected: all eight tests report `ok`; the command ends with `OK`.

- [ ] **Step 5: Run the full suite**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all fourteen tests pass; the command ends with `OK`.

- [ ] **Step 6: Commit the resizing slice**

```bash
git add app.py tests/test_image_resizing.py
git commit -m "feat: resize oversized images"
```

---

### Task 3: Upload-pipeline integration

**Files:**
- Modify: `app.py:227-242`
- Modify: `tests/test_image_resizing.py`

**Interfaces:**
- Consumes: `MAX_IMAGE_DIMENSION` and `resize_image_if_needed(image, max_dimension)` from Tasks 1 and 2.
- Produces: `/upload` data flow `clipboard image -> resized image -> watermarked image -> upload_to_s3(...)` with the existing HTTP response contract.

- [ ] **Step 1: Add a failing pipeline-order test**

Change the mock import in `tests/test_image_resizing.py` to:

```python
from unittest.mock import Mock, call, patch
```

Then add this class before the `if __name__ == "__main__"` block:

```python
class UploadResizePipelineTest(unittest.TestCase):
    def test_upload_resizes_before_watermark_and_s3_upload(self):
        source_image = Image.new("RGB", (4000, 2000), "white")
        resized_image = Image.new("RGB", (1920, 960), "white")
        watermarked_image = Image.new("RGB", (1920, 960), "gray")
        url = "https://example.test/clipboard.png"
        pipeline = Mock()
        pipeline.resize.return_value = resized_image
        pipeline.watermark.return_value = watermarked_image
        pipeline.upload.return_value = url

        with (
            patch.object(app, "MAX_IMAGE_DIMENSION", 1920),
            patch.object(app, "get_clipboard_image", return_value=source_image),
            patch.object(app, "resize_image_if_needed", pipeline.resize),
            patch.object(app, "add_watermark", pipeline.watermark),
            patch.object(app, "upload_to_s3", pipeline.upload),
            patch.object(app, "copy_to_clipboard") as copy_mock,
            patch.object(app, "show_notification") as notification_mock,
        ):
            response = app.app.test_client().post("/upload")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"success": True, "result": url}, response.get_json())
        self.assertEqual(
            [
                call.resize(source_image, 1920),
                call.watermark(resized_image),
                call.upload(watermarked_image, "clipboard.png"),
            ],
            pipeline.mock_calls,
        )
        copy_mock.assert_called_once_with(url)
        notification_mock.assert_called_once()
```

- [ ] **Step 2: Run the pipeline test and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_resizing.UploadResizePipelineTest -v
```

Expected: `FAIL` because `pipeline.mock_calls` contains watermark and upload calls but no resize call, and watermark receives `source_image` instead of `resized_image`.

- [ ] **Step 3: Insert resizing before watermarking**

In `app.py`, replace the current watermark block inside `upload()` with:

```python
        # 缩小超过尺寸限制的图片
        resized_image = resize_image_if_needed(image, MAX_IMAGE_DIMENSION)

        # 在最终上传尺寸上添加水印
        watermarked_image = add_watermark(resized_image)
```

Keep the following call unchanged:

```python
        url = upload_to_s3(watermarked_image, 'clipboard.png')
```

- [ ] **Step 4: Run the pipeline test and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_image_resizing.UploadResizePipelineTest -v
```

Expected: one test reports `ok`; the command ends with `OK`.

- [ ] **Step 5: Run all tests and a whitespace check**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected: all fifteen tests pass, the test command ends with `OK`, and `git diff --check` prints no output.

- [ ] **Step 6: Commit the upload integration**

```bash
git add app.py tests/test_image_resizing.py
git commit -m "feat: resize images before upload"
```
