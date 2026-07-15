import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
