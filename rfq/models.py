from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Order(models.Model):
    TYPE_CHOICES = [
        ('rfq', 'RFQ'),
        ('purchase_order', 'Purchase Order'),
    ]

    STAGE_CHOICES = [
        ('inquiry', 'Inquiry'),
        ('quotation', 'Quotation'),
        ('negotiation', 'Negotiation'),
        ('order', 'Order'),
        ('fulfilled', 'Fulfilled'),
        ('archived', 'Archived'),
    ]

    EMAIL_CLASSIFICATION_CHOICES = [
        ('rfq_po', 'RFQ / PO'),
        ('quotation', 'Quotation'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    SOURCE_CHOICES = [
        ('email', 'Email'),
        ('manual', 'Manual'),
        ('test', 'Test'),
    ]

    # Pipeline tracking
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='rfq')
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default='inquiry')

    # Contact relationships
    contact = models.ForeignKey(
        'contacts.Contact',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
        help_text='Client who sent the RFQ / placed the order',
    )
    supplier = models.ForeignKey(
        'contacts.Contact',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='supplied_orders',
        help_text='Supplier assigned to fulfill this order',
    )

    # Email source information
    email_subject = models.CharField(max_length=500)
    email_sender = models.EmailField()
    email_received_at = models.DateTimeField()
    email_body = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='email', help_text="Source of order (email, manual, test)")
    email_message_id = models.CharField(max_length=500, blank=True, db_index=True, help_text="Unique message ID from email provider for deduplication")
    email_classification = models.CharField(max_length=20, choices=EMAIL_CLASSIFICATION_CHOICES, default='other', help_text="AI-classified email type: RFQ/PO, Quotation, or Other")

    # Order details
    rfq_number = models.CharField(max_length=100, unique=True)
    company_name = models.CharField(max_length=200)
    supplier_email = models.EmailField(blank=True, null=True, help_text="Supplier email address for sending RFQ")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    probability = models.IntegerField(default=0, help_text="Win probability percentage (0-100)")

    # Extracted data from AI processing
    items_description = models.TextField(blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    specifications = models.TextField(blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Attachment information
    attachment_filename = models.CharField(max_length=255, blank=True)
    attachment_path = models.CharField(max_length=500, blank=True)
    attachment_size = models.IntegerField(null=True, blank=True)

    # Processing metadata
    ai_processed = models.BooleanField(default=False)
    ai_confidence_score = models.FloatField(null=True, blank=True)
    processing_errors = models.TextField(blank=True)

    # Supplier email tracking
    supplier_email_sent = models.BooleanField(default=False)
    supplier_email_sent_at = models.DateTimeField(null=True, blank=True)
    supplier_email_error = models.TextField(blank=True)

    # Business Central integration
    bc_quote_id = models.CharField(max_length=255, blank=True, help_text="Business Central sales quote ID")
    bc_synced = models.BooleanField(default=False, help_text="Whether order has been synced to BC")
    bc_synced_at = models.DateTimeField(null=True, blank=True)

    # Review and approval
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_orders')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rfq_rfq'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['stage']),
            models.Index(fields=['priority']),
            models.Index(fields=['type']),
            models.Index(fields=['email_received_at']),
            models.Index(fields=['rfq_number']),
            models.Index(fields=['email_sender']),
            models.Index(fields=['company_name']),
        ]

    def __str__(self):
        return f"{self.rfq_number} - {self.company_name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')

    item_name = models.CharField(max_length=200)
    item_code = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    quantity = models.IntegerField()
    unit = models.CharField(max_length=50, blank=True)
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


class OrderAttachment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='attachments')

    filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    file_size = models.IntegerField()
    file_type = models.CharField(max_length=100)
    mime_type = models.CharField(max_length=100, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rfq_rfqattachment'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.filename}"


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


class Product(models.Model):
    bc_product_id = models.CharField(max_length=255, unique=True, help_text="Business Central item ID")
    number = models.CharField(max_length=100, blank=True, help_text="Item number / SKU")
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


# ---------------------------------------------------------------------------
# Backward-compatible aliases (remove after full migration)
# ---------------------------------------------------------------------------
RFQ = Order
RFQItem = OrderItem
RFQAttachment = OrderAttachment
RFQAnalytics = OrderAnalytics



