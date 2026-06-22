from django.contrib import admin
from contacts.models import Contact


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'type', 'email', 'contact_person']
    list_filter = ['type']
    search_fields = ['company_name', 'email', 'contact_person']
