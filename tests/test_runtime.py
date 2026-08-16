from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from social_publisher.runtime import PublisherRuntime


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


class RuntimeShutdownTests(unittest.TestCase):
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
