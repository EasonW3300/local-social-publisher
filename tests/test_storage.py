from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from social_publisher.assets import AssetStore
from social_publisher.domain import AssetUsage, JobStatus, Platform, PostDraft
from social_publisher.storage import Repository


class AssetStoreTests(unittest.TestCase):
    def test_copies_and_deduplicates_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            source.write_bytes(b"fake png for storage contract")
            store = AssetStore(root / "assets")

            first = store.add(source)
            second = store.add(source)

            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual(first.stored_path, second.stored_path)
            self.assertEqual(first.stored_path.read_bytes(), source.read_bytes())
            self.assertEqual(len(list((root / "assets").iterdir())), 1)

    def test_rejects_unsupported_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            source.write_text("not an image")
            with self.assertRaisesRegex(ValueError, "png, jpeg"):
                AssetStore(Path(directory) / "assets").add(source)


class RepositoryTests(unittest.TestCase):
    def test_creates_grouped_platform_jobs_and_finds_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jpg"
            source.write_bytes(b"image bytes")
            asset = AssetStore(root / "assets").add(source)
            repository = Repository(root / "publisher.sqlite3")
            repository.initialize()
            draft = PostDraft(
                title="Cross platform post",
                markdown="A deterministic body",
                image_path=source,
                platforms=(Platform.WECHAT, Platform.CSDN),
                image_usage={
                    Platform.WECHAT: AssetUsage.COVER,
                    Platform.CSDN: AssetUsage.BODY,
                },
            )

            created = repository.create_post(draft, asset)
            bundle = repository.get_post(created.post_id)

            self.assertIsNotNone(bundle)
            assert bundle is not None
            self.assertEqual(bundle["post"]["title"], draft.title)  # type: ignore[index]
            self.assertEqual(
                {job["platform"] for job in bundle["jobs"]},  # type: ignore[union-attr]
                {Platform.WECHAT.value, Platform.CSDN.value},
            )
            self.assertTrue(
                all(job["status"] == JobStatus.READY.value for job in bundle["jobs"])  # type: ignore[union-attr]
            )
            self.assertEqual(len(repository.find_recent_duplicates(created.fingerprint)), 1)

    def test_scheduled_posts_create_scheduled_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.webp"
            source.write_bytes(b"webp bytes")
            asset = AssetStore(root / "assets").add(source)
            repository = Repository(root / "publisher.sqlite3")
            repository.initialize()
            draft = PostDraft(
                title="Scheduled post",
                markdown="Scheduled body",
                image_path=source,
                platforms=(Platform.CSDN,),
                image_usage={Platform.CSDN: AssetUsage.BOTH},
                scheduled_at=datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc),
            )

            created = repository.create_post(draft, asset)
            bundle = repository.get_post(created.post_id)

            assert bundle is not None
            self.assertEqual(bundle["jobs"][0]["status"], JobStatus.SCHEDULED.value)  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
