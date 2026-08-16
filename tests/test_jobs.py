from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from social_publisher.assets import AssetStore
from social_publisher.domain import AssetUsage, JobStatus, Platform, PostDraft
from social_publisher.jobs import (
    JobRunner,
    JobStateMachine,
    PublishResult,
    SchedulerCore,
    TransientPublishError,
)
from social_publisher.storage import JobContext, Repository
from social_publisher.submissions import SubmissionService


class FakeAdapter:
    platform = Platform.WECHAT

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def publish(self, job: JobContext) -> PublishResult:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, PublishResult)
        return outcome


class JobStateMachineTests(unittest.TestCase):
    def test_allows_expected_publish_path(self) -> None:
        JobStateMachine.ensure_allowed(JobStatus.READY, JobStatus.RUNNING)
        JobStateMachine.ensure_allowed(JobStatus.RUNNING, JobStatus.SUCCEEDED)

    def test_unknown_is_terminal(self) -> None:
        with self.assertRaisesRegex(ValueError, "illegal"):
            JobStateMachine.ensure_allowed(JobStatus.UNKNOWN, JobStatus.READY)


class JobRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        image = self.root / "image.png"
        image.write_bytes(b"image")
        self.repository = Repository(self.root / "publisher.sqlite3")
        self.repository.initialize()
        service = SubmissionService(self.repository, AssetStore(self.root / "assets"))
        draft = PostDraft(
            title="A publishable title",
            markdown="A publishable body",
            image_path=image,
            platforms=(Platform.WECHAT,),
            image_usage={Platform.WECHAT: AssetUsage.COVER},
        )
        self.created = service.submit(draft)
        self.job_id = self.created.job_ids[Platform.WECHAT.value]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def status(self) -> JobStatus:
        context = self.repository.get_job_context(self.job_id)
        assert context is not None
        return context.status

    def test_success_saves_public_link(self) -> None:
        adapter = FakeAdapter(
            [PublishResult(JobStatus.SUCCEEDED, remote_id="article-1", result_url="https://x")]
        )
        runner = JobRunner(self.repository, (adapter,))

        status = runner.run(self.job_id)

        self.assertEqual(status, JobStatus.SUCCEEDED)
        bundle = self.repository.get_post(self.created.post_id)
        assert bundle is not None
        self.assertEqual(bundle["jobs"][0]["result_url"], "https://x")  # type: ignore[index]

    def test_transient_error_schedules_retry(self) -> None:
        adapter = FakeAdapter([TransientPublishError("timeout")])
        runner = JobRunner(self.repository, (adapter,))
        now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

        status = runner.run(self.job_id, now)

        self.assertEqual(status, JobStatus.SCHEDULED)
        context = self.repository.get_job_context(self.job_id)
        assert context is not None
        self.assertEqual(context.attempts, 1)
        self.assertEqual(context.scheduled_at, now + timedelta(seconds=5))

    def test_unknown_result_is_not_runnable_again(self) -> None:
        adapter = FakeAdapter([PublishResult(JobStatus.UNKNOWN, message="button clicked")])
        runner = JobRunner(self.repository, (adapter,))
        self.assertEqual(runner.run(self.job_id), JobStatus.UNKNOWN)

        with self.assertRaisesRegex(ValueError, "not runnable"):
            runner.run(self.job_id)

    def test_waiting_user_message_is_visible_in_persisted_job(self) -> None:
        adapter = FakeAdapter(
            [PublishResult(JobStatus.WAITING_USER, message="complete account setup")]
        )
        runner = JobRunner(self.repository, (adapter,))

        self.assertEqual(runner.run(self.job_id), JobStatus.WAITING_USER)

        bundle = self.repository.get_post(self.created.post_id)
        assert bundle is not None
        self.assertEqual(
            bundle["jobs"][0]["error_message"],  # type: ignore[index]
            "complete account setup",
        )

    def test_pending_remote_is_polled_without_incrementing_publish_attempts(self) -> None:
        adapter = FakeAdapter(
            [
                PublishResult(JobStatus.PENDING_REMOTE, remote_id="publish-1"),
                PublishResult(
                    JobStatus.SUCCEEDED,
                    remote_id="article-1",
                    result_url="https://example.com/article",
                ),
            ]
        )
        runner = JobRunner(self.repository, (adapter,))
        now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(runner.run(self.job_id, now), JobStatus.PENDING_REMOTE)
        pending = self.repository.get_job_context(self.job_id)
        assert pending is not None
        self.assertEqual(pending.attempts, 1)
        self.assertEqual(pending.remote_id, "publish-1")

        self.assertEqual(runner.run(self.job_id, now + timedelta(seconds=10)), JobStatus.SUCCEEDED)
        finished = self.repository.get_job_context(self.job_id)
        assert finished is not None
        self.assertEqual(finished.attempts, 1)

    def test_missing_adapter_fails_safely(self) -> None:
        runner = JobRunner(self.repository, ())
        self.assertEqual(runner.run(self.job_id), JobStatus.FAILED)
        self.assertEqual(self.status(), JobStatus.FAILED)

    def test_scheduler_marks_old_jobs_missed(self) -> None:
        scheduled_at = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
        context = self.repository.get_job_context(self.job_id)
        assert context is not None
        self.repository.transition_job(
            self.job_id,
            expected=JobStatus.READY,
            target=JobStatus.RUNNING,
        )
        self.repository.transition_job(
            self.job_id,
            expected=JobStatus.RUNNING,
            target=JobStatus.SCHEDULED,
            scheduled_at=scheduled_at,
        )
        adapter = FakeAdapter([])
        scheduler = SchedulerCore(self.repository, JobRunner(self.repository, (adapter,)))

        results = scheduler.recover_and_run(scheduled_at + timedelta(minutes=31))

        self.assertEqual(results, [(self.job_id, JobStatus.MISSED)])
        self.assertEqual(self.status(), JobStatus.MISSED)
        self.assertEqual(adapter.calls, 0)


if __name__ == "__main__":
    unittest.main()
