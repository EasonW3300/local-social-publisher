from __future__ import annotations

from dataclasses import dataclass

from .secrets import SecretStore
from .storage import Repository

WECHAT_SECRET_REFERENCE = "wechat-app-secret"


@dataclass(frozen=True, slots=True)
class WeChatSettings:
    app_id: str
    secret_configured: bool
    browser_fallback_enabled: bool

    @property
    def official_configured(self) -> bool:
        return bool(self.app_id and self.secret_configured)


class SettingsService:
    def __init__(self, repository: Repository, secrets: SecretStore) -> None:
        self.repository = repository
        self.secrets = secrets

    def wechat(self) -> WeChatSettings:
        return WeChatSettings(
            app_id=str(self.repository.get_setting("wechat.app_id", "")),
            secret_configured=self.secrets.exists(WECHAT_SECRET_REFERENCE),
            browser_fallback_enabled=bool(
                self.repository.get_setting("wechat.browser_fallback_enabled", False)
            ),
        )

    def configure_wechat(
        self,
        *,
        app_id: str,
        app_secret: str | None,
        browser_fallback_enabled: bool,
    ) -> WeChatSettings:
        self.repository.set_setting("wechat.app_id", app_id.strip())
        self.repository.set_setting("wechat.browser_fallback_enabled", browser_fallback_enabled)
        if app_secret:
            self.secrets.set(WECHAT_SECRET_REFERENCE, app_secret)
        return self.wechat()
