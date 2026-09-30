from rest_framework import serializers
from contacts.models import Contact


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            'id', 'type', 'company_name', 'contact_person',
            'email', 'phone', 'tags', 'tax_id', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_email(self, value):
        """One contact per address, however the address is capitalised.

        Contact.email is unique case-sensitively at the database level, so
        without this check a hand-added 'Luigi@RossiMax.it' would sit next to
        the 'luigi@rossimax.it' that was created from an email thread.
        """
        address = (value or '').strip()
        if not address:
            return value

        others = Contact.objects.filter(email__iexact=address)
        if self.instance is not None:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise serializers.ValidationError(
                'A contact with this email already exists.'
            )
        return value
