from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db.models import Q
from django.utils import timezone

from rfq.models import Order, OrderItem, OrderAttachment
from rfq.serializers import (
    OrderSerializer,
    OrderListSerializer,
    OrderItemSerializer,
    OrderAttachmentSerializer,
    OrderAnalyticsSerializer,
    DealSerializer,
)
from rfq.analytics_service import compute_analytics, dashboard_stats
from rfq.email_service import SupplierEmailService
from rfq.email_ingestion_service import EmailIngestionService
from microsoft_auth.graph_api import GraphEmailProvider

ALLOWED_STATUS_TRANSITIONS = {
    'pending': ['processing', 'rejected'],
    'processing': ['completed', 'rejected'],
    'completed': [],
    'rejected': [],
}


def _build_email_provider(user) -> GraphEmailProvider:
    """Helper: build a GraphEmailProvider from a Django user."""
    token = user.microsoft_token
    token.refresh_if_expired()
    return GraphEmailProvider(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        token_expires_at=token.token_expires_at,
        user=user,
    )


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return OrderListSerializer
        return OrderSerializer

    def get_queryset(self):
        qs = Order.objects.all()

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        stage_param = self.request.query_params.get('stage')
        if stage_param:
            qs = qs.filter(stage=stage_param)

        type_param = self.request.query_params.get('type')
        if type_param:
            qs = qs.filter(type=type_param)

        email_classification_param = self.request.query_params.get('email_classification')
        if email_classification_param:
            qs = qs.filter(email_classification=email_classification_param)

        priority_param = self.request.query_params.get('priority')
        if priority_param:
            qs = qs.filter(priority=priority_param)

        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            qs = qs.filter(email_received_at__gte=start_date)
        if end_date:
            qs = qs.filter(email_received_at__lte=end_date)

        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(company_name__icontains=search)
                | Q(rfq_number__icontains=search)
                | Q(email_subject__icontains=search)
            )

        return qs

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        record = compute_analytics()
        serializer = OrderAnalyticsSerializer(record)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        return Response(dashboard_stats())

    @action(detail=False, methods=['get'])
    def available_suppliers(self, request):
        """Get list of all suppliers for dropdown selection."""
        from contacts.models import Contact
        
        suppliers = Contact.objects.filter(type='supplier').order_by('company_name')
        
        suppliers_data = []
        for supplier in suppliers:
            suppliers_data.append({
                'id': supplier.id,
                'company_name': supplier.company_name,
                'email': supplier.email,
                'contact_person': supplier.contact_person,
                'phone': supplier.phone,
            })
        
        return Response({
            'count': len(suppliers_data),
            'suppliers': suppliers_data,
        })

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        order = self.get_object()
        new_status = request.data.get('status', 'completed')

        allowed = ALLOWED_STATUS_TRANSITIONS.get(order.status, [])
        if new_status not in allowed:
            return Response(
                {
                    'error': (
                        f'Invalid transition from {order.status!r} '
                        f'to {new_status!r}. Allowed: {allowed}'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        order.reviewed_by = request.user
        order.reviewed_at = timezone.now()
        order.status = new_status
        order.notes = request.data.get('notes', '')
        order.save()

        serializer = OrderSerializer(order)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def send_to_supplier(self, request, pk=None):
        order = self.get_object()

        supplier_email = request.data.get('supplier_email')
        if supplier_email:
            order.supplier_email = supplier_email
            order.save(update_fields=['supplier_email'])

        if not order.supplier_email and not order.supplier:
            return Response(
                {'success': False, 'message': 'No supplier configured'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            provider = _build_email_provider(request.user)
        except Exception:
            return Response(
                {'success': False, 'message': 'No valid Microsoft token'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        email_service = SupplierEmailService(email_provider=provider)
        result = email_service.send_rfq_to_supplier(order)

        if result['success']:
            order.stage = 'quotation'
            order.save(update_fields=['stage'])
            return Response(
                {
                    'success': True,
                    'message': result['message'],
                    'order_id': order.id,
                    'supplier_email': order.supplier_email,
                    'email_sent_at': order.supplier_email_sent_at,
                },
                status=status.HTTP_200_OK,
            )
        return Response(result, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def assign_supplier(self, request, pk=None):
        order = self.get_object()
        supplier_id = request.data.get('supplier_id')
        auto_dispatch = request.data.get('auto_dispatch', False)

        if not supplier_id:
            return Response(
                {'error': 'supplier_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from contacts.models import Contact
        try:
            supplier = Contact.objects.get(id=supplier_id, type='supplier')
        except Contact.DoesNotExist:
            return Response(
                {'error': 'Supplier not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Add supplier to the ManyToMany field
        order.suppliers.add(supplier)
        
        # Set as primary supplier if not already set
        if not order.supplier:
            order.supplier = supplier
            order.supplier_email = supplier.email
            order.save(update_fields=['supplier', 'supplier_email'])

        # Create supplier assignment record
        from rfq.models import OrderSupplierAssignment
        OrderSupplierAssignment.objects.get_or_create(
            order=order,
            supplier=supplier,
            defaults={'assigned_by': request.user}
        )

        # Mark related tasks as completed
        from tasks.models import Task
        Task.objects.filter(order=order, status='pending').update(
            status='completed',
            completed_at=timezone.now()
        )

        # Auto-dispatch if requested
        if auto_dispatch:
            from rfq.tasks import dispatch_to_supplier
            dispatch_to_supplier.delay(order.id, supplier_id)

        return Response({
            'success': True,
            'message': f'Supplier {supplier.company_name} assigned',
            'order_id': order.id,
            'supplier_id': supplier.id,
            'auto_dispatched': auto_dispatch,
        })

    @action(detail=True, methods=['post'])
    def dispatch_to_supplier(self, request, pk=None):
        """Manually dispatch RFQ to a specific supplier."""
        order = self.get_object()
        supplier_id = request.data.get('supplier_id')

        if not supplier_id:
            return Response(
                {'error': 'supplier_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from contacts.models import Contact
        try:
            supplier = Contact.objects.get(id=supplier_id, type='supplier')
        except Contact.DoesNotExist:
            return Response(
                {'error': 'Supplier not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from rfq.tasks import dispatch_to_supplier
        dispatch_to_supplier.delay(order.id, supplier_id)

        return Response({
            'success': True,
            'message': f'Dispatch queued to supplier {supplier.company_name}',
            'order_id': order.id,
            'supplier_id': supplier.id,
        })

    @action(detail=True, methods=['get'])
    def suppliers(self, request, pk=None):
        """Get list of suppliers assigned to this order with their email status."""
        order = self.get_object()
        
        from rfq.models import OrderSupplierAssignment
        assignments = order.supplier_assignments.all()
        
        suppliers_data = []
        for assignment in assignments:
            suppliers_data.append({
                'id': assignment.supplier.id,
                'company_name': assignment.supplier.company_name,
                'email': assignment.supplier.email,
                'contact_person': assignment.supplier.contact_person,
                'assigned_at': assignment.assigned_at,
                'email_sent': assignment.email_sent,
                'email_sent_at': assignment.email_sent_at,
                'email_error': assignment.email_error,
                'is_primary': order.supplier_id == assignment.supplier.id,
            })
        
        return Response({
            'order_id': order.id,
            'suppliers': suppliers_data,
        })

    @action(detail=False, methods=['post'])
    def process_emails(self, request):
        days_back = request.data.get('days_back', 1)

        try:
            _build_email_provider(request.user)
        except Exception:
            return Response(
                {'success': False, 'message': 'No valid Microsoft token'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        service = EmailIngestionService(request.user)
        result = service.check_and_process_new_emails(days_back=days_back)

        if result['success']:
            return Response(result, status=status.HTTP_200_OK)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)


class OrderItemViewSet(viewsets.ModelViewSet):
    queryset = OrderItem.objects.all()
    serializer_class = OrderItemSerializer
    pagination_class = None

    def get_queryset(self):
        qs = OrderItem.objects.all()
        order_id = self.request.query_params.get('order_id')
        if order_id:
            qs = qs.filter(order_id=order_id)
        return qs


class OrderAttachmentViewSet(viewsets.ModelViewSet):
    queryset = OrderAttachment.objects.all()
    serializer_class = OrderAttachmentSerializer
    pagination_class = None

    def get_queryset(self):
        qs = OrderAttachment.objects.all()
        order_id = self.request.query_params.get('order_id')
        if order_id:
            qs = qs.filter(order_id=order_id)
        return qs


class DealViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = DealSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = Order.objects.all()
        stage_param = self.request.query_params.get('stage')
        if stage_param:
            qs = qs.filter(stage=stage_param)
        return qs
