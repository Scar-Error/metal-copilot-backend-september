from django.urls import path, include
from rest_framework.routers import SimpleRouter
from .views import OrderViewSet, OrderItemViewSet, DealViewSet, EmailThreadViewSet
from . import views_email

router = SimpleRouter()
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'items', OrderItemViewSet, basename='orderitem')
router.register(r'deals', DealViewSet, basename='deal')
router.register(r'email-threads', EmailThreadViewSet, basename='emailthread')

urlpatterns = [
    path('', include(router.urls)),
    # Email monitoring endpoints
    path('monitor/emails/pull/', views_email.pull_emails, name='pull_emails'),
    path('monitor/task/<str:task_id>/', views_email.get_task_status, name='get_task_status'),
    path('monitor/sync-products/', views_email.sync_products_from_bc, name='sync_products'),
]
