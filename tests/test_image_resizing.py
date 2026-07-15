import io
import unittest
from unittest.mock import Mock, call, patch

from PIL import Image

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


class UploadRealPipelineTest(unittest.TestCase):
    def make_source(self, image_format):
        raw_bytes = io.BytesIO()
        Image.new("RGBA", (16, 12), (10, 20, 30, 0)).save(
            raw_bytes,
            format=image_format,
        )
        return app.decode_clipboard_image(raw_bytes.getvalue())

    def upload_and_capture(self, source):
        url = "https://example.test/clipboard.webp"
        with (
            patch.multiple(
                app,
                MAX_IMAGE_DIMENSION=1920,
                WEBP_QUALITY=82,
                WATERMARK_TEXT="",
            ),
            patch.object(app, "get_clipboard_image", return_value=source),
            patch.object(app, "upload_to_s3", return_value=url) as upload_mock,
            patch.object(app, "copy_to_clipboard"),
            patch.object(app, "show_notification"),
        ):
            response = app.app.test_client().post("/upload")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"success": True, "result": url}, response.get_json())
        return upload_mock.call_args.args[0]

    def test_png_runs_through_real_pipeline_and_becomes_webp(self):
        source = self.make_source("PNG")

        payload = self.upload_and_capture(source)

        self.assertEqual("encoded", payload.processing)
        self.assertEqual("clipboard.webp", payload.filename)
        self.assertEqual("image/webp", payload.content_type)
        self.assertNotEqual(source.raw_bytes, payload.data)
        with Image.open(io.BytesIO(payload.data)) as uploaded:
            self.assertEqual("WEBP", uploaded.format)
            self.assertEqual(source.image.size, uploaded.size)

    def test_unchanged_webp_runs_through_real_pipeline_byte_for_byte(self):
        source = self.make_source("WEBP")

        payload = self.upload_and_capture(source)

        self.assertEqual("passthrough", payload.processing)
        self.assertEqual(source.raw_bytes, payload.data)


if __name__ == "__main__":
    unittest.main()
