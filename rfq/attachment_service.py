from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from django.conf import settings

from rfq.interfaces import AttachmentData

logger = logging.getLogger(__name__)


class LocalFileStorage:
    """Save files to the local filesystem under a base directory."""

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else settings.MEDIA_ROOT

    def save(self, filename: str, content: bytes, subdir: str = '') -> str:
        dest = self._base_dir / subdir
        os.makedirs(dest, exist_ok=True)
        path = dest / filename
        with open(path, 'wb') as f:
            f.write(content)
        return str(path)

    def delete(self, path: str) -> bool:
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            logger.error('File delete error [%s]: %s', path, exc)
            return False

    def exists(self, path: str) -> bool:
        return os.path.exists(path)


class AttachmentService:
    """
    Download, store temporarily, and clean up email attachments.

    Attachments are kept under ``MEDIA_ROOT/temp_attachments/<order_id>/`` so
    image attachments can be handed to the AI extractor without becoming
    permanent records. Document attachments are stored long enough to have
    their text extracted.
    """

    def __init__(self, storage=None) -> None:
        self._storage = storage or LocalFileStorage()

    def save_temp(self, order_id, filename: str, content: bytes) -> Optional[str]:
        """Save an attachment temporarily and return the file path."""
        if not filename or '..' in filename:
            filename = 'attachment'
        safe_name = Path(filename).name or 'attachment'

        max_size = getattr(settings, 'RFQ_ATTACHMENT_MAX_SIZE', 50 * 1024 * 1024)
        if len(content) > max_size:
            logger.error(
                'Attachment %s exceeds size limit (%d > %d)',
                safe_name, len(content), max_size,
            )
            return None

        try:
            return self._storage.save(
                filename=safe_name,
                content=content,
                subdir=f'temp_attachments/{order_id}',
            )
        except OSError as exc:
            logger.error('Failed to save attachment %s: %s', safe_name, exc)
            return None

    def delete(self, path: str) -> bool:
        return self._storage.delete(path)
