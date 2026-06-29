from django.urls import path, include
from rest_framework.routers import SimpleRouter
from contacts.views import ContactViewSet

router = SimpleRouter()
router.register(r'contacts', ContactViewSet, basename='contact')

urlpatterns = [
    path('', include(router.urls)),
]
