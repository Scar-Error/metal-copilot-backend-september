from django.contrib import admin
from .models import Order, OrderItem, OrderAnalytics, OrderAiMetadata, OrderBusinessCentral, Product, ProcessedEmail, EmailThread, EmailMessage


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['rfq_number', 'company_name', 'type', 'source', 'created_at']
    list_filter = ['type', 'source']
    search_fields = ['rfq_number', 'company_name', 'po_number']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(OrderAiMetadata)
class OrderAiMetadataAdmin(admin.ModelAdmin):
    list_display = ['order', 'processed', 'confidence_score', 'classification']
    list_filter = ['processed', 'classification']


@admin.register(OrderBusinessCentral)
class OrderBusinessCentralAdmin(admin.ModelAdmin):
    list_display = ['order', 'quote_id', 'synced', 'synced_at']
    list_filter = ['synced']


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['item_name', 'order', 'quantity', 'unit', 'unit_price']
    search_fields = ['item_name', 'item_code', 'order__rfq_number']


@admin.register(OrderAnalytics)
class OrderAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['date', 'total_orders_received', 'total_orders_processed', 'total_orders_completed']
    list_filter = ['date']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['number', 'display_name', 'unit_price', 'unit', 'blocked']
    list_filter = ['blocked', 'type']
    search_fields = ['number', 'display_name', 'description']


@admin.register(ProcessedEmail)
class ProcessedEmailAdmin(admin.ModelAdmin):
    list_display = [
        'email_message_id', 'classification', 'subject', 'sender_email',
        'received_at', 'order',
    ]
    list_filter = ['classification', 'received_at']
    search_fields = ['subject', 'sender_email', 'sender_name', 'email_message_id']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(EmailThread)
class EmailThreadAdmin(admin.ModelAdmin):
    list_display = ['conversation_id', 'subject', 'message_count', 'last_message_at', 'user']
    list_filter = ['last_message_at', 'user']
    search_fields = ['conversation_id', 'subject']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    list_display = ['message_id', 'subject', 'sender_email', 'received_at', 'thread', 'has_attachments']
    list_filter = ['received_at', 'has_attachments']
    search_fields = ['message_id', 'subject', 'sender_email', 'sender_name']
    readonly_fields = ['created_at']
