from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings

from microsoft_auth.graph_api import GraphEmailProvider
from authentication.models import MicrosoftToken
from rfq.models import Order
from rfq.orchestrator import EmailIngestionOrchestrator
from rfq.rfq_builder import RfqBuilder
from rfq.attachment_service import AttachmentService
from rfq.data_extractors import OpenAiExtractor, KeywordExtractor

logger = logging.getLogger(__name__)


class EmailIngestionService:
    """
    Backward-compatible wrapper that builds an
    ``EmailIngestionOrchestrator`` for a given Django user.

    Deprecated: prefer using ``EmailIngestionOrchestrator`` directly
    with explicit dependency injection.
    """

    def __init__(self, user) -> None:
        self.user = user
        self._orchestrator: Optional[EmailIngestionOrchestrator] = None

    @property
    def orchestrator(self) -> EmailIngestionOrchestrator:
        if self._orchestrator is None:
            token: MicrosoftToken = self._resolve_token()
            graph = GraphEmailProvider(
                access_token=token.access_token,
                refresh_token=token.refresh_token,
                token_expires_at=token.token_expires_at,
                user=self.user,
            )
            self._orchestrator = EmailIngestionOrchestrator(
                email_provider=graph,
                data_extractor=OpenAiExtractor(),
                fallback_extractor=KeywordExtractor(),
                rfq_builder=RfqBuilder(),
                attachment_service=AttachmentService(),
                use_ai_classification=True,
            )
        return self._orchestrator

    def check_and_process_new_emails(self, days_back: int = 1) -> dict:
        return self.orchestrator.poll_new_emails(days_back=days_back)

    def send_to_supplier(
        self,
        order_id: int,
        supplier_email: Optional[str] = None,
    ) -> dict:
        try:
            order = Order.objects.get(id=order_id)
            if supplier_email:
                order.supplier_email = supplier_email
                order.save(update_fields=['supplier_email'])

            from rfq.email_service import SupplierEmailService
            svc = SupplierEmailService(
                email_provider=self.orchestrator._email_provider,
            )
            return svc.send_rfq_to_supplier(order)
        except Order.DoesNotExist:
            return {'success': False, 'message': 'Order not found'}
        except Exception as exc:
            logger.error('send_to_supplier error: %s', exc)
            return {'success': False, 'message': str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_token(self) -> MicrosoftToken:
        try:
            token = self.user.microsoft_token
            token.refresh_if_expired()
            return token
        except MicrosoftToken.DoesNotExist:
            msg = f'No MicrosoftToken for user {self.user.username}'
            logger.error(msg)
            raise RuntimeError(msg)
