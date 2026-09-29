from rest_framework import serializers
from rfq.models import (
    Order, OrderItem, OrderAnalytics, OrderAiMetadata, OrderBusinessCentral,
    EmailThread, EmailMessage,
)

ALLOWED_UNITS = ('pc', 'pcs', 'kg', 'ltr')
ITEM_FIELD_MAX_LEN = 99


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = [
            'id', 'order', 'item_name', 'item_code', 'description',
            'quantity', 'unit', 'unit_price', 'total_price',
            'extraction_confidence', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'extraction_confidence']
        extra_kwargs = {
            'item_name': {'max_length': ITEM_FIELD_MAX_LEN},
            'item_code': {'max_length': ITEM_FIELD_MAX_LEN},
        }

    def validate_unit(self, value):
        if value is None or value == '':
            return value
        normalized = str(value).strip().lower()
        if normalized not in ALLOWED_UNITS:
            raise serializers.ValidationError(
                f'Unit must be one of: {", ".join(ALLOWED_UNITS)}'
            )
        return normalized

    def validate_quantity(self, value):
        if value < 0:
            raise serializers.ValidationError('Quantity must be non-negative')
        return value

    def validate(self, attrs):
        unit_price = attrs.get('unit_price')
        total_price = attrs.get('total_price')
        quantity = attrs.get('quantity', 0)
        if unit_price is not None and total_price is not None and quantity:
            expected = round(unit_price * quantity, 2)
            if abs(total_price - expected) > 0.01:
                raise serializers.ValidationError(
                    f'Total price {total_price} does not match '
                    f'unit_price × quantity ({unit_price} × {quantity} = {expected})'
                )
        return attrs


class OrderAiMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderAiMetadata
        fields = ['processed', 'confidence_score', 'processing_errors', 'classification']


class OrderBusinessCentralSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderBusinessCentral
        fields = ['quote_id', 'sales_order_id', 'sales_order_number', 'synced', 'synced_at']


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    ai_metadata = OrderAiMetadataSerializer(read_only=True)
    bc_data = OrderBusinessCentralSerializer(read_only=True)
    reviewed_by_username = serializers.CharField(
        source='reviewed_by.username', read_only=True,
    )
    contact_name = serializers.CharField(
        source='contact.company_name', read_only=True, default=None,
    )

    class Meta:
        model = Order
        fields = [
            'id', 'type', 'rfq_number', 'company_name',
            'contact', 'contact_name',
            'source', 'po_number',
            'items_description', 'quantity', 'specifications',
            'delivery_date', 'budget',
            'ai_metadata', 'bc_data',
            'reviewed_by', 'reviewed_by_username', 'reviewed_at', 'notes',
            'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'rfq_number', 'po_number',
            'reviewed_by', 'reviewed_at', 'created_at', 'updated_at',
        ]


class OrderListSerializer(serializers.ModelSerializer):
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'type', 'rfq_number', 'company_name',
            'source', 'items_count',
        ]

    def get_items_count(self, obj):
        return obj.items.count()


class OrderAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderAnalytics
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class DealSerializer(serializers.ModelSerializer):
    number = serializers.CharField(source='rfq_number', required=False)
    company = serializers.CharField(source='company_name', required=False)
    value = serializers.DecimalField(source='budget', max_digits=12, decimal_places=2, allow_null=True, required=False)
    expected_date = serializers.DateField(source='delivery_date', allow_null=True, required=False)
    contact_person = serializers.SerializerMethodField()
    is_manual = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'number', 'type', 'source',
            'company', 'contact_person', 'value',
            'expected_date', 'notes', 'is_manual',
        ]
        extra_kwargs = {
            'type': {'required': False},
            'notes': {'required': False},
            'source': {'required': False},
        }

    def get_contact_person(self, obj):
        if obj.contact:
            return obj.contact.contact_person or obj.contact.company_name
        return ''

    def get_is_manual(self, obj):
        return obj.source == 'manual'

    def create(self, validated_data):
        if not validated_data.get('rfq_number'):
            from rfq.utils import generate_rfq_number
            validated_data['rfq_number'] = generate_rfq_number()
        if not validated_data.get('source'):
            validated_data['source'] = 'manual'
        return super().create(validated_data)


class EmailMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailMessage
        fields = [
            'id', 'message_id', 'subject', 'sender_name', 'sender_email',
            'received_at', 'body', 'body_preview', 'has_attachments', 'category', 'created_at',
        ]
        read_only_fields = fields


class EmailMessageTagSerializer(serializers.ModelSerializer):
    """Per-message tag for the board, without the body.

    `EmailMessageSerializer` is right for the thread detail view but wrong for the
    board: `body` is a large HTML blob, and there can be hundreds of messages
    across the threads on screen. The tag itself is a few bytes, so the board can
    afford to carry every message's category and still stay small.
    """

    class Meta:
        model = EmailMessage
        fields = [
            'id', 'message_id', 'subject', 'sender_name', 'sender_email',
            'received_at', 'has_attachments', 'category',
        ]
        read_only_fields = fields


class DealDetailSerializer(serializers.ModelSerializer):
    number = serializers.CharField(source='rfq_number')
    company = serializers.CharField(source='company_name')
    value = serializers.DecimalField(source='budget', max_digits=12, decimal_places=2, allow_null=True)
    expected_date = serializers.DateField(source='delivery_date', allow_null=True)
    contact_person = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'number', 'type',
            'company', 'contact_person', 'value',
            'expected_date', 'notes', 'items_description',
            'specifications', 'created_at', 'updated_at',
        ]

    def get_contact_person(self, obj):
        if obj.contact:
            return obj.contact.contact_person or obj.contact.company_name
        return ''


class RfqDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'rfq_number', 'company_name',
            'items_description', 'quantity', 'specifications', 'delivery_date',
            'items', 'created_at', 'updated_at',
        ]


class EmailThreadListSerializer(serializers.ModelSerializer):
    """Lightweight payload for the Kanban board list request.

    Carries `messages` as tags only (see EmailMessageTagSerializer), so a card
    can show what kind of email each individual message in the thread is. The
    bodies are omitted because they are large HTML blobs and there can be
    hundreds of messages across the threads on screen; the full message data
    comes from the detail request (EmailThreadDetailSerializer) when the user
    opens a thread.

    `last_sender_name` / `last_sender_email` are annotated onto the queryset by
    EmailThreadViewSet, so the card can show who sent the most recent message
    without pulling every message body (and without an N+1 query per thread).
    """

    orders = RfqDetailSerializer(many=True, read_only=True)
    messages = EmailMessageTagSerializer(many=True, read_only=True)
    last_sender_name = serializers.CharField(read_only=True, allow_null=True, required=False)
    last_sender_email = serializers.CharField(read_only=True, allow_null=True, required=False)

    class Meta:
        model = EmailThread
        fields = [
            'id', 'conversation_id', 'subject', 'message_count',
            'last_message_at', 'category', 'stage', 'user',
            'orders', 'messages', 'last_sender_name', 'last_sender_email',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'message_count', 'category', 'created_at', 'updated_at']


class EmailThreadDetailSerializer(serializers.ModelSerializer):
    """Full thread payload, including message bodies.

    Only returned by the detail request (GET /api/rfq/email-threads/<id>/) so the
    large `body` fields are never sent as part of the board's list response.
    """

    messages = EmailMessageSerializer(many=True, read_only=True)
    orders = RfqDetailSerializer(many=True, read_only=True)

    class Meta:
        model = EmailThread
        fields = [
            'id', 'conversation_id', 'subject', 'message_count',
            'last_message_at', 'category', 'stage', 'user',
            'orders', 'messages', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'message_count', 'category', 'created_at', 'updated_at']
