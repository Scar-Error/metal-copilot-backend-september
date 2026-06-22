from __future__ import annotations

import logging
import os
from typing import Optional

from django.conf import settings

from rfq.interfaces import AttachmentData, FileStorage
from rfq.models import Order, OrderAttachment

logger = logging.getLogger(__name__)


class LocalFileStorage:
    """Save files to the local filesystem under ``settings.MEDIA_ROOT``."""

    def save(self, filename: str, content: bytes, subdir: str = '') -> str:
        dest = settings.MEDIA_ROOT / subdir
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
    """Download, store, and manage order attachments."""

    def __init__(self, storage: Optional[FileStorage] = None) -> None:
        self._storage: FileStorage = storage or LocalFileStorage()

    def save_attachment(
        self,
        order: Order,
        attachment: AttachmentData,
        content: bytes,
    ) -> Optional[OrderAttachment]:
        """Persist an attachment and return the model instance."""
        filename = attachment.get('name', 'unnamed')
        if not filename or '..' in filename or '/' in filename or '\\' in filename:
            logger.warning('Suspicious attachment filename: %s', filename)
            return None

        max_size = getattr(settings, 'RFQ_ATTACHMENT_MAX_SIZE', 50 * 1024 * 1024)
        if len(content) > max_size:
            logger.error(
                'Attachment %s exceeds size limit (%d > %d)',
                filename, len(content), max_size,
            )
            return None

        try:
            file_path = self._storage.save(
                filename=filename,
                content=content,
                subdir=f'attachments/{order.id}',
            )
        except OSError as exc:
            logger.error('Failed to save attachment %s: %s', filename, exc)
            return None

        return OrderAttachment.objects.create(
            order=order,
            filename=filename,
            file_path=file_path,
            file_size=attachment.get('size', len(content)),
            file_type=filename.split('.')[-1].upper() if '.' in filename else 'UNKNOWN',
            mime_type=attachment.get('content_type', ''),
        )
