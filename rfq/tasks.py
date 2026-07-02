import logging
import os

from celery import shared_task, group
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from rfq.email_ingestion_service import EmailIngestionService
from rfq.business_central import create_quotation_in_bc

User = get_user_model()
logger = logging.getLogger(__name__)


@shared_task(
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def monitor_emails_for_rfqs():
    """
    Main entry point (invoked by Celery Beat).
    Fans out per-user subtasks for parallel processing.
    """
    logger.info('Starting email monitoring for RFQs')

    users_with_tokens = User.objects.filter(
        microsoft_token__isnull=False,
    ).distinct()

    if not users_with_tokens:
        logger.info('No users with Microsoft tokens found')
        return 0

    task_group = group(
        process_user_emails.s(user.id) for user in users_with_tokens
    )
    result = task_group.apply_async()
    logger.info('Fanned out %d per-user tasks', len(users_with_tokens))
    return len(users_with_tokens)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def process_user_emails(self, user_id):
    """
    Process emails for a single user.
    Uses a Redis lock to prevent overlapping runs.
    """
    from django.core.cache import cache

    lock_key = f'email_monitor_lock:{user_id}'
    if not cache.add(lock_key, '1', timeout=600):
        logger.info('Lock held for user %s, skipping', user_id)
        return 0

    try:
        user = User.objects.get(id=user_id)
        if not user.microsoft_token:
            logger.warning('User %s no longer has a Microsoft token', user_id)
            return 0

        # Force-refresh the token before using it — access tokens
        # can be invalidated server-side even within their expiry window.
        user.microsoft_token.refresh_if_expired(force=True)

        service = EmailIngestionService(user)
        result = service.check_and_process_new_emails(days_back=1)

        if result['success']:
            logger.info(
                'Processed %d RFQ emails for user %s',
                result['processed'], user.username,
            )
            for error in result.get('errors', []):
                logger.error('  - %s', error)
            return result['processed']
        else:
            logger.error(
                'Email processing failed for user %s', user.username,
            )
            return 0
    except User.DoesNotExist:
        logger.error('User %s not found', user_id)
        return 0
    except Exception as exc:
        logger.exception('Error processing user %s', user_id)
        raise self.retry(exc=exc)
    finally:
        cache.delete(lock_key)


@shared_task(
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=120,
)
def process_rfq_with_ai(order_id):
    logger.info('Starting AI processing for order %d', order_id)

    from rfq.models import Order, OrderItem
    from rfq.ai_processor import AIProcessor

    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        logger.error('Order %d not found', order_id)
        return False

    if not order.attachment_path:
        logger.warning('No attachment for order %d', order_id)
        return False

    file_type = order.attachment_path.split('.')[-1].upper()
    processor = AIProcessor()
    result = processor.process_attachment(order.attachment_path, file_type)

    if not result['success']:
        order.ai_processed = False
        order.processing_errors = result.get('errors', 'AI processing failed')
        order.save(update_fields=['ai_processed', 'processing_errors'])
        logger.error('AI processing failed for order %d', order_id)
        return False

    data = result['data']
    order.company_name = data.get('company_name', order.company_name)
    order.items_description = data.get('description') or data.get('items_description') or order.items_description
    order.quantity = data.get('quantity', order.quantity)
    order.specifications = data.get('specifications', order.specifications)
    order.delivery_date = data.get('delivery_date', order.delivery_date)
    order.budget = data.get('budget', order.budget)
    order.ai_processed = True
    order.ai_confidence_score = result['confidence_score']
    order.processing_errors = ''
    order.save()

    for item_data in data.get('items', []):
        OrderItem.objects.create(
            order=order,
            item_name=item_data.get('name') or item_data.get('description') or item_data.get('item_name', 'Unknown Item'),
            item_code=item_data.get('item_code') or item_data.get('part_number', ''),
            description=item_data.get('description') or item_data.get('name', ''),
            quantity=item_data.get('quantity', 1),
            unit=item_data.get('unit', 'pcs'),
            unit_price=item_data.get('unit_price'),
            total_price=item_data.get('total_price'),
            extraction_confidence=item_data.get('confidence_score', 0.7),
        )

    logger.info('AI processing complete for order %d', order_id)

    # Chain: after AI, attempt supplier dispatch
    dispatch_to_supplier.delay(order_id)

    return True


@shared_task(
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def dispatch_to_supplier(order_id, supplier_id=None):
    """
    Dispatch the order to its supplier via email.
    If no supplier is configured, the order stays at 'inquiry' stage
    and a notification is created to add a supplier.
    
    Args:
        order_id: The ID of the order to dispatch
        supplier_id: Optional specific supplier ID to dispatch to (for manual selection)
    """
    logger.info('Starting supplier dispatch for order %d', order_id)

    from rfq.models import Order, OrderSupplierAssignment

    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        logger.error('Order %d not found for dispatch', order_id)
        return False

    # If supplier_id is provided, use that specific supplier
    if supplier_id:
        try:
            from contacts.models import Contact
            supplier = Contact.objects.get(id=supplier_id, type='supplier')
        except Contact.DoesNotExist:
            logger.error('Supplier %d not found', supplier_id)
            return False
    else:
        # Otherwise, use the primary supplier or check for assigned suppliers
        supplier = order.supplier
        if not supplier:
            # Check if there are any suppliers assigned via the ManyToMany field
            assigned_suppliers = order.suppliers.filter(type='supplier')
            if assigned_suppliers.exists():
                supplier = assigned_suppliers.first()
                logger.info('Using first assigned supplier: %s', supplier.company_name)

    if not supplier:
        logger.info(
            'Order %d has no supplier attached, creating notification to add supplier',
            order_id,
        )
        order.stage = 'inquiry'
        order.notes = 'No supplier assigned. Please add a supplier to dispatch this RFQ.'
        order.save(update_fields=['stage', 'notes'])
        
        # Create a task/notification for adding supplier
        create_add_supplier_task(order)
        return False

    # Check if this supplier has already been sent an email
    existing_assignment = OrderSupplierAssignment.objects.filter(
        order=order, supplier=supplier
    ).first()
    
    if existing_assignment and existing_assignment.email_sent:
        logger.info(
            'Order %d already sent to supplier %s',
            order_id, supplier.company_name
        )
        return True

    from rfq.email_service import SupplierEmailService
    from microsoft_auth.graph_api import GraphEmailProvider

    # Use the order's reviewer token, or fall back to any available token
    user = order.reviewed_by
    if not user or not hasattr(user, 'microsoft_token') or not user.microsoft_token:
        users_with_tokens = User.objects.filter(
            microsoft_token__isnull=False,
        ).distinct().first()
        if not users_with_tokens:
            logger.error('No user with Microsoft token available for dispatch')
            order.supplier_email_error = 'No available email provider'
            order.save(update_fields=['supplier_email_error'])
            return False
        user = users_with_tokens

    try:
        token = user.microsoft_token
        token.refresh_if_expired()
        provider = GraphEmailProvider(
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            token_expires_at=token.token_expires_at,
            user=user,
        )
    except Exception as exc:
        logger.error('Failed to build email provider: %s', exc)
        order.supplier_email_error = str(exc)
        order.save(update_fields=['supplier_email_error'])
        return False

    email_service = SupplierEmailService(email_provider=provider)
    result = email_service.send_rfq_to_supplier(order)

    if result['success']:
        logger.info('Supplier dispatch complete for order %d to supplier %s', order_id, supplier.company_name)
        
        # Update or create the supplier assignment record
        assignment, created = OrderSupplierAssignment.objects.update_or_create(
            order=order,
            supplier=supplier,
            defaults={
                'email_sent': True,
                'email_sent_at': timezone.now(),
                'assigned_by': user,
            }
        )
        
        # Update the order's primary supplier if not set
        if not order.supplier:
            order.supplier = supplier
            order.save(update_fields=['supplier'])
        
        return True

    logger.error('Supplier dispatch failed for order %d: %s', order_id, result['message'])
    
    # Update assignment with error
    if existing_assignment:
        existing_assignment.email_error = result['message']
        existing_assignment.save(update_fields=['email_error'])
    else:
        OrderSupplierAssignment.objects.create(
            order=order,
            supplier=supplier,
            email_error=result['message'],
            assigned_by=user,
        )
    
    return False


def create_add_supplier_task(order):
    """
    Create a task/notification for adding a supplier to an order.
    """
    from tasks.models import Task
    
    task_title = f"Add supplier for RFQ {order.rfq_number}"
    task_description = (
        f"Order from {order.company_name} needs a supplier to be assigned. "
        f"RFQ Number: {order.rfq_number}, "
        f"Items: {order.items_description or 'Not specified'}"
    )
    
    Task.objects.create(
        title=task_title,
        description=task_description,
        status='pending',
        order=order,
    )
    
    logger.info('Created task to add supplier for order %d', order.id)


@shared_task(
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=120,
    queue='email_polling',
)
def sync_with_business_central(order_id):
    from rfq.models import Order
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        logger.error('Order %d not found for BC sync', order_id)
        return False

    result = create_quotation_in_bc(order)
    if result:
        order.status = 'processing'
        order.save(update_fields=['status'])
        return True

    logger.error('BC sync failed for order %d', order_id)
    return False


@shared_task(
    autoretry_for=(OSError,),
    max_retries=2,
    default_retry_delay=60,
)
def cleanup_old_attachments(days=30):
    logger.info('Starting cleanup of attachments older than %d days', days)

    from rfq.models import Order, OrderAttachment
    from django.conf import settings

    cutoff = timezone.now() - timedelta(days=days)
    old_orders = Order.objects.filter(
        status='completed',
        updated_at__lt=cutoff,
    )

    deleted = 0
    for order in old_orders:
        for attachment in order.attachments.all():
            try:
                if os.path.exists(attachment.file_path):
                    os.remove(attachment.file_path)
                    deleted += 1
            except OSError as exc:
                logger.error('Failed to delete %s: %s', attachment.file_path, exc)
            attachment.delete()

        order.attachment_filename = ''
        order.attachment_path = ''
        order.attachment_size = None
        order.save(update_fields=[
            'attachment_filename', 'attachment_path', 'attachment_size',
        ])

    logger.info('Cleanup complete. Deleted %d attachment files', deleted)
    return deleted
