from __future__ import annotations

import re
from pathlib import Path

from ..domain import JobStatus, Platform
from ..jobs import PermanentPublishError, PublishResult
from ..storage import JobContext
from .browser import (
    BrowserPublishReceipt,
    BrowserSubmissionUnknown,
    LoginRequired,
    PersistentPlaywrightDriver,
    UserActionRequired,
    WeChatBrowserDriver,
)


class WeChatBrowserFallbackAdapter:
    platform = Platform.WECHAT

    def __init__(self, driver: WeChatBrowserDriver) -> None:
        self.driver = driver

    def publish(self, job: JobContext) -> PublishResult:
        try:
            receipt = self.driver.publish_article(job)
        except (LoginRequired, UserActionRequired) as error:
            return PublishResult(JobStatus.WAITING_USER, message=str(error))
        except BrowserSubmissionUnknown as error:
            return PublishResult(JobStatus.UNKNOWN, message=str(error))
        except RuntimeError as error:
            raise PermanentPublishError(str(error), "wechat_browser") from error
        return PublishResult(
            JobStatus.SUCCEEDED,
            remote_id=receipt.remote_id,
            result_url=receipt.result_url,
            message="WeChat article published through the explicit browser fallback",
        )


class WeChatPlaywrightDriver(PersistentPlaywrightDriver):
    HOME_URL = "https://mp.weixin.qq.com/"

    def __init__(self, profile_path: Path) -> None:
        super().__init__(profile_path)

    def publish_article(self, job: JobContext) -> BrowserPublishReceipt:
        page = self._page(self.HOME_URL)
        if page.locator("text=扫码登录").count() or "login" in page.url.lower():
            raise LoginRequired("请在已打开的微信公众号专用浏览器中扫码登录，然后重试")

        self._click_first(page, ("text=草稿箱", "a:has-text('草稿箱')"))
        page.wait_for_timeout(500)
        self._click_first(
            page,
            (
                "text=新的创作",
                "button:has-text('新的创作')",
                "text=写新图文",
            ),
        )
        page.wait_for_timeout(800)

        self._fill_first(
            page,
            (
                "input[placeholder*='标题']",
                "textarea[placeholder*='标题']",
                "#title",
            ),
            job.title,
        )
        editor = self._first(
            page,
            (
                "[contenteditable='true'][data-placeholder*='正文']",
                ".ProseMirror[contenteditable='true']",
                "[contenteditable='true']",
            ),
        )
        editor.evaluate(
            """(element, body) => {
                element.innerHTML = body;
                element.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));
            }""",
            job.body,
        )

        cover_input = page.locator("input[type='file'][accept*='image']")
        if cover_input.count():
            cover_input.first.set_input_files(str(job.image_path))
            page.wait_for_timeout(1200)
        else:
            raise UserActionRequired("微信封面上传控件发生变化，请人工设置封面后继续")

        self._click_first(
            page,
            (
                "button:has-text('发表')",
                "button:has-text('发布')",
                "text=发表",
            ),
        )
        page.wait_for_timeout(1200)
        if page.locator("text=扫码确认").count() or page.locator("text=管理员确认").count():
            raise UserActionRequired("微信正在等待管理员扫码或确认")

        public_links = page.locator("a[href*='mp.weixin.qq.com/s/']")
        if not public_links.count():
            raise BrowserSubmissionUnknown("微信已点击发表，但尚未找到可验证的公开链接")
        url = public_links.first.get_attribute("href")
        if not url:
            raise BrowserSubmissionUnknown("微信公开链接为空")
        match = re.search(r"/s/([^?&#]+)", url)
        return BrowserPublishReceipt(remote_id=match.group(1) if match else None, result_url=url)

