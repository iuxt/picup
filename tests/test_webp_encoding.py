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

    def test_real_output_preserves_icc_but_drops_exif_and_xmp(self):
        source = Image.new("RGB", (4, 4), "navy")
        source.info.update(
            {
                "icc_profile": b"test-icc-profile",
                "exif": b"private-exif",
                "xmp": b"private-xmp",
            }
        )

        encoded = app.encode_webp(source, 82)

        with Image.open(io.BytesIO(encoded)) as result:
            self.assertEqual(b"test-icc-profile", result.info["icc_profile"])
            self.assertNotIn("exif", result.info)
            self.assertNotIn("xmp", result.info)


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
