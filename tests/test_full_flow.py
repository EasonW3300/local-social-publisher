from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from social_publisher.api import create_app
from social_publisher.domain import JobStatus, Platform
from social_publisher.jobs import JobRunner, PublishResult
from social_publisher.storage import JobContext, Repository


class DeterministicAdapter:
    def __init__(self, platform: Platform, outcomes: list[PublishResult]) -> None:
        self.platform = platform
        self.outcomes = outcomes
        self.contexts: list[JobContext] = []

    def publish(self, job: JobContext) -> PublishResult:
        self.contexts.append(job)
        return self.outcomes.pop(0)


class FullFlowTests(unittest.TestCase):
    def test_multi_platform_submission_executes_and_persists_both_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wechat = DeterministicAdapter(
                Platform.WECHAT,
                [
                    PublishResult(JobStatus.PENDING_REMOTE, remote_id="publish-1"),
                    PublishResult(
                        JobStatus.SUCCEEDED,
                        remote_id="article-1",
                        result_url="https://mp.weixin.qq.com/s/full-flow",
                    ),
                ],
            )
            csdn = DeterministicAdapter(
                Platform.CSDN,
                [
                    PublishResult(
                        JobStatus.SUCCEEDED,
                        remote_id="draft-1",
                        result_url="https://editor.csdn.net/md/?articleId=draft-1",
                    )
                ],
            )
            repository_holder: dict[str, Repository] = {}

            def dispatch(job_ids: list[str]) -> None:
                runner = JobRunner(repository_holder["repository"], (wechat, csdn))
                for job_id in job_ids:
                    status = runner.run(job_id)
                    if status is JobStatus.PENDING_REMOTE:
                        runner.run(job_id)

            app = create_app(root, dispatch_jobs=dispatch)
            repository_holder["repository"] = app.state.repository
            with TestClient(app) as client:
                headers = {
                    "X-Local-Publisher-Token": client.get("/api/session").json()["token"]
                }
                form = {
                    "title": "双平台全流程",
                    "markdown": "# 正文\n\n这是双平台回归。",
                    "platforms": json.dumps(["wechat", "csdn"]),
                    "image_usage": json.dumps({"wechat": "cover", "csdn": "body"}),
                }
                preview = client.post(
                    "/api/previews",
                    data=form,
                    files={"image": ("cover.png", b"image-bytes", "image/png")},
                    headers=headers,
                )
                self.assertEqual(preview.status_code, 200)
                self.assertEqual(
                    {item["platform"] for item in preview.json()["items"]},
                    {"wechat", "csdn"},
                )

                submitted = client.post(
                    "/api/submissions",
                    data=form,
                    files={"image": ("cover.png", b"image-bytes", "image/png")},
                    headers=headers,
                )
                self.assertEqual(submitted.status_code, 201)
                post_id = submitted.json()["post_id"]
                bundle = client.get(f"/api/submissions/{post_id}").json()

            jobs = {job["platform"]: job for job in bundle["jobs"]}
            self.assertEqual(set(jobs), {"wechat", "csdn"})
            self.assertEqual({job["status"] for job in jobs.values()}, {"succeeded"})
            self.assertEqual(jobs["wechat"]["remote_id"], "article-1")
            self.assertEqual(
                jobs["wechat"]["result_url"], "https://mp.weixin.qq.com/s/full-flow"
            )
            self.assertEqual(jobs["csdn"]["remote_id"], "draft-1")
            self.assertEqual(
                jobs["csdn"]["result_url"],
                "https://editor.csdn.net/md/?articleId=draft-1",
            )
            self.assertEqual(len(wechat.contexts), 2)
            self.assertEqual(wechat.contexts[1].remote_id, "publish-1")
            self.assertEqual(wechat.contexts[0].content_type, "text/html")
            self.assertEqual(csdn.contexts[0].content_type, "text/markdown")
            self.assertIn("{{IMAGE_URL}}", csdn.contexts[0].body)


if __name__ == "__main__":
    unittest.main()
