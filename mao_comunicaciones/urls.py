from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path(
        "admin/",
        admin.site.urls,
    ),

    path(
        "integraciones/whatsapp/",
        include(
            "integraciones.whatsapp.urls"
        ),
    ),
]