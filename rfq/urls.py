from django.urls import path, include
from rest_framework.routers import SimpleRouter
from .views import OrderViewSet, OrderItemViewSet, OrderAttachmentViewSet, DealViewSet
from . import views_email

router = SimpleRouter()
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'items', OrderItemViewSet, basename='orderitem')
router.register(r'attachments', OrderAttachmentViewSet, basename='orderattachment')
router.register(r'deals', DealViewSet, basename='deal')

urlpatterns = [
    path('', include(router.urls)),
    # Email monitoring endpoints
    path('monitor/emails/', views_email.trigger_email_monitoring, name='trigger_email_monitoring'),
    path('monitor/ai/<int:order_id>/', views_email.trigger_ai_processing, name='trigger_ai_processing'),
    path('monitor/bc/<int:order_id>/', views_email.trigger_business_central_sync, name='trigger_bc_sync'),
    path('monitor/task/<str:task_id>/', views_email.get_task_status, name='get_task_status'),
    path('monitor/sync-products/', views_email.sync_products_from_bc, name='sync_products'),
    path('monitor/emails/list/', views_email.get_microsoft_emails, name='get_microsoft_emails'),
    path('monitor/emails/orders/', views_email.get_rfq_emails, name='get_rfq_emails'),
]
