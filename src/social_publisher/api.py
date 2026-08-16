from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .assets import AssetStore
from .domain import AssetUsage, Platform, PostDraft
from .rendering import RendererRegistry
from .storage import Repository
from .submissions import DuplicateSubmissionError, SubmissionService


class PreviewItem(BaseModel):
    platform: Platform
    title: str
    body: str
    content_type: str
    warnings: list[str]


class PreviewResponse(BaseModel):
    items: list[PreviewItem]


class SubmissionResponse(BaseModel):
    post_id: str
    job_ids: dict[str, str]
    fingerprint: str


class HealthResponse(BaseModel):
    status: str


DispatchJobs = Callable[[list[str]], None]


def create_app(
    data_dir: Path,
    *,
    dispatch_jobs: DispatchJobs | None = None,
) -> FastAPI:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    repository = Repository(data_dir / "publisher.sqlite3")
    repository.initialize()
    service = SubmissionService(repository, AssetStore(data_dir / "assets"))
    renderers = RendererRegistry()

    app = FastAPI(title="Local Social Publisher", version="0.1.0")
    app.state.repository = repository
    app.state.submission_service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Local-Publisher-Token"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post("/api/previews", response_model=PreviewResponse)
    def preview(
        title: Annotated[str, Form()],
        markdown: Annotated[str, Form()],
        platforms: Annotated[str, Form()],
        image_usage: Annotated[str, Form()],
        image: Annotated[UploadFile, File()],
        scheduled_at: Annotated[str | None, Form()] = None,
    ) -> PreviewResponse:
        draft = _draft_from_form(
            title,
            markdown,
            platforms,
            image_usage,
            Path(image.filename or "preview.png"),
            scheduled_at,
        )
        rendered = renderers.render_selected(draft)
        return PreviewResponse(
            items=[
                PreviewItem(
                    platform=platform,
                    title=item.title,
                    body=item.body,
                    content_type=item.content_type,
                    warnings=list(item.warnings),
                )
                for platform, item in rendered.items()
            ]
        )

    @app.post(
        "/api/submissions",
        response_model=SubmissionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def submit(
        background_tasks: BackgroundTasks,
        title: Annotated[str, Form()],
        markdown: Annotated[str, Form()],
        platforms: Annotated[str, Form()],
        image_usage: Annotated[str, Form()],
        image: Annotated[UploadFile, File()],
        scheduled_at: Annotated[str | None, Form()] = None,
        confirm_duplicate: Annotated[bool, Form()] = False,
    ) -> SubmissionResponse:
        suffix = Path(image.filename or "image.png").suffix.lower() or ".png"
        incoming_dir = data_dir / "incoming"
        incoming_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=suffix, dir=incoming_dir, delete=False) as target:
            temporary_path = Path(target.name)
            shutil.copyfileobj(image.file, target)
        try:
            draft = _draft_from_form(
                title,
                markdown,
                platforms,
                image_usage,
                temporary_path,
                scheduled_at,
            )
            created = service.submit(draft, confirm_duplicate=confirm_duplicate)
        except DuplicateSubmissionError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "duplicate_submission", "post_ids": error.post_ids},
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "validation_error", "message": str(error)},
            ) from error
        finally:
            temporary_path.unlink(missing_ok=True)

        job_ids = list(created.job_ids.values())
        if dispatch_jobs is not None and scheduled_at is None:
            background_tasks.add_task(dispatch_jobs, job_ids)
        return SubmissionResponse(
            post_id=created.post_id,
            job_ids=created.job_ids,
            fingerprint=created.fingerprint,
        )

    @app.get("/api/submissions")
    def list_submissions(limit: int = 100, offset: int = 0) -> dict[str, object]:
        if not 1 <= limit <= 500 or offset < 0:
            raise HTTPException(status_code=422, detail="invalid pagination")
        return {"items": repository.list_posts(limit, offset)}

    @app.get("/api/submissions/{post_id}")
    def get_submission(post_id: str) -> dict[str, object]:
        result = repository.get_post(post_id)
        if result is None:
            raise HTTPException(status_code=404, detail="submission not found")
        return result

    return app


def _draft_from_form(
    title: str,
    markdown: str,
    platforms_json: str,
    image_usage_json: str,
    image_path: Path,
    scheduled_at: str | None,
) -> PostDraft:
    try:
        platform_values = json.loads(platforms_json)
        usage_values = json.loads(image_usage_json)
        if not isinstance(platform_values, list) or not isinstance(usage_values, dict):
            raise ValueError("platforms must be a list and image_usage must be an object")
        selected = tuple(Platform(value) for value in platform_values)
        usage = {Platform(key): AssetUsage(value) for key, value in usage_values.items()}
        schedule = datetime.fromisoformat(scheduled_at) if scheduled_at else None
        return PostDraft(
            title=title,
            markdown=markdown,
            image_path=image_path,
            platforms=selected,
            image_usage=usage,
            scheduled_at=schedule,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError(str(error)) from error
