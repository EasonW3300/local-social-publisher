from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .assets import StoredAsset
from .domain import JobStatus, PostDraft, content_fingerprint


@dataclass(frozen=True, slots=True)
class CreatedPost:
    post_id: str
    job_ids: dict[str, str]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class JobContext:
    job_id: str
    post_id: str
    platform: str
    status: JobStatus
    attempts: int
    max_attempts: int
    title: str
    body: str
    content_type: str
    image_path: Path
    image_usage: str
    scheduled_at: datetime | None
    remote_id: str | None


class Repository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(_SCHEMA)
            connection.execute("PRAGMA journal_mode = WAL")

    def create_post(self, draft: PostDraft, asset: StoredAsset) -> CreatedPost:
        now = datetime.now(timezone.utc).isoformat()
        post_id = str(uuid.uuid4())
        fingerprint = content_fingerprint(draft.title, draft.markdown, asset.sha256)
        initial_status = JobStatus.SCHEDULED if draft.scheduled_at else JobStatus.READY
        scheduled_at = draft.scheduled_at.isoformat() if draft.scheduled_at else None
        job_ids: dict[str, str] = {}

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO posts(id, title, source_markdown, fingerprint, scheduled_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (post_id, draft.title, draft.markdown, fingerprint, scheduled_at, now),
            )
            connection.execute(
                """
                INSERT INTO assets(
                    id, post_id, sha256, original_name, stored_path, size_bytes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    post_id,
                    asset.sha256,
                    asset.original_name,
                    str(asset.stored_path),
                    asset.size_bytes,
                    now,
                ),
            )
            for platform in draft.platforms:
                job_id = str(uuid.uuid4())
                job_ids[platform.value] = job_id
                connection.execute(
                    """
                    INSERT INTO platform_jobs(
                        id, post_id, platform, status, image_usage, attempts,
                        max_attempts, scheduled_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 3, ?, ?, ?)
                    """,
                    (
                        job_id,
                        post_id,
                        platform.value,
                        initial_status.value,
                        draft.image_usage[platform].value,
                        scheduled_at,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO job_events(id, job_id, event_type, details_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        job_id,
                        "job_created",
                        json.dumps({"status": initial_status.value}),
                        now,
                    ),
                )

        return CreatedPost(post_id=post_id, job_ids=job_ids, fingerprint=fingerprint)

    def find_recent_duplicates(self, fingerprint: str, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT id, title, created_at
                    FROM posts
                    WHERE fingerprint = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (fingerprint, limit),
                )
            )

    def get_post(self, post_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            post = connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
            if post is None:
                return None
            jobs = connection.execute(
                "SELECT * FROM platform_jobs WHERE post_id = ? ORDER BY platform", (post_id,)
            ).fetchall()
            asset = connection.execute(
                "SELECT * FROM assets WHERE post_id = ?", (post_id,)
            ).fetchone()
            return {
                "post": dict(post),
                "jobs": [dict(job) for job in jobs],
                "asset": dict(asset) if asset else None,
            }

    def get_job_context(self, job_id: str) -> JobContext | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    platform_jobs.id AS job_id,
                    platform_jobs.post_id,
                    platform_jobs.platform,
                    platform_jobs.status,
                    platform_jobs.attempts,
                    platform_jobs.max_attempts,
                    platform_jobs.image_usage,
                    platform_jobs.scheduled_at,
                    platform_jobs.remote_id,
                    rendered_contents.title,
                    rendered_contents.body,
                    rendered_contents.content_type,
                    assets.stored_path
                FROM platform_jobs
                JOIN rendered_contents ON rendered_contents.job_id = platform_jobs.id
                JOIN assets ON assets.post_id = platform_jobs.post_id
                WHERE platform_jobs.id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        scheduled_at = datetime.fromisoformat(row["scheduled_at"]) if row["scheduled_at"] else None
        return JobContext(
            job_id=row["job_id"],
            post_id=row["post_id"],
            platform=row["platform"],
            status=JobStatus(row["status"]),
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            title=row["title"],
            body=row["body"],
            content_type=row["content_type"],
            image_path=Path(row["stored_path"]),
            image_usage=row["image_usage"],
            scheduled_at=scheduled_at,
            remote_id=row["remote_id"],
        )

    def list_runnable_job_ids(self, now: datetime, limit: int = 20) -> list[str]:
        if now.tzinfo is None:
            raise ValueError("now must include timezone information")
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM platform_jobs
                WHERE status = 'ready'
                   OR (status = 'scheduled' AND scheduled_at <= ?)
                   OR (status = 'pending_remote' AND scheduled_at <= ?)
                ORDER BY COALESCE(scheduled_at, created_at), created_at
                LIMIT ?
                """,
                (now.isoformat(), now.isoformat(), limit),
            ).fetchall()
        return [row["id"] for row in rows]

    def transition_job(
        self,
        job_id: str,
        *,
        expected: JobStatus,
        target: JobStatus,
        attempts: int | None = None,
        scheduled_at: datetime | None = None,
        remote_id: str | None = None,
        result_url: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        event_details: dict[str, object] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        values = {
            "status": target.value,
            "attempts": attempts,
            "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
            "remote_id": remote_id,
            "result_url": result_url,
            "error_code": error_code,
            "error_message": error_message,
            "updated_at": now,
            "id": job_id,
            "expected": expected.value,
        }
        assignments = ["status = :status", "updated_at = :updated_at"]
        for name in (
            "attempts",
            "scheduled_at",
            "remote_id",
            "result_url",
            "error_code",
            "error_message",
        ):
            if values[name] is not None:
                assignments.append(f"{name} = :{name}")

        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE platform_jobs SET {', '.join(assignments)} "
                "WHERE id = :id AND status = :expected",
                values,
            )
            if cursor.rowcount != 1:
                raise ValueError(f"job {job_id} is no longer in expected state {expected.value}")
            details = {"from": expected.value, "to": target.value}
            if event_details:
                details.update(event_details)
            connection.execute(
                """
                INSERT INTO job_events(id, job_id, event_type, details_json, created_at)
                VALUES (?, ?, 'status_changed', ?, ?)
                """,
                (str(uuid.uuid4()), job_id, json.dumps(details), now),
            )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 20),
    source_markdown TEXT NOT NULL CHECK(length(source_markdown) BETWEEN 1 AND 2000),
    fingerprint TEXT NOT NULL,
    scheduled_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_fingerprint ON posts(fingerprint, created_at DESC);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    sha256 TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_jobs (
    id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    platform TEXT NOT NULL CHECK(platform IN ('wechat', 'csdn')),
    status TEXT NOT NULL CHECK(status IN (
        'ready', 'scheduled', 'running', 'pending_remote', 'waiting_user', 'succeeded',
        'failed', 'unknown', 'missed', 'canceled'
    )),
    image_usage TEXT NOT NULL CHECK(image_usage IN ('cover', 'body', 'both')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    scheduled_at TEXT,
    remote_id TEXT,
    result_url TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(post_id, platform)
);
CREATE INDEX IF NOT EXISTS idx_platform_jobs_status
    ON platform_jobs(status, scheduled_at, created_at);

CREATE TABLE IF NOT EXISTS rendered_contents (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES platform_jobs(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    content_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES platform_jobs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, created_at);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL CHECK(platform IN ('wechat', 'csdn')),
    display_name TEXT NOT NULL,
    secret_reference TEXT,
    browser_profile_path TEXT,
    capability_status TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
