from __future__ import annotations

from collections.abc import Callable

from .adapters.wechat import WeChatOfficialAdapter
from .adapters.wechat_browser import WeChatBrowserFallbackAdapter
from .domain import Platform
from .jobs import PermanentPublishError, PlatformAdapter, PublishResult
from .settings import SettingsService
from .storage import JobContext


class WeChatRoutingAdapter:
    """Prefer official APIs and fall back only for confirmed permission denial."""

    platform = Platform.WECHAT

    def __init__(
        self,
        settings: SettingsService,
        official_factory: Callable[[], WeChatOfficialAdapter],
        browser_adapter: WeChatBrowserFallbackAdapter,
    ) -> None:
        self.settings = settings
        self.official_factory = official_factory
        self.browser_adapter = browser_adapter
        self._official: WeChatOfficialAdapter | None = None
        self._official_app_id = ""

    def publish(self, job: JobContext) -> PublishResult:
        config = self.settings.wechat()
        if job.remote_id or config.official_configured:
            official = self._official_adapter(config.app_id)
            try:
                return official.publish(job)
            except PermanentPublishError as error:
                permission_denied = error.code in {"wechat_48001", "wechat_40164"}
                if not (
                    permission_denied and config.browser_fallback_enabled and not job.remote_id
                ):
                    raise
        if config.browser_fallback_enabled:
            return self.browser_adapter.publish(job)
        raise PermanentPublishError(
            "WeChat official credentials are not configured and browser fallback is disabled",
            "wechat_not_configured",
        )

    def _official_adapter(self, app_id: str) -> WeChatOfficialAdapter:
        if self._official is None or self._official_app_id != app_id:
            self._official = self.official_factory()
            self._official_app_id = app_id
        return self._official


def adapters_by_platform(adapters: tuple[PlatformAdapter, ...]) -> dict[Platform, PlatformAdapter]:
    return {adapter.platform: adapter for adapter in adapters}
