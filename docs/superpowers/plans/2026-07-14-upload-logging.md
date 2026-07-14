# PicUp Upload Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add consistent, timestamped application logs that identify the full S3 object path and report upload start, success, duration, and failure.

**Architecture:** Add one small `logging_config.py` module that owns the root logger format and stdout handler. `app.py` and `server.py` will use named loggers; S3 upload logging stays next to the upload call so its start, result, object key, and duration share one source of truth.

**Tech Stack:** Python 3.12, standard-library `logging` and `unittest`, Flask, boto3, Pillow, Waitress

## Global Constraints

- Format every application log as `YYYY-MM-DD HH:MM:SS | LEVEL | message` using the process's local timezone.
- Write application logs to standard output so launchd continues collecting them in `logs/stdout.log`.
- Record the generated full S3 `object_key` for upload start, success, and failure; never log credentials, tokens, or image bytes.
- Preserve `/upload` and `/health` responses, S3 object naming, PNG conversion, watermarking, clipboard behavior, and notification behavior.
- Add no runtime dependency and do not add JSON logging or log rotation.

---

### Task 1: Central logging configuration

**Files:**
- Create: `logging_config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_logging_config.py`

**Interfaces:**
- Consumes: Python standard-library `logging`; optional text stream passed by tests.
- Produces: `configure_logging(stream=None) -> None`, `LOG_FORMAT`, and `DATE_FORMAT`.

- [ ] **Step 1: Write the failing formatter test**

Create an empty `tests/__init__.py`, then create `tests/test_logging_config.py`:

```python
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
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_logging_config -v
```

Expected: `ERROR` with `ModuleNotFoundError: No module named 'logging_config'`.

- [ ] **Step 3: Implement the minimal central configuration**

Create `logging_config.py`:

```python
import logging
import sys


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(stream=None):
    """Configure all application loggers with one readable stdout format."""
    if stream is None:
        stream = sys.stdout

    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
```

- [ ] **Step 4: Run the formatter test and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_logging_config -v
```

Expected: one test reports `ok`; the command ends with `OK`.

- [ ] **Step 5: Commit the central configuration**

```bash
git add logging_config.py tests/__init__.py tests/test_logging_config.py
git commit -m "feat: add timestamped logging configuration"
```

---

### Task 2: S3 upload lifecycle logs

**Files:**
- Modify: `app.py:1-21,124-180`
- Create: `tests/test_upload_logging.py`

**Interfaces:**
- Consumes: `configure_logging()` from Task 1 and the existing `upload_to_s3(image, filename) -> str | None` API.
- Produces: named logger `picup.app` and upload messages containing `object_key` plus `duration_ms` on success.

- [ ] **Step 1: Write the failing successful-upload logging test**

Create `tests/test_upload_logging.py`:

```python
import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

import app


class UploadLoggingTest(unittest.TestCase):
    def test_success_logs_start_and_completion_with_same_object_key(self):
        s3_client = Mock()
        image = Image.new("RGB", (2, 2), "white")

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
            result = app.upload_to_s3(image, "clipboard.png")

        object_key = s3_client.upload_fileobj.call_args.args[2]
        self.assertRegex(
            object_key,
            re.compile(r"^\d{4}/\d{2}/1720942221_abc123_clipboard\.png$"),
        )
        self.assertEqual(
            result,
            f"https://images.s3.cn-test-1.amazonaws.com/{object_key}",
        )
        start_message, success_message = captured.output
        self.assertIn(f"开始上传 | object_key={object_key}", start_message)
        self.assertIn(f"上传成功 | object_key={object_key}", success_message)
        self.assertIn("duration_ms=125", success_message)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_upload_logging -v
```

Expected: `FAIL` because `assertLogs` reports that no `INFO` logs were emitted by `picup.app`.

- [ ] **Step 3: Implement upload start and success logs**

Add `import logging` to the standard-library imports and `from logging_config import configure_logging` after the third-party imports. Immediately after `load_dotenv()`, add:

```python
configure_logging()
logger = logging.getLogger("picup.app")
```

Immediately after `unique_filename` is created, replace the existing `upload_fileobj` block with:

```python
        logger.info("开始上传 | object_key=%s", unique_filename)
        started_at = time.perf_counter()

        s3.upload_fileobj(
            img_byte_arr,
            S3_BUCKET,
            unique_filename,
            ExtraArgs={'ContentType': 'image/png'}
        )

        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "上传成功 | object_key=%s | duration_ms=%.0f",
            unique_filename,
            duration_ms,
        )
```

- [ ] **Step 4: Run the successful-upload test and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_upload_logging -v
```

