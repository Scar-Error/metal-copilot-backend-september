from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q

from contacts.models import Contact
from contacts.serializers import ContactSerializer


class ContactViewSet(viewsets.ModelViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Contact.objects.all()
        type_param = self.request.query_params.get('type')
        if type_param in ('supplier', 'client'):
            qs = qs.filter(type=type_param)
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(company_name__icontains=search)
                | Q(contact_person__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
            )
        return qs

    @action(detail=False, methods=['post'])
    def bulk_delete(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return Response(
                {'error': 'No IDs provided'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        deleted, _ = Contact.objects.filter(id__in=ids).delete()
        return Response({'deleted': deleted})

    @action(detail=True, methods=['post'])
    def sync_bc(self, request, pk=None):
        """Create (or return) this single contact as a customer in Business Central."""
        from django.conf import settings
        from rfq.business_central import (
            build_bc_client_for_user,
            CUSTOMER_NAME_SUFFIX,
        )

        contact = self.get_object()

        client = build_bc_client_for_user(request.user)
        if not client:
            return Response(
                {'error': 'Business Central is not configured (missing credentials)'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        company_id = client.get_company_by_name(settings.BC_COMPANY_NAME)
        if not company_id:
            return Response(
                {'error': f'Business Central company "{settings.BC_COMPANY_NAME}" not found'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        customer_name = f'{contact.company_name}{CUSTOMER_NAME_SUFFIX}'

        existing = client.get_customer_by_name(company_id, customer_name)
        if existing:
            return Response({
                'success': True,
                'already_synced': True,
                'customer_number': existing.get('number'),
                'customer_id': existing.get('id'),
            })

        result = client.create_customer(
            company_id=company_id,
            customer_name=customer_name,
            email=contact.email or '',
        )
        if not result:
            return Response(
                {'error': 'Failed to create customer in Business Central'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({
            'success': True,
            'already_synced': False,
            'customer_number': result.get('number'),
            'customer_id': result.get('id'),
        })
