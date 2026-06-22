"""
Microsoft Authentication URLs
"""
from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.microsoft_login, name='microsoft_login'),
    path('callback/', views.microsoft_callback, name='microsoft_callback'),
    path('refresh/', views.refresh_microsoft_token, name='refresh_microsoft_token'),
    path('disconnect/', views.disconnect_microsoft, name='disconnect_microsoft'),
    path('status/', views.microsoft_status, name='microsoft_status'),
]
