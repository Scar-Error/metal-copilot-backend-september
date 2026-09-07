from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Order(models.Model):
    """Business transaction: RFQ, PO, or Quotation.

    Linked to an EmailThread when created from email. Stage lives on the thread.
    """

    TYPE_CHOICES = [
        ('rfq', 'RFQ'),
        ('purchase_order', 'Purchase Order'),
    ]

    SOURCE_CHOICES = [
        ('email', 'Email'),
        ('manual', 'Manual'),
        ('test', 'Test'),
    ]

    # Contact relationships
    contact = models.ForeignKey(
        'contacts.Contact',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
    )

    # Order details
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='rfq')
    rfq_number = models.CharField(max_length=100, unique=True)
    po_number = models.CharField(max_length=100, blank=True, null=True)
    company_name = models.CharField(max_length=200)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='email')

    # Extracted data
    items_description = models.TextField(blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    specifications = models.TextField(blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Review
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_orders')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Linked email thread (single direction)
    email_thread = models.ForeignKey(
        'EmailThread',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rfq_rfq'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['type']),
            models.Index(fields=['rfq_number']),
            models.Index(fields=['company_name']),
        ]

    def __str__(self):
        return f"{self.rfq_number} - {self.company_name}"


class OrderAiMetadata(models.Model):
    """AI processing data for an Order. 1:1 relationship."""

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name='ai_metadata',
    )
    processed = models.BooleanField(default=False)
    confidence_score = models.FloatField(null=True, blank=True)
    processing_errors = models.TextField(blank=True)
    classification = models.CharField(max_length=20, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rfq_orderaimetadata'

    def __str__(self):
        return f"AI for {self.order.rfq_number}"


class OrderBusinessCentral(models.Model):
    """Business Central integration data for an Order. 1:1 relationship."""

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name='bc_data',
    )
    quote_id = models.CharField(max_length=255, blank=True)
    sales_order_id = models.CharField(max_length=255, blank=True, null=True)
    sales_order_number = models.CharField(max_length=255, blank=True, null=True)
    synced = models.BooleanField(default=False)
    synced_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rfq_orderbusinesscentral'

    def __str__(self):
        return f"BC for {self.order.rfq_number}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')

    item_name = models.CharField(max_length=200)
    item_code = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True)
    quantity = models.IntegerField()
    unit = models.CharField(max_length=50, blank=True, null=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    extraction_confidence = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rfq_rfqitem'
        ordering = ['id']

    def __str__(self):
        return f"{self.item_name} (Qty: {self.quantity})"


class OrderAnalytics(models.Model):
    date = models.DateField(unique=True)
    total_orders_received = models.IntegerField(default=0)
    total_orders_processed = models.IntegerField(default=0)
    total_orders_completed = models.IntegerField(default=0)
    total_orders_rejected = models.IntegerField(default=0)

    avg_processing_time_hours = models.FloatField(null=True, blank=True)
    avg_ai_confidence_score = models.FloatField(null=True, blank=True)

    unique_companies = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rfq_rfqanalytics'
        ordering = ['-date']
        verbose_name_plural = 'Order Analytics'

    def __str__(self):
        return f"Analytics for {self.date}"


class AiUsageRecord(models.Model):
    USE_CHOICES = [
        ('classification', 'Classification'),
        ('image_details', 'Image details'),
        ('extraction', 'Extraction'),
        ('general', 'General'),
    ]

    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=100)
    use = models.CharField(max_length=30, choices=USE_CHOICES, default='general')

    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    image_count = models.IntegerField(default=0)

    input_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    output_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    order = models.ForeignKey(
        'Order',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='ai_usage_records',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rfq_aiusagerecord'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['provider', 'model']),
            models.Index(fields=['use']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.provider}/{self.model} {self.use} ${self.total_cost}'


class Product(models.Model):
    bc_product_id = models.CharField(max_length=255, unique=True)
    number = models.CharField(max_length=100, blank=True)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=50, blank=True)
    type = models.CharField(max_length=100, blank=True)
    blocked = models.BooleanField(default=False)
    synced_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rfq_product'
        ordering = ['display_name']
        verbose_name_plural = 'Products'

    def __str__(self):
        return f"{self.number} - {self.display_name}"


class EmailThread(models.Model):
    """Email conversation grouped by Microsoft Graph conversationId.

    Owns category, stage, and messages. Pipeline stage is the source of truth.
    """

    STAGE_CHOICES = [
        ('synced', 'Synced'),
        ('ai_analysis', 'AI Analysis'),
        ('categorized', 'Categorized'),
        ('inquiry', 'Inquiry'),
        ('quotation', 'Quotation'),
        ('negotiation', 'Negotiation'),
        ('order', 'Order'),
        ('fulfilled', 'Fulfilled'),
        ('archived', 'Archived'),
    ]

    conversation_id = models.CharField(max_length=500, unique=True, db_index=True)
    subject = models.CharField(max_length=500, blank=True)
    message_count = models.IntegerField(default=0)
    last_message_at = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='email_threads',
    )
    category = models.CharField(max_length=20, blank=True, default='')
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default='synced')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rfq_emailthread'
        ordering = ['-last_message_at']
        indexes = [
            models.Index(fields=['conversation_id']),
            models.Index(fields=['stage']),
        ]

    def __str__(self):
        return f"{self.subject[:80]} ({self.message_count} messages)"


class EmailMessage(models.Model):
    """A single email message within an EmailThread."""

    thread = models.ForeignKey(
        EmailThread,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    message_id = models.CharField(max_length=500, unique=True, db_index=True)
    subject = models.CharField(max_length=500, blank=True)
    sender_name = models.CharField(max_length=255, blank=True)
    sender_email = models.EmailField(blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    body = models.TextField(blank=True)
    body_preview = models.CharField(max_length=500, blank=True)
    has_attachments = models.BooleanField(default=False)
    category = models.CharField(max_length=20, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rfq_emailmessage'
        ordering = ['received_at']
        indexes = [
            models.Index(fields=['message_id']),
        ]

    def __str__(self):
        return f"{self.subject[:80]} from {self.sender_email}"


class ProcessedEmail(models.Model):
    """Debug snapshot of an email processed from Outlook."""

    EMAIL_CLASSIFICATION_CHOICES = [
        ('rfq', 'RFQ'),
        ('po', 'PO'),
        ('quotation', 'Quotation'),
        ('other', 'Other'),
    ]

    email_message_id = models.CharField(max_length=500, unique=True)
    conversation_id = models.CharField(max_length=500, blank=True, db_index=True)
    subject = models.CharField(max_length=500, blank=True)
    sender_name = models.CharField(max_length=255, blank=True)
    sender_email = models.EmailField(blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    body = models.TextField(blank=True)
    body_preview = models.CharField(max_length=500, blank=True)
    classification = models.CharField(max_length=20, choices=EMAIL_CLASSIFICATION_CHOICES, default='other')
    order = models.ForeignKey(
        'Order',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='processed_emails',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='processed_emails',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rfq_processedemail'
        ordering = ['-received_at', '-created_at']
        indexes = [
            models.Index(fields=['classification']),
            models.Index(fields=['conversation_id']),
        ]

    def __str__(self):
        return f"{self.get_classification_display()} - {self.subject[:80]}"


# Backward-compatible aliases
RFQ = Order
RFQItem = OrderItem
RFQAnalytics = OrderAnalytics
