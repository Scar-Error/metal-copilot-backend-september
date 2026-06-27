from rest_framework import serializers
from rfq.models import Order, OrderItem, OrderAttachment, OrderAnalytics


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = [
            'id', 'order', 'item_name', 'item_code', 'description',
            'quantity', 'unit', 'unit_price', 'total_price',
            'extraction_confidence', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'extraction_confidence']

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


class OrderAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderAttachment
        fields = [
            'id', 'order', 'filename', 'file_path', 'file_size',
            'file_type', 'mime_type', 'uploaded_at',
        ]
        read_only_fields = ['id', 'uploaded_at']


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    attachments = OrderAttachmentSerializer(many=True, read_only=True)
    reviewed_by_username = serializers.CharField(
        source='reviewed_by.username', read_only=True,
    )
    contact_name = serializers.CharField(
        source='contact.company_name', read_only=True, default=None,
    )
    supplier_name = serializers.CharField(
        source='supplier.company_name', read_only=True, default=None,
    )
    supplier_id = serializers.IntegerField(
        source='supplier.id', read_only=True, default=None,
    )

    class Meta:
        model = Order
        fields = [
            'id', 'type', 'stage', 'rfq_number', 'company_name',
            'contact', 'contact_name', 'supplier', 'supplier_id', 'supplier_name',
            'supplier_email', 'status', 'priority', 'source',
            'email_subject', 'email_sender', 'email_received_at', 'email_body',
            'email_classification',
            'items_description', 'quantity', 'specifications',
            'delivery_date', 'budget',
            'ai_processed', 'ai_confidence_score', 'processing_errors',
            'supplier_email_sent', 'supplier_email_sent_at', 'supplier_email_error',
            'reviewed_by', 'reviewed_by_username', 'reviewed_at', 'notes',
            'items', 'attachments',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'rfq_number', 'email_received_at', 'ai_processed',
            'ai_confidence_score', 'processing_errors',
            'supplier_email_sent', 'supplier_email_sent_at', 'supplier_email_error',
            'reviewed_by', 'reviewed_at', 'created_at', 'updated_at',
        ]


class OrderListSerializer(serializers.ModelSerializer):
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'type', 'stage', 'rfq_number', 'company_name', 'status', 'priority',
            'source', 'email_subject', 'email_sender', 'email_received_at',
            'email_classification',
            'ai_processed', 'items_count',
            'supplier_email', 'supplier_email_sent', 'supplier_email_sent_at',
        ]

    def get_items_count(self, obj):
        return obj.items.count()


class OrderAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderAnalytics
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class DealSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='email_subject')
    number = serializers.CharField(source='rfq_number')
    company = serializers.CharField(source='company_name')
    value = serializers.DecimalField(source='budget', max_digits=12, decimal_places=2, allow_null=True)
    expected_date = serializers.DateField(source='delivery_date', allow_null=True)
    contact_person = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'title', 'type', 'stage', 'number',
            'company', 'contact_person', 'value',
            'probability', 'expected_date', 'notes',
        ]

    def get_contact_person(self, obj):
        if obj.contact:
            return obj.contact.contact_person or obj.contact.company_name
        return ''
