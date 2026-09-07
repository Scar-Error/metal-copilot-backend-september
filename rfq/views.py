import logging

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from rfq.models import Order, OrderItem, OrderAiMetadata, EmailThread
from rfq.serializers import (
    OrderSerializer,
    OrderListSerializer,
    OrderItemSerializer,
    OrderAnalyticsSerializer,
    DealSerializer,
    EmailThreadSerializer,
)
from rfq.analytics_service import compute_analytics, dashboard_stats
from rfq.ai_usage import ai_usage_stats
from rfq.email_ingestion_service import EmailIngestionService
from microsoft_auth.graph_api import GraphEmailProvider

logger = logging.getLogger(__name__)


def _build_email_provider(user) -> GraphEmailProvider:
    """Helper: build a GraphEmailProvider from a Django user."""
    token = user.microsoft_token
    token.refresh_if_expired()
    return GraphEmailProvider(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        token_expires_at=token.token_expires_at,
        user=user,
    )


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return OrderListSerializer
        return OrderSerializer

    def get_queryset(self):
        qs = Order.objects.all()

        type_param = self.request.query_params.get('type')
        if type_param:
            qs = qs.filter(type=type_param)

        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            qs = qs.filter(created_at__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__lte=end_date)

        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(company_name__icontains=search)
                | Q(rfq_number__icontains=search)
            )

        return qs

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        record = compute_analytics()
        serializer = OrderAnalyticsSerializer(record)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        return Response(dashboard_stats())

    @action(detail=False, methods=['get'])
    def ai_usage(self, request):
        """Aggregated AI API cost analytics (model, use type, per-day)."""
        days = int(request.query_params.get('days', 30))
        return Response(ai_usage_stats(days=days))

    @action(detail=False, methods=['get'])
    def purchase_orders(self, request):
        """Get list of purchase orders (type=purchase_order)."""
        qs = Order.objects.filter(type='purchase_order')

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        if start_date:
            qs = qs.filter(created_at__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__lte=end_date)

        search = request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(company_name__icontains=search)
                | Q(rfq_number__icontains=search)
            )

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = OrderListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = OrderListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def bulk_delete(self, request):
        """Bulk delete multiple RFQs by IDs."""
        ids = request.data.get('ids', [])
        if not ids:
            return Response(
                {'error': 'No IDs provided'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deleted_count = Order.objects.filter(id__in=ids).delete()[0]

        return Response({
            'message': f'{deleted_count} RFQ(s) deleted successfully',
            'deleted_count': deleted_count,
        })

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        order = self.get_object()

        order.reviewed_by = request.user
        order.reviewed_at = timezone.now()
        order.notes = request.data.get('notes', '')
        order.save()

        serializer = OrderSerializer(order)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def process_emails(self, request):
        days_back = request.data.get('days_back', 1)

        try:
            _build_email_provider(request.user)
        except Exception:
            return Response(
                {'success': False, 'message': 'No valid Microsoft token'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        service = EmailIngestionService(request.user)
        result = service.check_and_process_new_emails(days_back=days_back)

        if result['success']:
            return Response(result, status=status.HTTP_200_OK)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)


class OrderItemViewSet(viewsets.ModelViewSet):
    queryset = OrderItem.objects.all()
    serializer_class = OrderItemSerializer
    pagination_class = None

    def get_queryset(self):
        qs = OrderItem.objects.all()
        order_id = self.request.query_params.get('order_id')
        if order_id:
            qs = qs.filter(order_id=order_id)
        return qs


class DealViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.select_related('contact').all()
    serializer_class = DealSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = Order.objects.select_related('contact').all()
        type_param = self.request.query_params.get('type')
        if type_param:
            qs = qs.filter(type=type_param)
        source_param = self.request.query_params.get('source')
        if source_param:
            qs = qs.filter(source=source_param)
        return qs

    @action(detail=True, methods=['post'], url_path='attachments')
    def attachments(self, request, pk=None):
        """Upload attachments for a deal (manual deals)."""
        order = self.get_object()
        files = request.FILES.getlist('files')
        if not files:
            return Response({'error': 'No files provided'}, status=status.HTTP_400_BAD_REQUEST)

        from rfq.attachment_service import AttachmentService
        service = AttachmentService()
        saved = []

        for f in files:
            content = f.read()
            path = service.save_temp(order.id, f.name, content)
            if path:
                saved.append({'name': f.name, 'path': path, 'size': len(content)})

        return Response({
            'order_id': order.id,
            'attachments': saved,
            'count': len(saved),
        })


class EmailThreadViewSet(viewsets.ModelViewSet):
    queryset = EmailThread.objects.all()
    serializer_class = EmailThreadSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = EmailThread.objects.all()
        user_param = self.request.query_params.get('user_id')
        if user_param:
            qs = qs.filter(user_id=user_param)
        return qs

    @action(detail=True, methods=['post'])
    def categorize(self, request, pk=None):
        thread = self.get_object()
        messages = thread.messages.order_by('received_at')
        if not messages.exists():
            return Response({'error': 'No messages in thread'}, status=400)

        from rfq.ai_classifier import AiEmailClassifier, ClassificationUnavailable

        try:
            classifier = AiEmailClassifier()
        except Exception as exc:
            logger.warning('AI provider unavailable: %s', exc)
            classifier = None

        PRIORITY = {'po': 4, 'quotation': 3, 'rfq': 2, 'other': 1}
        best_category = 'other'
        best_priority = 0

        for msg in messages:
            email_data = {
                'id': msg.message_id,
                'subject': msg.subject,
                'sender_name': msg.sender_name,
                'sender_email': msg.sender_email,
                'received_at': str(msg.received_at),
                'body': msg.body or msg.body_preview or '',
                'body_preview': msg.body_preview or '',
                'has_attachments': msg.has_attachments,
                'conversation_id': thread.conversation_id,
            }

            if classifier is not None:
                try:
                    category = classifier.classify(email_data)
                except ClassificationUnavailable:
                    category = 'other'
                except Exception as exc:
                    logger.warning('Classification failed for message %s: %s', msg.message_id, exc)
                    category = 'other'
            else:
                category = 'other'

            msg.category = category
            msg.save(update_fields=['category'])

            cat_priority = PRIORITY.get(category, 0)
            if cat_priority > best_priority:
                best_priority = cat_priority
                best_category = category

        thread.category = best_category
        thread.stage = 'categorized'
        thread.save(update_fields=['category', 'stage', 'updated_at'])

        # Find or create the linked Order
        existing_order = Order.objects.filter(email_thread=thread).first()
        if existing_order:
            rfq_order = existing_order
        else:
            latest_msg = messages.last()
            sender_name = latest_msg.sender_name if latest_msg else ''
            sender_email = latest_msg.sender_email if latest_msg else ''
            company = sender_name or (sender_email.split('@')[0] if sender_email else 'Unknown')

            from rfq.rfq_builder import RfqBuilder
            builder = RfqBuilder()

            if best_category == 'rfq':

                rfq_msg = None
                for msg in messages:
                    if msg.category == 'rfq':
                        rfq_msg = msg
                        break
                if not rfq_msg:
                    rfq_msg = messages.first()

                rfq_order = builder.create_from_email(
                    subject=rfq_msg.subject or thread.subject or '',
                    sender_email=rfq_msg.sender_email,
                    sender_name=rfq_msg.sender_name,
                    received_at=str(rfq_msg.received_at) if rfq_msg.received_at else '',
                    body=rfq_msg.body or rfq_msg.body_preview or '',
                    source='email',
                )
            else:
                from rfq.utils import generate_rfq_number
                order_type = best_category if best_category in ('rfq', 'purchase_order') else 'rfq'
                rfq_order = Order.objects.create(
                    rfq_number=generate_rfq_number(),
                    company_name=company,
                    type=order_type,
                    source='email',
                    email_thread=thread,
                )

            rfq_order.email_thread = thread
            rfq_order.company_name = company
            rfq_order.save(update_fields=['email_thread', 'company_name'])

            # Create AI metadata
            OrderAiMetadata.objects.get_or_create(
                order=rfq_order,
                defaults={'processed': False, 'classification': best_category},
            )

            # Auto-create or link contact
            if sender_email:
                from contacts.models import Contact
                contact, _ = Contact.objects.get_or_create(
                    email=sender_email,
                    defaults={
                        'company_name': company,
                        'contact_person': sender_name,
                        'type': 'client',
                    },
                )
                rfq_order.contact = contact
                rfq_order.save(update_fields=['contact'])

            # Extract items from ALL messages + attachments
            from rfq.data_extractors import OpenAiExtractor
            extractor = OpenAiExtractor()

            all_text = '\n\n---\n\n'.join(
                f"Subject: {msg.subject}\nFrom: {msg.sender_name} <{msg.sender_email}>\n\n{msg.body or msg.body_preview or ''}"
                for msg in messages
            )

            # Log attachment status for each message
            msgs_with_att = [m for m in messages if m.has_attachments]
            msgs_without_att = [m for m in messages if not m.has_attachments]
            logger.info(
                'Categorize thread %s: %d messages total, %d with has_attachments=True, %d without',
                thread.conversation_id[-16:], len(messages), len(msgs_with_att), len(msgs_without_att)
            )
            for m in msgs_with_att:
                logger.info(
                    '  Message %s (subject=%s) has_attachments=True',
                    m.message_id, m.subject[:80] if m.subject else '<no subject>'
                )
            for m in msgs_without_att:
                logger.debug(
                    '  Message %s (subject=%s) has_attachments=False',
                    m.message_id, m.subject[:80] if m.subject else '<no subject>'
                )

            images = []
            doc_texts = []
            try:
                from microsoft_auth.graph_api import GraphEmailProvider
                token = thread.user.microsoft_token if thread.user else request.user.microsoft_token
                token.refresh_if_expired()
                provider = GraphEmailProvider(
                    access_token=token.access_token,
                    refresh_token=token.refresh_token,
                )
                logger.info('Graph provider initialized successfully for attachment download')

                for msg in messages:
                    if not msg.has_attachments:
                        continue
                    try:
                        atts = provider.get_attachments_with_content(msg.message_id)
                        logger.info(
                            'Message %s: downloaded %d attachments from Graph API',
                            msg.message_id, len(atts)
                        )
                        for att in atts:
                            content_len = len(att.get('content', b'')) if att.get('content') else 0
                            logger.info(
                                '  Attachment: name=%s, is_image=%s, is_document=%s, content_bytes=%d, media_type=%s',
                                att.get('name'), att.get('is_image'), att.get('is_document'),
                                content_len, att.get('media_type')
                            )
                            if att.get('is_image') and att.get('content'):
                                images.append({
                                    'data': att['content'],
                                    'media_type': att.get('media_type', 'image/png'),
                                    'name': att.get('name', 'attachment'),
                                })
                            elif att.get('is_document') and att.get('content'):
                                from rfq.document_parsers import extract_text
                                import tempfile
                                with tempfile.NamedTemporaryFile(suffix=att.get('name', ''), delete=False) as tmp:
                                    tmp.write(att['content'])
                                    tmp_path = tmp.name
                                try:
                                    doc_text = extract_text(tmp_path)
                                    if doc_text:
                                        doc_texts.append(f"Attachment: {att.get('name')}\n{doc_text}")
                                        logger.info('  Extracted %d chars from document %s', len(doc_text), att.get('name'))
                                    else:
                                        logger.warning('  Document %s returned empty text', att.get('name'))
                                except Exception as doc_exc:
                                    logger.warning('  Failed to extract text from %s: %s', att.get('name'), doc_exc)
                                finally:
                                    import os
                                    os.unlink(tmp_path)
                            elif not att.get('content'):
                                logger.warning('  Attachment %s downloaded but content is empty', att.get('name'))
                    except Exception as exc:
                        logger.warning('Failed to fetch attachments for message %s: %s', msg.message_id, exc)

            except Exception as exc:
                logger.warning('Failed to init Graph provider for attachments: %s', exc, exc_info=True)

            # For manual deals, also gather locally uploaded attachments
            if rfq_order.source == 'manual':
                import os as _os
                from pathlib import Path as _Path
                att_dir = Path(settings.MEDIA_ROOT) / 'temp_attachments' / str(rfq_order.id)
                if att_dir.exists():
                    logger.info('Manual deal %s: scanning local attachments at %s', rfq_order.id, att_dir)
                    for att_file in att_dir.iterdir():
                        if att_file.is_dir():
                            continue
                        att_name = att_file.name
                        content = att_file.read_bytes()
                        if not content:
                            logger.warning('  Local attachment %s is empty, skipping', att_name)
                            continue
                        ext = att_file.suffix.lower()
                        is_image = ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp')
                        is_document = ext in ('.pdf', '.docx', '.doc', '.xlsx', '.xls', '.csv', '.txt')
                        if is_image:
                            import imghdr
                            media_type = imghdr.what(None, h=content) or 'image/png'
                            images.append({
                                'data': content,
                                'media_type': f'image/{media_type}',
                                'name': att_name,
                            })
                            logger.info('  Local image attachment %s (%d bytes)', att_name, len(content))
                        elif is_document:
                            try:
                                from rfq.document_parsers import extract_text
                                import tempfile
                                with tempfile.NamedTemporaryFile(suffix=att_name, delete=False) as tmp:
                                    tmp.write(content)
                                    tmp_path = tmp.name
                                try:
                                    doc_text = extract_text(tmp_path)
                                    if doc_text:
                                        doc_texts.append(f"Attachment: {att_name}\n{doc_text}")
                                        logger.info('  Extracted %d chars from local document %s', len(doc_text), att_name)
                                    else:
                                        logger.warning('  Local document %s returned empty text', att_name)
                                except Exception as doc_exc:
                                    logger.warning('  Failed to extract text from local %s: %s', att_name, doc_exc)
                                finally:
                                    _os.unlink(tmp_path)
                            except Exception as exc:
                                logger.warning('  Failed to process local attachment %s: %s', att_name, exc)
                        else:
                            logger.info('  Skipping unsupported local attachment %s (ext=%s)', att_name, ext)
                    logger.info('Local attachment gathering complete: %d images, %d doc texts', len(images), len(doc_texts))

            logger.info(
                'Attachment gathering complete: %d images (raw), %d doc texts, all_text length=%d',
                len(images), len(doc_texts), len(all_text)
            )

            # Deduplicate images by content hash
            import hashlib
            seen_hashes = set()
            unique_images = []
            for img in images:
                h = hashlib.md5(img['data']).hexdigest()
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    unique_images.append(img)
                else:
                    logger.info('Dedup: skipping duplicate image %s (hash=%s)', img['name'], h)
            if len(images) != len(unique_images):
                logger.info('Dedup: %d images -> %d unique', len(images), len(unique_images))
            images = unique_images

            if doc_texts:
                all_text += '\n\n--- Attachment Text ---\n\n' + '\n\n'.join(doc_texts)

            try:
                extracted = extractor.extract(
                    text=all_text,
                    source_label=f'thread-{thread.conversation_id[:16]}',
                    is_quotation=False,
                    images=images or None,
                    order_id=rfq_order.id,
                )
                logger.info(
                    'AI extraction returned: extracted=%s, images_sent=%d',
                    bool(extracted), len(images)
                )
                if extracted:
                    builder.update_from_extraction(rfq_order, extracted)
                    # Update AI metadata
                    ai_meta, _ = OrderAiMetadata.objects.get_or_create(order=rfq_order)
                    ai_meta.processed = True
                    ai_meta.classification = best_category
                    ai_meta.save(update_fields=['processed', 'classification', 'updated_at'])
                    logger.info('Extracted %d items for RFQ %s', len(extracted.get('items', [])), rfq_order.rfq_number)
            except Exception as exc:
                logger.warning('Item extraction failed for thread %s: %s', pk, exc)

        # Create contacts from thread senders (skip internal @corimetal.it)
        from contacts.models import Contact
        from rfq.business_central import build_bc_client_for_user, BusinessCentralClient, CUSTOMER_NAME_SUFFIX
        seen_emails = set()
        contacts_created = 0
        bc_customers_created = 0

        # Build BC client once (if available)
        bc_client = None
        bc_company_id = None
        try:
            bc_client = build_bc_client_for_user(thread.user or request.user)
            if bc_client:
                bc_company_id = bc_client.get_company_by_name(settings.BC_COMPANY_NAME)
                if not bc_company_id:
                    logger.warning('BC company "%s" not found, skipping BC customer creation', settings.BC_COMPANY_NAME)
                    bc_client = None
        except Exception as exc:
            logger.warning('Failed to init BC client for contact creation: %s', exc)

        for msg in messages:
            sender_email = (msg.sender_email or '').strip().lower()
            sender_name = (msg.sender_name or '').strip()
            if not sender_email or sender_email in seen_emails:
                continue
            seen_emails.add(sender_email)
            if sender_email.endswith('@corimetal.it'):
                continue

            contact_name = sender_name or sender_email.split('@')[0]

            # Create local contact
            contact, created = Contact.objects.get_or_create(
                email=sender_email,
                defaults={
                    'company_name': contact_name,
                    'contact_person': sender_name,
                },
            )
            if created:
                contacts_created += 1
                logger.info('Created contact: %s <%s>', sender_name, sender_email)

            # Create customer in BC
            if bc_client and bc_company_id:
                try:
                    bc_result = bc_client.create_customer(
                        company_id=bc_company_id,
                        customer_name=f'{contact_name}{CUSTOMER_NAME_SUFFIX}',
                        email=sender_email,
                    )
                    if bc_result:
                        bc_customers_created += 1
                        logger.info('Created BC customer: %s', contact_name)
                except Exception as exc:
                    logger.warning('Failed to create BC customer for %s: %s', contact_name, exc)

        if contacts_created:
            logger.info('Created %d new contacts from thread %s', contacts_created, thread.conversation_id[-16:])
        if bc_customers_created:
            logger.info('Created %d new BC customers from thread %s', bc_customers_created, thread.conversation_id[-16:])

        return Response({
            'id': thread.id,
            'conversation_id': thread.conversation_id,
            'category': best_category,
            'order_id': rfq_order.id,
            'contacts_created': contacts_created,
            'bc_customers_created': bc_customers_created,
        })
