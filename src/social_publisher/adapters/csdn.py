from __future__ import annotations

import re
from pathlib import Path

from ..domain import JobStatus, Platform
from ..jobs import PermanentPublishError, PublishResult
from ..rendering import IMAGE_URL_PLACEHOLDER
from ..storage import JobContext
from .browser import (
    BrowserPublishReceipt,
    BrowserSubmissionUnknown,
    CsdnBrowserDriver,
    LoginRequired,
    PersistentPlaywrightDriver,
    UserActionRequired,
)


class CsdnAdapter:
    platform = Platform.CSDN

    def __init__(self, driver: CsdnBrowserDriver) -> None:
        self.driver = driver

    def publish(self, job: JobContext) -> PublishResult:
        try:
            receipt = self.driver.create_draft(job)
        except (LoginRequired, UserActionRequired) as error:
            return PublishResult(JobStatus.WAITING_USER, message=str(error))
        except BrowserSubmissionUnknown as error:
            return PublishResult(JobStatus.UNKNOWN, message=str(error))
        except RuntimeError as error:
            raise PermanentPublishError(str(error), "csdn_browser") from error
        return PublishResult(
            JobStatus.SUCCEEDED,
            remote_id=receipt.remote_id,
            result_url=receipt.result_url,
            message="CSDN draft created and opened for review",
        )


class CsdnPlaywrightDriver(PersistentPlaywrightDriver):
    EDITOR_URL = "https://editor.csdn.net/md/"

    def __init__(self, profile_path: Path) -> None:
        super().__init__(profile_path)

    def create_draft(self, job: JobContext) -> BrowserPublishReceipt:
        page = self._page(self.EDITOR_URL)
        if "passport.csdn.net" in page.url or "login" in page.url.lower():
            raise LoginRequired("请在已打开的 CSDN 专用浏览器中登录，然后重试")

        self._fill_first(
            page,
            (
                "textarea.article-bar__title",
                "input.article-bar__title",
                "textarea[placeholder*='文章标题']",
                "input[placeholder*='文章标题']",
            ),
            job.title,
        )

        body = job.body.replace(f"![{job.title}]({IMAGE_URL_PLACEHOLDER})\n\n", "")
        self._fill_first(
            page,
            (
                ".cledit-section textarea",
                "textarea.editor__inner",
                "textarea[placeholder*='Markdown']",
                "textarea",
            ),
            body,
        )

        if IMAGE_URL_PLACEHOLDER in job.body:
            image_input = page.locator("input[type='file'][accept*='image']")
            if not image_input.count():
                raise UserActionRequired("CSDN 图片上传控件发生变化，请人工上传图片并保存草稿")
            image_input.first.set_input_files(str(job.image_path))
            page.wait_for_timeout(1500)

        self._click_first(
            page,
            (
                "button:has-text('保存草稿')",
                "button:has-text('保存')",
                "text=保存草稿",
            ),
        )
        page.wait_for_timeout(1200)
        if "editor.csdn.net" not in page.url:
            raise BrowserSubmissionUnknown("CSDN 已点击保存，但无法确认草稿编辑地址")
        match = re.search(r"(?:articleId=|/)(\d{4,})(?:\D|$)", page.url)
        return BrowserPublishReceipt(
            remote_id=match.group(1) if match else None,
            result_url=page.url,
        )
