from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..domain import JobStatus, Platform
from ..jobs import PermanentPublishError, PublishResult, TransientPublishError
from ..rendering import IMAGE_URL_PLACEHOLDER
from ..storage import JobContext

_API_ROOT = "https://api.weixin.qq.com/cgi-bin"
_TRANSIENT_CODES = {-1, 45009}


class SecretProvider(Protocol):
    def get(self, reference: str) -> str: ...


class WeChatTransport(Protocol):
    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def post_file(
        self, url: str, field: str, path: Path, data: dict[str, str] | None = None
    ) -> dict[str, Any]: ...


class HttpxWeChatTransport:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(url, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise TransientPublishError(str(error), "wechat_network") from error
        except (httpx.HTTPStatusError, ValueError) as error:
            raise PermanentPublishError(str(error), "wechat_http") from error

    def post_file(
        self, url: str, field: str, path: Path, data: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            with path.open("rb") as handle:
                response = httpx.post(
                    url,
                    files={field: (path.name, handle)},
                    data=data,
                    timeout=self.timeout_seconds,
                )
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise TransientPublishError(str(error), "wechat_network") from error
        except (OSError, httpx.HTTPStatusError, ValueError) as error:
            raise PermanentPublishError(str(error), "wechat_upload") from error


@dataclass(frozen=True, slots=True)
class WeChatConfig:
    app_id: str
    app_secret_reference: str


@dataclass(slots=True)
class _CachedToken:
    value: str
    expires_at: float


class WeChatOfficialAdapter:
    platform = Platform.WECHAT

    def __init__(
        self,
        config: WeChatConfig,
        secrets: SecretProvider,
        transport: WeChatTransport | None = None,
        clock: callable = time.time,
    ) -> None:
        self.config = config
        self.secrets = secrets
        self.transport = transport or HttpxWeChatTransport()
        self.clock = clock
        self._token: _CachedToken | None = None

    def publish(self, job: JobContext) -> PublishResult:
        token = self._access_token()
        if job.remote_id:
            return self._poll_publish(token, job.remote_id)

        thumb_media_id = self._upload_cover(token, job.image_path)
        content = job.body
        if IMAGE_URL_PLACEHOLDER in content:
            body_image_url = self._upload_body_image(token, job.image_path)
            content = content.replace(IMAGE_URL_PLACEHOLDER, body_image_url)

        draft_payload = {
            "articles": [
                {
                    "article_type": "news",
                    "title": job.title,
                    "content": content,
                    "thumb_media_id": thumb_media_id,
                    "show_cover_pic": 0 if job.image_usage == "body" else 1,
                }
            ]
        }
        draft = self._checked(
            self.transport.post_json(f"{_API_ROOT}/draft/add?access_token={token}", draft_payload)
        )
        draft_media_id = _required_string(draft, "media_id")
        submitted = self._checked(
            self.transport.post_json(
                f"{_API_ROOT}/freepublish/submit?access_token={token}",
                {"media_id": draft_media_id},
            )
        )
        publish_id = _required_string(submitted, "publish_id")
        return PublishResult(
            JobStatus.PENDING_REMOTE,
            remote_id=publish_id,
            message="WeChat accepted the asynchronous publish job",
        )

    def _access_token(self) -> str:
        now = float(self.clock())
        if self._token and self._token.expires_at > now + 300:
            return self._token.value
        secret = self.secrets.get(self.config.app_secret_reference)
        response = self._checked(
            self.transport.post_json(
                "https://api.weixin.qq.com/cgi-bin/stable_token",
                {
                    "grant_type": "client_credential",
                    "appid": self.config.app_id,
                    "secret": secret,
                    "force_refresh": False,
                },
            )
        )
        token = _required_string(response, "access_token")
        expires_in = int(response.get("expires_in", 7200))
        self._token = _CachedToken(token, now + expires_in)
        return token

    def _upload_cover(self, token: str, image_path: Path) -> str:
        response = self._checked(
            self.transport.post_file(
                f"{_API_ROOT}/material/add_material?access_token={token}&type=image",
                "media",
                image_path,
            )
        )
        return _required_string(response, "media_id")

    def _upload_body_image(self, token: str, image_path: Path) -> str:
        response = self._checked(
            self.transport.post_file(
                f"{_API_ROOT}/media/uploadimg?access_token={token}", "media", image_path
            )
        )
        return _required_string(response, "url")

    def _poll_publish(self, token: str, publish_id: str) -> PublishResult:
        response = self._checked(
            self.transport.post_json(
                f"{_API_ROOT}/freepublish/get?access_token={token}",
                {"publish_id": publish_id},
            )
        )
        status = int(response.get("publish_status", -1))
        if status == 1:
            return PublishResult(
                JobStatus.PENDING_REMOTE,
                remote_id=publish_id,
                message="WeChat publication is still processing",
            )
        if status == 0:
            article_id = str(response.get("article_id") or publish_id)
            article_url = _extract_article_url(response)
            if not article_url:
                raise TransientPublishError(
                    "WeChat reported success without a public article URL",
                    "wechat_link_missing",
                )
            return PublishResult(
                JobStatus.SUCCEEDED,
                remote_id=article_id,
                result_url=article_url,
            )
        if status in (2, 4):
            raise PermanentPublishError(
                f"WeChat content review failed with status {status}",
                "wechat_review_rejected",
            )
        raise PermanentPublishError(
            f"WeChat publish failed with status {status}", "wechat_publish_failed"
        )

    @staticmethod
    def _checked(response: dict[str, Any]) -> dict[str, Any]:
        code = int(response.get("errcode", 0))
        if code == 0:
            return response
        message = str(response.get("errmsg", "WeChat API error"))
        if code in _TRANSIENT_CODES:
            raise TransientPublishError(message, f"wechat_{code}")
        raise PermanentPublishError(message, f"wechat_{code}")


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise PermanentPublishError(
            f"WeChat response did not include {key}", "wechat_invalid_response"
        )
    return value


def _extract_article_url(payload: dict[str, Any]) -> str | None:
    detail = payload.get("article_detail")
    if not isinstance(detail, dict):
        return None
    items = detail.get("item") or detail.get("item_list")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    value = first.get("article_url") or first.get("content_url")
    return value if isinstance(value, str) and value else None
