from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .domain import JobStatus, Platform
from .storage import JobContext, Repository


class TransientPublishError(RuntimeError):
    def __init__(self, message: str, code: str = "transient_error") -> None:
        super().__init__(message)
        self.code = code


class PermanentPublishError(RuntimeError):
    def __init__(self, message: str, code: str = "permanent_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PublishResult:
    status: JobStatus
    remote_id: str | None = None
    result_url: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        allowed = {
            JobStatus.SUCCEEDED,
            JobStatus.PENDING_REMOTE,
            JobStatus.WAITING_USER,
            JobStatus.UNKNOWN,
        }
        if self.status not in allowed:
            raise ValueError(
                "adapter result must be succeeded, pending_remote, waiting_user, or unknown"
            )
        if self.status is JobStatus.SUCCEEDED and not self.result_url:
            raise ValueError("successful publishing must include a result URL")


class PlatformAdapter(Protocol):
    platform: Platform

    def publish(self, job: JobContext) -> PublishResult: ...


class JobStateMachine:
    _ALLOWED = {
        JobStatus.READY: {JobStatus.RUNNING, JobStatus.CANCELED},
        JobStatus.SCHEDULED: {JobStatus.RUNNING, JobStatus.MISSED, JobStatus.CANCELED},
        JobStatus.RUNNING: {
            JobStatus.SCHEDULED,
            JobStatus.PENDING_REMOTE,
            JobStatus.WAITING_USER,
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.UNKNOWN,
        },
        JobStatus.PENDING_REMOTE: {JobStatus.RUNNING, JobStatus.CANCELED},
        JobStatus.WAITING_USER: {JobStatus.RUNNING, JobStatus.CANCELED},
        JobStatus.FAILED: {JobStatus.READY, JobStatus.CANCELED},
        JobStatus.MISSED: {JobStatus.READY, JobStatus.CANCELED},
        JobStatus.SUCCEEDED: set(),
        JobStatus.UNKNOWN: set(),
        JobStatus.CANCELED: set(),
    }

    @classmethod
    def ensure_allowed(cls, source: JobStatus, target: JobStatus) -> None:
        if target not in cls._ALLOWED[source]:
            raise ValueError(f"illegal job transition: {source.value} -> {target.value}")


class JobRunner:
    _RETRY_DELAYS = (timedelta(seconds=5), timedelta(seconds=30), timedelta(minutes=2))

    def __init__(self, repository: Repository, adapters: tuple[PlatformAdapter, ...]) -> None:
        self.repository = repository
        self.adapters = {adapter.platform.value: adapter for adapter in adapters}

    def run(self, job_id: str, now: datetime | None = None) -> JobStatus:
        now = now or datetime.now(timezone.utc)
        context = self.repository.get_job_context(job_id)
        if context is None:
            raise ValueError(f"job not found: {job_id}")
        if context.status not in (
            JobStatus.READY,
            JobStatus.SCHEDULED,
            JobStatus.PENDING_REMOTE,
            JobStatus.WAITING_USER,
        ):
            raise ValueError(f"job is not runnable from {context.status.value}")

        JobStateMachine.ensure_allowed(context.status, JobStatus.RUNNING)
        attempt = (
            context.attempts if context.status is JobStatus.PENDING_REMOTE else context.attempts + 1
        )
        self.repository.transition_job(
            job_id,
            expected=context.status,
            target=JobStatus.RUNNING,
            attempts=attempt,
            event_details={"attempt": attempt},
        )
        running_context = self.repository.get_job_context(job_id)
        assert running_context is not None
        adapter = self.adapters.get(running_context.platform)
        if adapter is None:
            return self._fail(
                running_context,
                code="adapter_missing",
                message=f"no adapter for {running_context.platform}",
            )

        try:
            result = adapter.publish(running_context)
        except TransientPublishError as error:
            return self._retry_or_fail(running_context, now, error)
        except PermanentPublishError as error:
            return self._fail(running_context, error.code, str(error))
        except Exception as error:
            return self._fail(running_context, "adapter_crash", str(error))

        JobStateMachine.ensure_allowed(JobStatus.RUNNING, result.status)
        self.repository.transition_job(
            job_id,
            expected=JobStatus.RUNNING,
            target=result.status,
            scheduled_at=(now + timedelta(seconds=10))
            if result.status is JobStatus.PENDING_REMOTE
            else None,
            remote_id=result.remote_id,
            result_url=result.result_url,
            event_details={"message": result.message} if result.message else None,
        )
        return result.status

    def _retry_or_fail(
        self, context: JobContext, now: datetime, error: TransientPublishError
    ) -> JobStatus:
        if context.attempts >= context.max_attempts:
            return self._fail(context, error.code, str(error))
        JobStateMachine.ensure_allowed(JobStatus.RUNNING, JobStatus.SCHEDULED)
        delay = self._RETRY_DELAYS[min(context.attempts - 1, len(self._RETRY_DELAYS) - 1)]
        retry_at = now + delay
        self.repository.transition_job(
            context.job_id,
            expected=JobStatus.RUNNING,
            target=JobStatus.SCHEDULED,
            scheduled_at=retry_at,
            error_code=error.code,
            error_message=str(error),
            event_details={"retry_at": retry_at.isoformat()},
        )
        return JobStatus.SCHEDULED

    def _fail(self, context: JobContext, code: str, message: str) -> JobStatus:
        JobStateMachine.ensure_allowed(JobStatus.RUNNING, JobStatus.FAILED)
        self.repository.transition_job(
            context.job_id,
            expected=JobStatus.RUNNING,
            target=JobStatus.FAILED,
            error_code=code,
            error_message=message,
        )
        return JobStatus.FAILED


class SchedulerCore:
    def __init__(
        self,
        repository: Repository,
        runner: JobRunner,
        missed_grace: timedelta = timedelta(minutes=30),
    ) -> None:
        self.repository = repository
        self.runner = runner
        self.missed_grace = missed_grace

    def recover_and_run(self, now: datetime | None = None) -> list[tuple[str, JobStatus]]:
        now = now or datetime.now(timezone.utc)
        results: list[tuple[str, JobStatus]] = []
        for job_id in self.repository.list_runnable_job_ids(now):
            context = self.repository.get_job_context(job_id)
            assert context is not None
            if (
                context.status is JobStatus.SCHEDULED
                and context.scheduled_at is not None
                and now - context.scheduled_at > self.missed_grace
            ):
                JobStateMachine.ensure_allowed(JobStatus.SCHEDULED, JobStatus.MISSED)
                self.repository.transition_job(
                    job_id,
                    expected=JobStatus.SCHEDULED,
                    target=JobStatus.MISSED,
                    event_details={"grace_seconds": int(self.missed_grace.total_seconds())},
                )
                results.append((job_id, JobStatus.MISSED))
                continue
            results.append((job_id, self.runner.run(job_id, now)))
        return results
