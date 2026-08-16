from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from social_publisher.adapters.browser import BrowserPublishReceipt
from social_publisher.adapters.wechat_browser import WeChatBrowserFallbackAdapter
from social_publisher.domain import JobStatus
from social_publisher.jobs import PermanentPublishError, PublishResult
from social_publisher.routing import WeChatRoutingAdapter
from social_publisher.secrets import MemorySecretStore
from social_publisher.settings import SettingsService
from social_publisher.storage import JobContext, Repository


class FakeBrowserDriver:
    def publish_article(self, job: JobContext) -> BrowserPublishReceipt:
        return BrowserPublishReceipt("browser", "https://mp.weixin.qq.com/s/browser")


class FakeOfficial:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome

    def publish(self, job: JobContext) -> PublishResult:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        assert isinstance(self.outcome, PublishResult)
        return self.outcome


def job(remote_id: str | None = None) -> JobContext:
    return JobContext(
        job_id="job",
        post_id="post",
        platform="wechat",
        status=JobStatus.RUNNING,
        attempts=1,
        max_attempts=3,
        title="title",
        body="body",
        content_type="text/html",
        image_path=Path("image.png"),
        image_usage="cover",
        scheduled_at=None,
        remote_id=remote_id,
    )


class SettingsAndRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = Repository(Path(self.temp.name) / "db.sqlite3")
        self.repository.initialize()
        self.secrets = MemorySecretStore()
        self.settings = SettingsService(self.repository, self.secrets)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_secret_is_not_stored_in_sqlite_settings(self) -> None:
        current = self.settings.configure_wechat(
            app_id="wx-app",
            app_secret="top-secret",
            browser_fallback_enabled=True,
        )
        self.assertTrue(current.official_configured)
        self.assertEqual(self.secrets.get("wechat-app-secret"), "top-secret")
        with self.repository.connect() as connection:
            values = " ".join(
                row[0] for row in connection.execute("SELECT value_json FROM settings")
            )
        self.assertNotIn("top-secret", values)

    def test_official_is_preferred_when_configured(self) -> None:
        self.settings.configure_wechat(
            app_id="wx-app", app_secret="secret", browser_fallback_enabled=True
        )
        official = FakeOfficial(PublishResult(JobStatus.PENDING_REMOTE, remote_id="publish"))
        router = WeChatRoutingAdapter(
            self.settings,
            lambda: official,  # type: ignore[arg-type]
            WeChatBrowserFallbackAdapter(FakeBrowserDriver()),
        )
        result = router.publish(job())
        self.assertEqual(result.remote_id, "publish")

    def test_permission_denial_falls_back_only_when_enabled(self) -> None:
        self.settings.configure_wechat(
            app_id="wx-app", app_secret="secret", browser_fallback_enabled=True
        )
        official = FakeOfficial(PermanentPublishError("denied", "wechat_48001"))
        router = WeChatRoutingAdapter(
            self.settings,
            lambda: official,  # type: ignore[arg-type]
            WeChatBrowserFallbackAdapter(FakeBrowserDriver()),
        )
        result = router.publish(job())
        self.assertEqual(result.result_url, "https://mp.weixin.qq.com/s/browser")

    def test_inflight_official_job_never_switches_to_browser(self) -> None:
        self.settings.configure_wechat(
            app_id="wx-app", app_secret="secret", browser_fallback_enabled=True
        )
        router = WeChatRoutingAdapter(
            self.settings,
            lambda: FakeOfficial(PermanentPublishError("denied", "wechat_48001")),  # type: ignore[arg-type]
            WeChatBrowserFallbackAdapter(FakeBrowserDriver()),
        )
        with self.assertRaises(PermanentPublishError):
            router.publish(job(remote_id="publish-id"))


if __name__ == "__main__":
    unittest.main()
