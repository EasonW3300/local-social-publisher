from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from social_publisher.runtime import PublisherRuntime
from social_publisher.secrets import MemorySecretStore


class _Scheduler:
    running = True

    def __init__(self) -> None:
        self.stopped = False

    def shutdown(self, wait: bool) -> None:
        self.stopped = not wait


class _Driver:
    def __init__(self) -> None:
        self.closed_on: str | None = None

    def close(self) -> None:
        self.closed_on = threading.current_thread().name

    def is_logged_in(self) -> bool:
        self.closed_on = threading.current_thread().name
        return True


class RuntimeShutdownTests(unittest.TestCase):
    def test_wechat_probe_explains_missing_credentials_without_network_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = PublisherRuntime(Path(directory), secrets=MemorySecretStore())
            try:
                ready, code, message = runtime.check_wechat_api()
            finally:
                runtime.close()

        self.assertFalse(ready)
        self.assertEqual(code, "wechat_not_configured")
        self.assertIn("AppID", message)

    def test_login_check_runs_on_the_publisher_thread(self) -> None:
        runtime = PublisherRuntime.__new__(PublisherRuntime)
        runtime.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="publisher")
        runtime.csdn_driver = _Driver()
        try:
            self.assertTrue(runtime.is_csdn_logged_in())
            self.assertTrue(runtime.csdn_driver.closed_on.startswith("publisher"))
        finally:
            runtime.executor.shutdown(wait=True)

    def test_browser_drivers_close_on_their_executor_thread(self) -> None:
        runtime = PublisherRuntime.__new__(PublisherRuntime)
        runtime.scheduler = _Scheduler()
        runtime.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="publisher")
        runtime.csdn_driver = _Driver()
        runtime.wechat_driver = _Driver()

        runtime.close()

        self.assertTrue(runtime.scheduler.stopped)
        self.assertTrue(runtime.csdn_driver.closed_on.startswith("publisher"))
        self.assertTrue(runtime.wechat_driver.closed_on.startswith("publisher"))


if __name__ == "__main__":
    unittest.main()
