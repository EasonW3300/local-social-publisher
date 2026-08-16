from __future__ import annotations

import base64
import mimetypes
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

    def open_login(self) -> None:
        self._page(self.EDITOR_URL)

    def is_logged_in(self) -> bool:
        page = self._page(self.EDITOR_URL)
        return "passport.csdn.net" not in page.url and "login" not in page.url.lower()

    @staticmethod
    def _dismiss_informational_modals(page) -> None:
        for selector in (
            ".modal__close-button[aria-label='关闭']",
            ".el-dialog__headerbtn",
            "button:has-text('我知道了')",
        ):
            locator = page.locator(selector)
            for index in range(locator.count()):
                candidate = locator.nth(index)
                if candidate.is_visible():
                    candidate.click()
                    page.wait_for_timeout(250)

    @staticmethod
    def _drop_image(page, image_path: Path) -> None:
        editor = page.locator("pre.editor__inner[contenteditable='true']")
        try:
            payload = {
                "data": base64.b64encode(image_path.read_bytes()).decode("ascii"),
                "name": image_path.name,
                "type": mimetypes.guess_type(image_path.name)[0] or "application/octet-stream",
            }
            editor.evaluate(
                """(element, payload) => {
                    const binary = atob(payload.data);
                    const bytes = new Uint8Array(binary.length);
                    for (let index = 0; index < binary.length; index += 1) {
                        bytes[index] = binary.charCodeAt(index);
                    }
                    const file = new File([bytes], payload.name, {type: payload.type});
                    const transfer = new DataTransfer();
                    transfer.items.add(file);
                    element.focus();
                    for (const eventName of ['dragenter', 'dragover', 'drop']) {
                        element.dispatchEvent(new DragEvent(eventName, {
                            bubbles: true,
                            cancelable: true,
                            dataTransfer: transfer,
                        }));
                    }
                }""",
                payload,
            )
            page.wait_for_timeout(7_000)
            content = editor.inner_text()
        except Exception as error:
            raise UserActionRequired(
                "CSDN 图片拖拽上传失败，请人工上传图片后继续"
            ) from error
        if not re.search(r"https://(?:i-blog|img-blog)\.csdnimg\.cn/", content):
            raise UserActionRequired("CSDN 未返回可验证的图片链接，请人工检查上传状态")

    def create_draft(self, job: JobContext) -> BrowserPublishReceipt:
        page = self._page(self.EDITOR_URL)
        if "passport.csdn.net" in page.url or "login" in page.url.lower():
            raise LoginRequired("请在已打开的 CSDN 专用浏览器中登录，然后重试")

        page.wait_for_selector(
            ".article-bar__title-display", state="visible", timeout=15_000
        )
        self._dismiss_informational_modals(page)
        page.locator(".article-bar__title-display").click()

        self._fill_first(
            page,
            (
                "input.article-bar__title--input",
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
                "pre.editor__inner[contenteditable='true']",
                ".cledit-section textarea",
                "textarea.editor__inner",
                "textarea[placeholder*='Markdown']",
                "textarea",
            ),
            body,
        )

        if IMAGE_URL_PLACEHOLDER in job.body:
            self._drop_image(page, job.image_path)

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
