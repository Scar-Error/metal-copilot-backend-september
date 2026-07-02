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
