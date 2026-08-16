from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from social_publisher.assets import AssetStore
from social_publisher.domain import AssetUsage, Platform, PostDraft
from social_publisher.rendering import CsdnRenderer, RendererRegistry, WeChatRenderer
from social_publisher.storage import Repository
from social_publisher.submissions import DuplicateSubmissionError, SubmissionService


def draft_for(platforms: tuple[Platform, ...] = (Platform.WECHAT, Platform.CSDN)) -> PostDraft:
    usage = {
        Platform.WECHAT: AssetUsage.BOTH,
        Platform.CSDN: AssetUsage.BODY,
    }
    return PostDraft(
        title="安全发布",
        markdown=(
            "# Heading\n\nA **bold** paragraph with <script>alert(1)</script>.\n\n- first\n- second"
        ),
        image_path=Path("image.png"),
        platforms=platforms,
        image_usage={platform: usage[platform] for platform in platforms},
    )


class RendererTests(unittest.TestCase):
    def test_wechat_renderer_escapes_raw_html_and_adds_body_image(self) -> None:
        rendered = WeChatRenderer().render(draft_for((Platform.WECHAT,)))

        self.assertEqual(rendered.content_type, "text/html")
        self.assertIn("{{IMAGE_URL}}", rendered.body)
        self.assertIn("<strong>bold</strong>", rendered.body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered.body)
        self.assertNotIn("<script>", rendered.body)
        self.assertIn("<ul><li>first</li><li>second</li></ul>", rendered.body)

    def test_csdn_renderer_keeps_markdown_and_adds_image_placeholder(self) -> None:
        rendered = CsdnRenderer().render(draft_for((Platform.CSDN,)))

        self.assertEqual(rendered.content_type, "text/markdown")
        self.assertTrue(rendered.body.startswith("![安全发布]({{IMAGE_URL}})"))
        self.assertIn("# Heading", rendered.body)

    def test_registry_only_renders_selected_platforms(self) -> None:
        rendered = RendererRegistry().render_selected(draft_for((Platform.CSDN,)))
        self.assertEqual(set(rendered), {Platform.CSDN})


class SubmissionServiceTests(unittest.TestCase):
    def test_submit_persists_rendered_contents_for_each_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            image.write_bytes(b"image")
            source = draft_for()
            draft = PostDraft(
                title=source.title,
                markdown=source.markdown,
                image_path=image,
                platforms=source.platforms,
                image_usage=source.image_usage,
            )
            repository = Repository(root / "publisher.sqlite3")
            repository.initialize()
            service = SubmissionService(repository, AssetStore(root / "assets"))

            created = service.submit(draft)

            with repository.connect() as connection:
                rows = connection.execute(
                    """
                    SELECT platform, content_type, body
                    FROM rendered_contents
                    JOIN platform_jobs ON platform_jobs.id = rendered_contents.job_id
                    WHERE platform_jobs.post_id = ?
                    ORDER BY platform
                    """,
                    (created.post_id,),
                ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {(row["platform"], row["content_type"]) for row in rows},
                {("csdn", "text/markdown"), ("wechat", "text/html")},
            )

    def test_duplicate_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            image.write_bytes(b"image")
            source = draft_for()
            draft = PostDraft(
                title=source.title,
                markdown=source.markdown,
                image_path=image,
                platforms=source.platforms,
                image_usage=source.image_usage,
            )
            repository = Repository(root / "publisher.sqlite3")
            repository.initialize()
            service = SubmissionService(repository, AssetStore(root / "assets"))
            service.submit(draft)

            with self.assertRaises(DuplicateSubmissionError):
                service.submit(draft)

            confirmed = service.submit(draft, confirm_duplicate=True)
            self.assertIsNotNone(confirmed.post_id)


if __name__ == "__main__":
    unittest.main()
