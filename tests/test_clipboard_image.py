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
