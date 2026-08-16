from __future__ import annotations

import json
import secrets
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from .assets import AssetStore
from .domain import AssetUsage, Platform, PostDraft
from .rendering import RendererRegistry
from .storage import Repository
from .submissions import DuplicateSubmissionError, SubmissionService

if TYPE_CHECKING:
    from .settings import SettingsService


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


class WeChatSettingsRequest(BaseModel):
    app_id: str = ""
    app_secret: str | None = None
    browser_fallback_enabled: bool = False


class WeChatSettingsResponse(BaseModel):
    app_id: str
    secret_configured: bool
    official_configured: bool
    browser_fallback_enabled: bool


DispatchJobs = Callable[[list[str]], None]
OpenBrowser = Callable[[], None]


def create_app(
    data_dir: Path,
    *,
    dispatch_jobs: DispatchJobs | None = None,
    settings_service: SettingsService | None = None,
    open_csdn_login: OpenBrowser | None = None,
    open_wechat_login: OpenBrowser | None = None,
    frontend_dir: Path | None = None,
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
    app.state.local_api_token = secrets.token_urlsafe(32)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "X-Local-Publisher-Token"],
    )

    @app.middleware("http")
    async def require_local_api_token(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied = request.headers.get("X-Local-Publisher-Token", "")
            if not supplied or not secrets.compare_digest(supplied, app.state.local_api_token):
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "invalid local session token"},
                )
        return await call_next(request)

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/api/session")
    def local_session() -> dict[str, str]:
        return {"token": app.state.local_api_token}

    if settings_service is not None:

        @app.get("/api/settings/wechat", response_model=WeChatSettingsResponse)
        def get_wechat_settings() -> WeChatSettingsResponse:
            current = settings_service.wechat()
            return WeChatSettingsResponse(
                app_id=current.app_id,
                secret_configured=current.secret_configured,
                official_configured=current.official_configured,
                browser_fallback_enabled=current.browser_fallback_enabled,
            )

        @app.put("/api/settings/wechat", response_model=WeChatSettingsResponse)
        def put_wechat_settings(request: WeChatSettingsRequest) -> WeChatSettingsResponse:
            current = settings_service.configure_wechat(
                app_id=request.app_id,
                app_secret=request.app_secret,
                browser_fallback_enabled=request.browser_fallback_enabled,
            )
            return WeChatSettingsResponse(
                app_id=current.app_id,
                secret_configured=current.secret_configured,
                official_configured=current.official_configured,
                browser_fallback_enabled=current.browser_fallback_enabled,
            )

    if open_csdn_login is not None:

        @app.post("/api/browser/csdn/login", status_code=status.HTTP_202_ACCEPTED)
        def start_csdn_login(background_tasks: BackgroundTasks) -> dict[str, str]:
            background_tasks.add_task(open_csdn_login)
            return {"status": "opening"}

    if open_wechat_login is not None:

        @app.post("/api/browser/wechat/login", status_code=status.HTTP_202_ACCEPTED)
        def start_wechat_login(background_tasks: BackgroundTasks) -> dict[str, str]:
            background_tasks.add_task(open_wechat_login)
            return {"status": "opening"}

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

    if frontend_dir is not None and Path(frontend_dir).is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

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
