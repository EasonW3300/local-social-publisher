from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from .adapters.csdn import CsdnAdapter, CsdnPlaywrightDriver
from .adapters.wechat import WeChatConfig, WeChatOfficialAdapter
from .adapters.wechat_browser import WeChatBrowserFallbackAdapter, WeChatPlaywrightDriver
from .jobs import JobRunner, PermanentPublishError, SchedulerCore, TransientPublishError
from .routing import WeChatRoutingAdapter
from .secrets import KeyringSecretStore, SecretStore
from .settings import WECHAT_SECRET_REFERENCE, SettingsService
from .storage import Repository


class PublisherRuntime:
    def __init__(self, data_dir: Path, secrets: SecretStore | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.repository = Repository(self.data_dir / "publisher.sqlite3")
        self.repository.initialize()
        self.secrets = secrets or KeyringSecretStore()
        self.settings = SettingsService(self.repository, self.secrets)
        profiles = self.data_dir / "browser-profiles"
        self.csdn_driver = CsdnPlaywrightDriver(profiles / "csdn")
        self.wechat_driver = WeChatPlaywrightDriver(profiles / "wechat")
        csdn = CsdnAdapter(self.csdn_driver)
        browser_wechat = WeChatBrowserFallbackAdapter(self.wechat_driver)

        def official_factory() -> WeChatOfficialAdapter:
            current = self.settings.wechat()
            return WeChatOfficialAdapter(
                WeChatConfig(current.app_id, WECHAT_SECRET_REFERENCE), self.secrets
            )

        wechat = WeChatRoutingAdapter(
            self.settings,
            official_factory,
            browser_wechat,
        )
        self.runner = JobRunner(self.repository, (wechat, csdn))
        self.scheduler_core = SchedulerCore(self.repository, self.runner)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="publisher")
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.scheduler.add_job(
            self._tick,
            "interval",
            seconds=10,
            id="publish-queue",
            max_instances=1,
            coalesce=True,
        )

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            self.executor.submit(self.scheduler_core.recover_and_run)

    def dispatch(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.executor.submit(self.runner.run, job_id)

    def dispatch_future(self, job_id: str) -> Future:
        return self.executor.submit(self.runner.run, job_id)

    def open_csdn_login(self) -> None:
        self.executor.submit(self.csdn_driver.open_login)

    def open_wechat_login(self) -> None:
        self.executor.submit(self.wechat_driver.open_login)

    def is_csdn_logged_in(self) -> bool:
        return bool(self.executor.submit(self.csdn_driver.is_logged_in).result(timeout=30))

    def check_wechat_api(self) -> tuple[bool, str | None, str]:
        current = self.settings.wechat()
        if not current.official_configured:
            return False, "wechat_not_configured", "请先保存微信公众号 AppID 和 AppSecret"
        adapter = WeChatOfficialAdapter(
            WeChatConfig(current.app_id, WECHAT_SECRET_REFERENCE), self.secrets
        )
        try:
            adapter.check_credentials()
        except (PermanentPublishError, TransientPublishError) as error:
            return False, error.code, str(error)
        except Exception as error:
            return False, "wechat_probe_failed", str(error)
        return True, None, "微信公众号官方 API 凭证与网络检查通过"

    def _tick(self) -> None:
        self.executor.submit(self.scheduler_core.recover_and_run)

    def close(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        close_future = self.executor.submit(self._close_browser_drivers)
        try:
            close_future.result()
        finally:
            self.executor.shutdown(wait=True, cancel_futures=True)

    def _close_browser_drivers(self) -> None:
        try:
            self.csdn_driver.close()
        finally:
            self.wechat_driver.close()
