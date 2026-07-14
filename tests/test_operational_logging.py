import ast
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import server


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class OperationalLoggingTest(unittest.TestCase):
    def test_clipboard_copy_error_is_logged(self):
        with (
            patch.object(
                app.subprocess,
                "run",
                side_effect=RuntimeError("pbcopy failed"),
            ),
            self.assertLogs("picup.app", level="ERROR") as captured,
        ):
            result = app.copy_to_clipboard("https://example.test/image.png")

        self.assertFalse(result)
        self.assertIn("复制到剪贴板失败 | error=pbcopy failed", captured.output[0])

    def test_server_main_logs_address_and_starts_waitress(self):
        environment = {
            "PICUP_HOST": "0.0.0.0",
            "PICUP_PORT": "4567",
            "PICUP_THREADS": "8",
        }
        with (
            patch.dict(server.os.environ, environment, clear=False),
            patch.object(server, "serve") as serve_mock,
            self.assertLogs("picup.server", level="INFO") as captured,
        ):
            server.main()

        self.assertIn(
            "PicUp 服务启动 | address=http://0.0.0.0:4567 | threads=8",
            captured.output[0],
        )
        serve_mock.assert_called_once_with(
            server.app,
            host="0.0.0.0",
            port=4567,
            threads=8,
        )

    def test_application_modules_have_no_direct_print_calls(self):
        print_locations = []
        for relative_path in ("app.py", "server.py"):
            tree = ast.parse((PROJECT_ROOT / relative_path).read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "print"
                ):
                    print_locations.append(f"{relative_path}:{node.lineno}")

        self.assertEqual([], print_locations)


if __name__ == "__main__":
    unittest.main()
