"""
Admin configuration for Authentication app.
Custom User model with UUID primary key.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


class CustomUserAdmin(UserAdmin):
    """
    Custom admin configuration for CustomUser model.
    """
    list_display = ('id', 'username', 'email', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_active', 'is_superuser')
    search_fields = ('username', 'email', 'id')
    ordering = ('username',)
    
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('id',)}),
    )
    
    readonly_fields = ('id',)


# Register the custom User model
admin.site.register(CustomUser, CustomUserAdmin)
