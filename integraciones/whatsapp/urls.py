# integraciones/whatsapp/urls.py

from django.urls import path

from integraciones.whatsapp.views import (
    whatsapp_webhook_view,
)


app_name = "whatsapp"


urlpatterns = [
    path(
        "webhook/",
        whatsapp_webhook_view,
        name="webhook",
    ),
]