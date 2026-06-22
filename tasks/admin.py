from django.contrib import admin
from tasks.models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'order', 'assigned_to', 'created_at', 'completed_at']
    list_filter = ['status', 'created_at']
    search_fields = ['title', 'order__rfq_number']
    readonly_fields = ['created_at', 'completed_at']
