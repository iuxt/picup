import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from PIL import Image

import app


def image_bytes(image_format):
    output = io.BytesIO()
    Image.new("RGBA", (2, 2), (10, 20, 30, 0)).save(
        output,
        format=image_format,
    )
    return output.getvalue()


def oriented_jpeg_bytes():
    output = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (3, 2), "red").save(
        output,
        format="JPEG",
        exif=exif,
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

    def test_exif_orientation_is_applied_before_metadata_is_dropped(self):
        raw_bytes = oriented_jpeg_bytes()

        result = app.decode_clipboard_image(raw_bytes)

        self.assertEqual(raw_bytes, result.raw_bytes)
        self.assertEqual("JPEG", result.source_format)
        self.assertEqual((2, 3), result.image.size)
        self.assertNotIn(274, result.image.getexif())


class ClipboardReaderFallbackTest(unittest.TestCase):
    def test_invalid_webp_representation_falls_back_to_png(self):
        png_bytes = image_bytes("PNG")
        data_by_type = {
            "org.webmproject.webp": b"not-a-webp",
            "public.png": png_bytes,
        }
        item = Mock()
        item.types.return_value = tuple(data_by_type)
        item.dataForType_.side_effect = lambda data_type: SimpleNamespace(
            bytes=lambda: memoryview(data_by_type[data_type])
        )
        pasteboard = Mock()
        pasteboard.pasteboardItems.return_value = [item]
        appkit = SimpleNamespace(
            NSPasteboard=SimpleNamespace(
                generalPasteboard=Mock(return_value=pasteboard)
            )
        )

        with patch.dict(sys.modules, {"AppKit": appkit}):
            result = app.get_clipboard_image()

        self.assertEqual("PNG", result.source_format)
        self.assertEqual(png_bytes, result.raw_bytes)
        self.assertEqual(
            [call("org.webmproject.webp"), call("public.png")],
            item.dataForType_.call_args_list,
        )


if __name__ == "__main__":
    unittest.main()
