from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path


_ALLOWED_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StoredAsset:
    sha256: str
    original_name: str
    stored_path: Path
    size_bytes: int


class AssetStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def add(self, source: Path) -> StoredAsset:
        source = Path(source)
        if not source.is_file():
            raise ValueError("image must be an existing file")

        extension = source.suffix.lower()
        if extension not in _ALLOWED_EXTENSIONS:
            raise ValueError("image must be png, jpeg, gif, or webp")

        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                if size > _MAX_IMAGE_BYTES:
                    raise ValueError("image must not exceed 10 MiB")
                digest.update(chunk)

        sha256 = digest.hexdigest()
        destination = self.root / f"{sha256}{extension}"
        if not destination.exists():
            shutil.copy2(source, destination)

        return StoredAsset(
            sha256=sha256,
            original_name=source.name,
            stored_path=destination,
            size_bytes=size,
        )

