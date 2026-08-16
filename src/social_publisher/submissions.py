from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .assets import AssetStore
from .domain import Platform, PostDraft
from .rendering import RenderedContent, RendererRegistry
from .storage import CreatedPost, Repository


class SubmissionService:
    def __init__(
        self,
        repository: Repository,
        asset_store: AssetStore,
        renderers: RendererRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.asset_store = asset_store
        self.renderers = renderers or RendererRegistry()

    def preview(self, draft: PostDraft) -> dict[Platform, RenderedContent]:
        return self.renderers.render_selected(draft)

    def submit(self, draft: PostDraft) -> CreatedPost:
        asset = self.asset_store.add(draft.image_path)
        rendered = self.preview(draft)
        created = self.repository.create_post(draft, asset)
        self._save_rendered(created, rendered)
        return created

    def _save_rendered(
        self,
        created: CreatedPost,
        rendered: dict[Platform, RenderedContent],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.repository.connect() as connection:
            for platform, content in rendered.items():
                job_id = created.job_ids[platform.value]
                connection.execute(
                    """
                    INSERT INTO rendered_contents(
                        id, job_id, title, body, content_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        job_id,
                        content.title,
                        content.body,
                        content.content_type,
                        now,
                    ),
                )
                if content.warnings:
                    connection.execute(
                        """
                        INSERT INTO job_events(id, job_id, event_type, details_json, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            job_id,
                            "render_warning",
                            json.dumps({"warnings": list(content.warnings)}),
                            now,
                        ),
                    )

