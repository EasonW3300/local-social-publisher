from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from social_publisher.api import create_app


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.dispatched: list[list[str]] = []
        self.client = TestClient(
            create_app(Path(self.temp.name), dispatch_jobs=self.dispatched.append)
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    @staticmethod
    def form(**overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "title": "一篇测试文章",
            "markdown": "# 正文\n\n这是正文。",
            "platforms": json.dumps(["wechat", "csdn"]),
            "image_usage": json.dumps({"wechat": "cover", "csdn": "body"}),
        }
        values.update(overrides)
        return values

    def test_health(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_preview_renders_only_selected_platforms(self) -> None:
        response = self.client.post(
            "/api/previews",
            data=self.form(
                platforms=json.dumps(["csdn"]),
                image_usage=json.dumps({"csdn": "body"}),
            ),
            files={"image": ("image.png", b"image", "image/png")},
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["platform"], "csdn")
        self.assertIn("{{IMAGE_URL}}", items[0]["body"])

    def test_submit_creates_grouped_jobs_and_dispatches_immediate_work(self) -> None:
        response = self.client.post(
            "/api/submissions",
            data=self.form(),
            files={"image": ("image.png", b"image", "image/png")},
        )
        self.assertEqual(response.status_code, 201)
        result = response.json()
        self.assertEqual(set(result["job_ids"]), {"wechat", "csdn"})
        self.assertEqual(self.dispatched, [list(result["job_ids"].values())])

        listed = self.client.get("/api/submissions").json()["items"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["post"]["title"], "一篇测试文章")
        self.assertEqual(len(listed[0]["jobs"]), 2)

    def test_duplicate_requires_explicit_confirmation(self) -> None:
        first = self.client.post(
            "/api/submissions",
            data=self.form(),
            files={"image": ("image.png", b"same", "image/png")},
        )
        self.assertEqual(first.status_code, 201)
        duplicate = self.client.post(
            "/api/submissions",
            data=self.form(),
            files={"image": ("image.png", b"same", "image/png")},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["detail"]["code"], "duplicate_submission")

        confirmed = self.client.post(
            "/api/submissions",
            data=self.form(confirm_duplicate="true"),
            files={"image": ("image.png", b"same", "image/png")},
        )
        self.assertEqual(confirmed.status_code, 201)

    def test_rejects_missing_platform_selection(self) -> None:
        response = self.client.post(
            "/api/submissions",
            data=self.form(platforms="[]", image_usage="{}"),
            files={"image": ("image.png", b"image", "image/png")},
        )
        self.assertEqual(response.status_code, 422)

    def test_scheduled_submission_is_not_immediately_dispatched(self) -> None:
        response = self.client.post(
            "/api/submissions",
            data=self.form(scheduled_at="2026-08-16T12:00:00+08:00"),
            files={"image": ("image.png", b"image", "image/png")},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.dispatched, [])


if __name__ == "__main__":
    unittest.main()
