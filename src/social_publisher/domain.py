from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class Platform(str, Enum):
    WECHAT = "wechat"
    CSDN = "csdn"


class AssetUsage(str, Enum):
    COVER = "cover"
    BODY = "body"
    BOTH = "both"


class JobStatus(str, Enum):
    READY = "ready"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    MISSED = "missed"
    CANCELED = "canceled"


_SPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def normalize_content(value: str) -> str:
    """Normalize insignificant whitespace without changing authored line breaks."""

    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = "\n".join(_SPACE_RE.sub(" ", line).strip() for line in normalized.split("\n"))
    return _BLANK_LINES_RE.sub("\n\n", normalized)


def content_fingerprint(title: str, markdown: str, image_sha256: str) -> str:
    payload = "\0".join(
        (
            normalize_content(title),
            normalize_content(markdown),
            image_sha256.lower().strip(),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PostDraft:
    title: str
    markdown: str
    image_path: Path
    platforms: tuple[Platform, ...]
    image_usage: dict[Platform, AssetUsage]
    scheduled_at: datetime | None = None

    def __post_init__(self) -> None:
        title = self.title.strip()
        markdown = self.markdown.strip()
        unique_platforms = tuple(dict.fromkeys(self.platforms))

        if not title:
            raise ValueError("title is required")
        if len(title) > 20:
            raise ValueError("title must contain at most 20 characters")
        if not markdown:
            raise ValueError("markdown is required")
        if len(markdown) > 2_000:
            raise ValueError("markdown must contain at most 2000 characters")
        if not unique_platforms:
            raise ValueError("at least one platform is required")
        if set(self.image_usage) != set(unique_platforms):
            raise ValueError("image usage must be specified for every selected platform")
        if self.scheduled_at is not None and self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must include timezone information")

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "markdown", markdown)
        object.__setattr__(self, "image_path", Path(self.image_path))
        object.__setattr__(self, "platforms", unique_platforms)

