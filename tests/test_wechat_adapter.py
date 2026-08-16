from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from social_publisher.adapters.wechat import WeChatConfig, WeChatOfficialAdapter
from social_publisher.domain import JobStatus
from social_publisher.jobs import PermanentPublishError
from social_publisher.storage import JobContext


class FakeSecrets:
    def get(self, reference: str) -> str:
        if reference != "wechat-secret":
            raise AssertionError(reference)
        return "secret-value"


class FakeTransport:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, object]] = []

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("json", url, payload))
        return self.responses.pop(0)

    def post_file(
        self, url: str, field: str, path: Path, data: dict[str, str] | None = None
    ) -> dict[str, Any]:
        self.calls.append(("file", url, (field, path, data)))
        return self.responses.pop(0)


def job(image: Path, *, remote_id: str | None = None, body: str = "<p>body</p>") -> JobContext:
    return JobContext(
        job_id="job-1",
        post_id="post-1",
        platform="wechat",
        status=JobStatus.RUNNING,
        attempts=1,
        max_attempts=3,
        title="A title",
        body=body,
        content_type="text/html",
        image_path=image,
        image_usage="cover",
        scheduled_at=None,
        remote_id=remote_id,
    )


class WeChatOfficialAdapterTests(unittest.TestCase):
    def test_credentials_check_only_requests_a_token(self) -> None:
        transport = FakeTransport([{"access_token": "token", "expires_in": 7200}])
        adapter = WeChatOfficialAdapter(
            WeChatConfig("appid", "wechat-secret"), FakeSecrets(), transport
        )

        adapter.check_credentials()

        self.assertEqual(len(transport.calls), 1)
        self.assertIn("/stable_token", transport.calls[0][1])

    def test_submits_material_draft_and_publish_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            image.write_bytes(b"image")
            transport = FakeTransport(
                [
                    {"access_token": "token", "expires_in": 7200},
                    {"media_id": "thumb"},
                    {"url": "https://mmbiz.qpic.cn/body.png"},
                    {"media_id": "draft"},
                    {"publish_id": "publish"},
                ]
            )
            adapter = WeChatOfficialAdapter(
                WeChatConfig("appid", "wechat-secret"),
                FakeSecrets(),
                transport,
                clock=lambda: 100.0,
            )

            result = adapter.publish(job(image, body='<img src="{{IMAGE_URL}}">'))

            self.assertEqual(result.status, JobStatus.PENDING_REMOTE)
            self.assertEqual(result.remote_id, "publish")
            draft_call = next(call for call in transport.calls if "/draft/add" in call[1])
            article = draft_call[2]["articles"][0]  # type: ignore[index]
            self.assertEqual(article["thumb_media_id"], "thumb")
            self.assertIn("https://mmbiz.qpic.cn/body.png", article["content"])

    def test_polling_success_returns_public_link_without_resubmitting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            image.write_bytes(b"image")
            transport = FakeTransport(
                [
                    {"access_token": "token", "expires_in": 7200},
                    {
                        "publish_status": 0,
                        "article_id": "article",
                        "article_detail": {
                            "item": [{"article_url": "https://mp.weixin.qq.com/s/example"}]
                        },
                    },
                ]
            )
            adapter = WeChatOfficialAdapter(
                WeChatConfig("appid", "wechat-secret"), FakeSecrets(), transport
            )

            result = adapter.publish(job(image, remote_id="publish"))

            self.assertEqual(result.status, JobStatus.SUCCEEDED)
            self.assertEqual(result.result_url, "https://mp.weixin.qq.com/s/example")
            self.assertEqual(len(transport.calls), 2)
            self.assertIn("/freepublish/get", transport.calls[-1][1])

    def test_pending_publish_is_polled_again_later(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            image.write_bytes(b"image")
            transport = FakeTransport(
                [
                    {"access_token": "token"},
                    {"publish_status": 1},
                ]
            )
            adapter = WeChatOfficialAdapter(
                WeChatConfig("appid", "wechat-secret"), FakeSecrets(), transport
            )
            result = adapter.publish(job(image, remote_id="publish"))
            self.assertEqual(result.status, JobStatus.PENDING_REMOTE)

    def test_review_rejection_is_permanent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            image.write_bytes(b"image")
            transport = FakeTransport([{"access_token": "token"}, {"publish_status": 4}])
            adapter = WeChatOfficialAdapter(
                WeChatConfig("appid", "wechat-secret"), FakeSecrets(), transport
            )
            with self.assertRaisesRegex(PermanentPublishError, "review failed"):
                adapter.publish(job(image, remote_id="publish"))

    def test_token_is_cached_between_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            image.write_bytes(b"image")
            transport = FakeTransport(
                [
                    {"access_token": "token", "expires_in": 7200},
                    {"publish_status": 1},
                    {"publish_status": 1},
                ]
            )
            adapter = WeChatOfficialAdapter(
                WeChatConfig("appid", "wechat-secret"),
                FakeSecrets(),
                transport,
                clock=lambda: 100.0,
            )
            adapter.publish(job(image, remote_id="first"))
            adapter.publish(job(image, remote_id="second"))
            token_calls = [call for call in transport.calls if "stable_token" in call[1]]
            self.assertEqual(len(token_calls), 1)


if __name__ == "__main__":
    unittest.main()
