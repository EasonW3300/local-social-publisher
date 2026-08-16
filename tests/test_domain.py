from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from social_publisher.domain import (
    AssetUsage,
    Platform,
    PostDraft,
    content_fingerprint,
)


class PostDraftTests(unittest.TestCase):
    def make_draft(self, **overrides: object) -> PostDraft:
        values: dict[str, object] = {
            "title": "A useful title",
            "markdown": "A useful body",
            "image_path": Path("image.png"),
            "platforms": (Platform.WECHAT, Platform.CSDN),
            "image_usage": {
                Platform.WECHAT: AssetUsage.COVER,
                Platform.CSDN: AssetUsage.BODY,
            },
        }
        values.update(overrides)
        return PostDraft(**values)  # type: ignore[arg-type]

    def test_accepts_the_product_limits(self) -> None:
        draft = self.make_draft(title="题" * 20, markdown="文" * 2_000)
        self.assertEqual(len(draft.title), 20)
        self.assertEqual(len(draft.markdown), 2_000)

    def test_rejects_title_over_20_characters(self) -> None:
        with self.assertRaisesRegex(ValueError, "at most 20"):
            self.make_draft(title="题" * 21)

    def test_rejects_copy_over_2000_characters(self) -> None:
        with self.assertRaisesRegex(ValueError, "at most 2000"):
            self.make_draft(markdown="文" * 2_001)

    def test_requires_image_usage_for_every_platform(self) -> None:
        with self.assertRaisesRegex(ValueError, "every selected platform"):
            self.make_draft(image_usage={Platform.WECHAT: AssetUsage.COVER})

    def test_schedules_must_be_timezone_aware(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.make_draft(scheduled_at=datetime(2026, 8, 16, 12, 0))

    def test_duplicate_platforms_are_removed(self) -> None:
        draft = self.make_draft(
            platforms=(Platform.WECHAT, Platform.WECHAT),
            image_usage={Platform.WECHAT: AssetUsage.COVER},
        )
        self.assertEqual(draft.platforms, (Platform.WECHAT,))


class FingerprintTests(unittest.TestCase):
    def test_insignificant_whitespace_is_normalized(self) -> None:
        first = content_fingerprint(" Hello ", "one  two\r\n\r\n\r\nthree", "ABC")
        second = content_fingerprint("Hello", "one two\n\nthree", "abc")
        self.assertEqual(first, second)

    def test_content_changes_change_the_fingerprint(self) -> None:
        first = content_fingerprint("Hello", "one", "abc")
        second = content_fingerprint("Hello", "two", "abc")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()

