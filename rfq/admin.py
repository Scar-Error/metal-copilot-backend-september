from django.contrib import admin
from .models import Order, OrderItem, OrderAttachment, OrderAnalytics, Product


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['rfq_number', 'company_name', 'email_classification', 'type', 'stage', 'status', 'priority', 'email_received_at', 'ai_processed']
    list_filter = ['status', 'stage', 'type', 'priority', 'email_classification', 'ai_processed', 'email_received_at']
    search_fields = ['rfq_number', 'company_name', 'email_subject', 'email_sender']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'email_received_at'


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['item_name', 'order', 'quantity', 'unit', 'unit_price']
    list_filter = ['order__status']
    search_fields = ['item_name', 'item_code', 'order__rfq_number']


@admin.register(OrderAttachment)
class OrderAttachmentAdmin(admin.ModelAdmin):
    list_display = ['filename', 'order', 'file_type', 'file_size', 'uploaded_at']
    list_filter = ['file_type', 'uploaded_at']
    search_fields = ['filename', 'order__rfq_number']


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
