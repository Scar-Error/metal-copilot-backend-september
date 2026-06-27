from rest_framework import serializers
from tasks.models import Task


class TaskSerializer(serializers.ModelSerializer):
    order_rfq_number = serializers.CharField(
        source='order.rfq_number', read_only=True, default=None,
    )
    assigned_to_username = serializers.CharField(
        source='assigned_to.username', read_only=True, default=None,
    )

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'status',
            'order', 'order_rfq_number',
            'assigned_to', 'assigned_to_username',
            'created_at', 'completed_at',
        ]
        read_only_fields = ['id', 'created_at', 'completed_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['completed'] = instance.status == 'completed'
        return data
