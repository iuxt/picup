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
