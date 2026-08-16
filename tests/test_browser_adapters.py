from __future__ import annotations

import unittest
from pathlib import Path

from social_publisher.adapters.browser import (
    BrowserPublishReceipt,
    BrowserSubmissionUnknown,
    LoginRequired,
    UserActionRequired,
)
from social_publisher.adapters.csdn import CsdnAdapter
from social_publisher.adapters.wechat_browser import WeChatBrowserFallbackAdapter
from social_publisher.domain import JobStatus
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
            FakeWeChatDriver(
                BrowserPublishReceipt("abc", "https://mp.weixin.qq.com/s/example")
            )
        )
        result = adapter.publish(job("wechat"))
        self.assertEqual(result.status, JobStatus.SUCCEEDED)
        self.assertEqual(result.result_url, "https://mp.weixin.qq.com/s/example")


if __name__ == "__main__":
    unittest.main()
