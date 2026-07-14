import io
import logging
import re
import unittest

from logging_config import configure_logging


class LoggingConfigTest(unittest.TestCase):
    def setUp(self):
        root_logger = logging.getLogger()
        self.original_handlers = root_logger.handlers[:]
        self.original_level = root_logger.level

    def tearDown(self):
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.handlers.extend(self.original_handlers)
        root_logger.setLevel(self.original_level)

    def test_log_line_contains_local_time_level_and_message(self):
        output = io.StringIO()
        configure_logging(output)

        logging.getLogger("picup.test").info(
            "开始上传 | object_key=2026/07/example_clipboard.png"
        )

        line = output.getvalue().strip()
        self.assertRegex(
            line,
            re.compile(
                r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| INFO \| "
                r"开始上传 \| object_key=2026/07/example_clipboard\.png$"
            ),
        )


if __name__ == "__main__":
    unittest.main()
