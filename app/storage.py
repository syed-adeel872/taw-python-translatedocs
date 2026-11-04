"""Safe local file storage for uploads and generated outputs."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from app.errors import DocumentProcessingError

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.uploads = self.root / "uploads"
        self.outputs = self.root / "outputs"

    def ensure(self) -> None:
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.outputs.mkdir(parents=True, exist_ok=True)

    def save_upload(self, data: bytes, extension: str) -> tuple[Path, str]:
        name = f"{uuid4().hex}{extension}"
        path = self.uploads / name
        path.write_bytes(data)
        return path, name

    def delete_upload(self, name: str) -> None:
        """Remove a previously saved upload, ignoring missing files.

        Filesystem failures are logged but never replace the original error that
        triggered cleanup.
        """
        try:
            path = self._resolve(self.uploads, name)
        except DocumentProcessingError:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove uploaded file at %s", path)

    def new_output(self, extension: str) -> tuple[Path, str]:
        name = f"{uuid4().hex}{extension}"
        return self.outputs / name, name

    def upload_path(self, name: str) -> Path:
        return self._resolve(self.uploads, name)

    def output_path(self, name: str) -> Path:
        return self._resolve(self.outputs, name)

    @staticmethod
    def _resolve(base: Path, name: str) -> Path:
        if not name or Path(name).name != name:
            raise DocumentProcessingError("Stored file reference is invalid.")
        path = (base / name).resolve()
        if path.parent != base.resolve():
            raise DocumentProcessingError("Stored file reference is invalid.")
        return path