Expected: one test reports `ok`; the command ends with `OK`.

- [ ] **Step 5: Add the failing upload-error logging test**

Add this method to `UploadLoggingTest`:

```python
    def test_failure_logs_object_key_and_reason(self):
        s3_client = Mock()
        s3_client.upload_fileobj.side_effect = RuntimeError("network down")
        image = Image.new("RGB", (2, 2), "white")

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
            result = app.upload_to_s3(image, "clipboard.png")

        object_key = s3_client.upload_fileobj.call_args.args[2]
        self.assertIsNone(result)
        self.assertIn(f"上传失败 | object_key={object_key}", captured.output[0])
        self.assertIn("error=network down", captured.output[0])
```

- [ ] **Step 6: Run the upload tests and verify the new test is RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_upload_logging -v
```

Expected: the success test reports `ok`; the failure test reports `FAIL` because the existing exception handler prints instead of emitting an `ERROR` log.

- [ ] **Step 7: Implement upload error logs without changing return values**

Insert `unique_filename = None` immediately after the `upload_to_s3` docstring. Replace the incomplete-configuration branch with:

```python
        if not S3_BUCKET or not S3_REGION:
            logger.error("上传失败 | object_key=- | error=S3 配置不完整")
            return None
```

Replace the two exception handlers at the end of `upload_to_s3` with:

```python
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

- [ ] **Step 8: Run both upload tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_upload_logging -v
```

Expected: two tests report `ok`; the command ends with `OK`.

- [ ] **Step 9: Commit upload lifecycle logging**

```bash
git add app.py tests/test_upload_logging.py
git commit -m "feat: log S3 upload lifecycle"
```

---

### Task 3: Remaining application and startup logs

**Files:**
- Modify: `app.py:29-120,183-232`
- Modify: `server.py:1-29`
- Create: `tests/test_operational_logging.py`

**Interfaces:**
- Consumes: the configured root logger and existing helper return values.
- Produces: `picup.server` startup logger, testable `server.main() -> None`, and no direct `print` calls in application Python modules.

- [ ] **Step 1: Write failing helper, startup, and print-migration tests**

Create `tests/test_operational_logging.py`:

```python
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
```

- [ ] **Step 2: Run the operational tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_operational_logging -v
```

Expected: the clipboard and direct-`print` assertions report `FAIL`, while the missing `server.main` reports `ERROR`.

- [ ] **Step 3: Replace the remaining `app.py` prints with named logger calls**

Use these replacements inside the corresponding existing branches, keeping their current return values:

```python
logger.exception("获取剪贴板图片失败 | error=%s", e)
logger.exception("添加水印失败 | error=%s", e)
logger.exception("复制到剪贴板失败 | error=%s", e)
logger.exception("显示通知失败 | error=%s", e)
logger.warning("剪贴板中没有图片")
logger.exception("上传过程中出错 | error=%s", e)
```

The S3 configuration, credential, and upload exception outputs were migrated in Task 2.

- [ ] **Step 4: Extract and log the testable Waitress startup path**

Replace `server.py` with:

```python
import logging
import os

from dotenv import load_dotenv
from waitress import serve

from app import app


load_dotenv()
logger = logging.getLogger("picup.server")


def env_int(name, default):
    value = os.getenv(name)
    if not value:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {value!r}") from exc


def main():
    host = os.getenv('PICUP_HOST', '127.0.0.1')
    port = env_int('PICUP_PORT', 36677)
    threads = env_int('PICUP_THREADS', 4)

    logger.info(
        "PicUp 服务启动 | address=http://%s:%s | threads=%s",
        host,
        port,
        threads,
    )
    serve(app, host=host, port=port, threads=threads)


if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Run operational tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_operational_logging -v
```

Expected: three tests report `ok`; the command ends with `OK`.

- [ ] **Step 6: Run the complete regression suite**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all six tests report `ok`; the command ends with `OK`, with no warnings or unexpected output.

- [ ] **Step 7: Check source and diff hygiene**

Run:

```bash
.venv/bin/python -m compileall -q app.py server.py logging_config.py tests
git diff --check
git status --short
```

Expected: compilation and `git diff --check` produce no output; status lists only the intended Python/test changes plus the user's pre-existing untracked `.env.bak`.

- [ ] **Step 8: Commit the completed migration**

```bash
git add app.py server.py tests/test_operational_logging.py
git commit -m "refactor: standardize application logs"
```

---

## Final verification

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q app.py server.py logging_config.py tests
git diff --check
git status --short
```

Expected: six passing tests, successful bytecode compilation, no whitespace errors, and no unintended tracked changes. Leave `.env.bak` untouched.
