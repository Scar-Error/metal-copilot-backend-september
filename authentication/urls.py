"""
URL configuration for Authentication app.
"""
from django.urls import path
from .views import login_view, protected_view

urlpatterns = [
    path('login/', login_view, name='login'),
    path('protected/', protected_view, name='protected'),
]
