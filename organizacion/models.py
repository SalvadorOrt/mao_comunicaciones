from django.db import models


class Sucursal(models.Model):
    """
    Referencia local a una sucursal existente en MAO ERP.

    MAO ERP sigue siendo la fuente de verdad.
    MAO Comunicaciones conserva únicamente los datos
    necesarios para enrutar canales y conversaciones.
    """

    erp_sucursal_id = models.IntegerField(
        null=True,
        blank=True,
        unique=True,
    )

    codigo = models.CharField(
        max_length=50,
        unique=True,
    )

    nombre = models.CharField(
        max_length=255,
    )

    activa = models.BooleanField(
        default=True,
    )

    class Meta:
        verbose_name = "Sucursal"
        verbose_name_plural = "Sucursales"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"