from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from social_publisher.adapters.browser import (
    BrowserPublishReceipt,
    BrowserSubmissionUnknown,
    LoginRequired,
    PersistentPlaywrightDriver,
    UserActionRequired,
)
from social_publisher.adapters.csdn import CsdnAdapter, CsdnPlaywrightDriver
from social_publisher.adapters.wechat_browser import WeChatBrowserFallbackAdapter
from social_publisher.domain import JobStatus
from social_publisher.rendering import IMAGE_URL_PLACEHOLDER
from social_publisher.storage import JobContext


class FakeCsdnDriver:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome

    def create_draft(self, job: JobContext) -> BrowserPublishReceipt:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        assert isinstance(self.outcome, BrowserPublishReceipt)
        return self.outcome


class FakeWeChatDriver:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome

    def publish_article(self, job: JobContext) -> BrowserPublishReceipt:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        assert isinstance(self.outcome, BrowserPublishReceipt)
        return self.outcome


def job(platform: str) -> JobContext:
    return JobContext(
        job_id="job",
        post_id="post",
        platform=platform,
        status=JobStatus.RUNNING,
        attempts=1,
        max_attempts=3,
        title="A title",
        body="body",
        content_type="text/markdown",
        image_path=Path("image.png"),
        image_usage="body",
        scheduled_at=None,
        remote_id=None,
    )


class BrowserAdapterTests(unittest.TestCase):
    def test_browser_close_is_idempotent_after_visible_window_disconnects(self) -> None:
        driver = PersistentPlaywrightDriver(Path("profile"))
        driver._context = MagicMock()
        driver._context.close.side_effect = RuntimeError("connection closed")
        driver._playwright = MagicMock()
        driver._playwright.stop.side_effect = RuntimeError("already stopped")

        driver.close()

        self.assertIsNone(driver._context)
        self.assertIsNone(driver._playwright)

    def test_csdn_login_status_uses_the_resulting_editor_url(self) -> None:
        driver = CsdnPlaywrightDriver(Path("profile"))
        driver._page = lambda _url: SimpleNamespace(url="https://editor.csdn.net/md/")
        self.assertTrue(driver.is_logged_in())
        driver._page = lambda _url: SimpleNamespace(
            url="https://passport.csdn.net/login?code=required"
        )
        self.assertFalse(driver.is_logged_in())

    def test_csdn_driver_uses_current_title_editor_and_file_chooser(self) -> None:
        title_locator = MagicMock()
        title_locator.count.return_value = 1
        title_locator.first = title_locator
        title_locator.is_visible.return_value = True
        image_locator = MagicMock()
        image_locator.count.return_value = 1
        image_locator.first = image_locator
        image_locator.is_visible.return_value = True
        chooser = MagicMock()
        chooser_context = MagicMock()
        chooser_context.__enter__.return_value = chooser_context
        chooser_context.value = chooser
        page = MagicMock()
        page.url = "https://editor.csdn.net/md/?articleId=123456"
        page.locator.side_effect = lambda selector: (
            title_locator if selector == ".article-bar__title-display" else image_locator
        )
        page.expect_file_chooser.return_value = chooser_context

        driver = CsdnPlaywrightDriver(Path("profile"))
        driver._page = MagicMock(return_value=page)
        driver._fill_first = MagicMock()
        driver._click_first = MagicMock()
        upload_job = replace(
            job("csdn"),
            body=f"![A title]({IMAGE_URL_PLACEHOLDER})\n\nbody",
        )

        receipt = driver.create_draft(upload_job)

        title_locator.click.assert_called_once_with()
        first_fill_selectors = driver._fill_first.call_args_list[0].args[1]
        body_fill_selectors = driver._fill_first.call_args_list[1].args[1]
        self.assertEqual(first_fill_selectors[0], "input.article-bar__title--input")
        self.assertEqual(body_fill_selectors[0], "pre.editor__inner[contenteditable='true']")
        chooser.set_files.assert_called_once_with("image.png")
        self.assertEqual(receipt.remote_id, "123456")

    def test_csdn_draft_is_success_for_the_csdn_delivery_contract(self) -> None:
        adapter = CsdnAdapter(
            FakeCsdnDriver(BrowserPublishReceipt("123", "https://editor.csdn.net/md/123"))
        )
        result = adapter.publish(job("csdn"))
        self.assertEqual(result.status, JobStatus.SUCCEEDED)
        self.assertEqual(result.result_url, "https://editor.csdn.net/md/123")

    def test_login_requirement_waits_for_user(self) -> None:
        adapter = CsdnAdapter(FakeCsdnDriver(LoginRequired("login")))
        result = adapter.publish(job("csdn"))
        self.assertEqual(result.status, JobStatus.WAITING_USER)

    def test_ambiguous_csdn_save_is_terminal_unknown(self) -> None:
        adapter = CsdnAdapter(FakeCsdnDriver(BrowserSubmissionUnknown("unknown")))
        result = adapter.publish(job("csdn"))
        self.assertEqual(result.status, JobStatus.UNKNOWN)

    def test_wechat_verification_waits_for_user(self) -> None:
        adapter = WeChatBrowserFallbackAdapter(
            FakeWeChatDriver(UserActionRequired("scan to confirm"))
        )
        result = adapter.publish(job("wechat"))
        self.assertEqual(result.status, JobStatus.WAITING_USER)

    def test_wechat_browser_success_requires_verified_public_link(self) -> None:
        adapter = WeChatBrowserFallbackAdapter(
            FakeWeChatDriver(BrowserPublishReceipt("abc", "https://mp.weixin.qq.com/s/example"))
        )
        result = adapter.publish(job("wechat"))
        self.assertEqual(result.status, JobStatus.SUCCEEDED)
        self.assertEqual(result.result_url, "https://mp.weixin.qq.com/s/example")


if __name__ == "__main__":
    unittest.main()
