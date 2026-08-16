from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..storage import JobContext


class LoginRequired(RuntimeError):
    """A visible dedicated browser is waiting for the user to sign in."""


class UserActionRequired(RuntimeError):
    """A platform verification or confirmation requires a human action."""


class BrowserSubmissionUnknown(RuntimeError):
    """The submit action happened but the remote result cannot be proven."""


@dataclass(frozen=True, slots=True)
class BrowserPublishReceipt:
    remote_id: str | None
    result_url: str


class CsdnBrowserDriver(Protocol):
    def create_draft(self, job: JobContext) -> BrowserPublishReceipt: ...


class WeChatBrowserDriver(Protocol):
    def publish_article(self, job: JobContext) -> BrowserPublishReceipt: ...


class PersistentPlaywrightDriver:
    """Own one visible Chromium profile for a single platform account.

    Playwright is imported lazily so the core and unit tests do not require a
    browser installation. Packaged builds bundle a compatible Chromium.
    """

    def __init__(self, profile_path: Path) -> None:
        self.profile_path = Path(profile_path)
        self._playwright = None
        self._context = None

    def _page(self, start_url: str):
        if self._context is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as error:
                raise RuntimeError("Playwright is not installed") from error
            self.profile_path.mkdir(parents=True, exist_ok=True)
            self._playwright = sync_playwright().start()
            options = {
                "headless": False,
                "viewport": {"width": 1440, "height": 1000},
            }
            channel = os.environ.get("LOCAL_SOCIAL_PUBLISHER_BROWSER_CHANNEL", "chrome")
            try:
                self._context = self._playwright.chromium.launch_persistent_context(
                    str(self.profile_path), channel=channel, **options
                )
            except Exception:
                self._context = self._playwright.chromium.launch_persistent_context(
                    str(self.profile_path), **options
                )
        page = self._context.pages[0] if self._context.pages else self._context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")
        page.bring_to_front()
        return page

    @staticmethod
    def _first(page, selectors: tuple[str, ...]):
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() and locator.first.is_visible():
                return locator.first
        raise RuntimeError(f"platform editor selector not found: {selectors}")

    @classmethod
    def _fill_first(cls, page, selectors: tuple[str, ...], value: str) -> None:
        locator = cls._first(page, selectors)
        locator.fill(value)

    @classmethod
    def _click_first(cls, page, selectors: tuple[str, ...]) -> None:
        cls._first(page, selectors).click()

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
