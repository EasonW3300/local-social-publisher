from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from social_publisher.api import create_app
from social_publisher.secrets import MemorySecretStore
from social_publisher.settings import SettingsService
from social_publisher.storage import Repository


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

    def test_wechat_settings_never_return_the_secret(self) -> None:
        data_dir = Path(self.temp.name) / "settings-app"
        repository = Repository(data_dir / "publisher.sqlite3")
        repository.initialize()
        settings = SettingsService(repository, MemorySecretStore())
        with TestClient(create_app(data_dir, settings_service=settings)) as client:
            updated = client.put(
                "/api/settings/wechat",
                json={
                    "app_id": "wx-app",
                    "app_secret": "top-secret",
                    "browser_fallback_enabled": True,
                },
            )
            self.assertEqual(updated.status_code, 200)
            self.assertNotIn("app_secret", updated.json())
            self.assertTrue(updated.json()["official_configured"])

    def test_browser_login_endpoint_dispatches_visible_profile(self) -> None:
        opened: list[str] = []
        data_dir = Path(self.temp.name) / "browser-app"
        with TestClient(
            create_app(
                data_dir,
                open_csdn_login=lambda: opened.append("csdn"),
                open_wechat_login=lambda: opened.append("wechat"),
            )
        ) as client:
            self.assertEqual(client.post("/api/browser/csdn/login").status_code, 202)
            self.assertEqual(client.post("/api/browser/wechat/login").status_code, 202)
        self.assertEqual(opened, ["csdn", "wechat"])

    def test_built_frontend_can_be_served_from_loopback_app(self) -> None:
        frontend = Path(self.temp.name) / "static"
        frontend.mkdir()
        (frontend / "index.html").write_text("<h1>Publisher UI</h1>")
        with TestClient(
            create_app(Path(self.temp.name) / "static-app", frontend_dir=frontend)
        ) as client:
            response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Publisher UI", response.text)


if __name__ == "__main__":
    unittest.main()
