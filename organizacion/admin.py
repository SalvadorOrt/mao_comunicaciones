from django.contrib import admin

from .models import Sucursal


@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nombre",
        "erp_sucursal_id",
        "activa",
    )

    list_filter = (
        "activa",
    )

    search_fields = (
        "codigo",
        "nombre",
    )