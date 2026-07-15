import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app


class UploadLoggingTest(unittest.TestCase):
    def make_payload(self):
        return app.UploadPayload(
            data=b"webp-payload",
            filename="clipboard.webp",
            content_type="image/webp",
            processing="encoded",
        )

    def test_success_uploads_bytes_and_logs_same_object_key(self):
        s3_client = Mock()
        payload = self.make_payload()

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
            result = app.upload_to_s3(payload)

        upload_call = s3_client.upload_fileobj.call_args
        uploaded_stream, bucket, object_key = upload_call.args
        self.assertEqual(b"webp-payload", uploaded_stream.read())
        self.assertEqual("images", bucket)
        self.assertRegex(
            object_key,
            re.compile(r"^\d{4}/\d{2}/1720942221_abc123_clipboard\.webp$"),
        )
        self.assertEqual(
            {"ContentType": "image/webp"},
            upload_call.kwargs["ExtraArgs"],
        )
        self.assertEqual(
            result,
            f"https://images.s3.cn-test-1.amazonaws.com/{object_key}",
        )
        start_message, success_message = captured.output
        self.assertIn(f"开始上传 | object_key={object_key}", start_message)
        self.assertIn(f"上传成功 | object_key={object_key}", success_message)
        self.assertIn("duration_ms=125", success_message)

    def test_failure_logs_webp_object_key_and_reason(self):
        s3_client = Mock()
        s3_client.upload_fileobj.side_effect = RuntimeError("network down")
        payload = self.make_payload()

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
            result = app.upload_to_s3(payload)

        object_key = s3_client.upload_fileobj.call_args.args[2]
        self.assertIsNone(result)
        self.assertTrue(object_key.endswith("clipboard.webp"))
        self.assertIn(f"上传失败 | object_key={object_key}", captured.output[0])
        self.assertIn("error=network down", captured.output[0])


if __name__ == "__main__":
    unittest.main()
