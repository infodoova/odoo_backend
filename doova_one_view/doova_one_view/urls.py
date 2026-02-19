"""
URL configuration for doova_one_view project.

API endpoints are now handled by FastAPI via ASGI routing.
Django only handles admin and static files.
"""
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path('admin/', admin.site.urls),
    # API routes are handled by FastAPI via ASGI (see asgi.py)
]
