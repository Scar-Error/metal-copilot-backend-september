from django.db import models


class Contact(models.Model):
    TYPE_CHOICES = [
        ('supplier', 'Supplier'),
        ('client', 'Client'),
    ]

    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='client')
    company_name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=200, blank=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=50, blank=True)
    tags = models.JSONField(default=list, blank=True)
    tax_id = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company_name']
        indexes = [
            models.Index(fields=['type']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f'{self.company_name} ({self.get_type_display()})'
