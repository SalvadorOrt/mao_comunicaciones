from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from organizacion.models import Sucursal


# =========================================================
# NÚMERO / CANAL
# =========================================================


class NumeroCanal(models.Model):
    """
    Representa un canal o punto de comunicación empresarial.

    Un canal puede tener una sucursal predeterminada y,
    adicionalmente, estar habilitado para operar en varias
    sucursales.
    """

    class TipoCanal(models.TextChoices):
        CORPORATIVO = "CORPORATIVO", "Corporativo"
        MIXTO = "MIXTO", "Mixto"
        EXTERNO_PERSONAL = "EXTERNO_PERSONAL", "Externo Personal"

    nombre = models.CharField(
        max_length=255,
    )

    numero_telefonico = models.CharField(
        max_length=50,
        null=True,
        blank=True,
    )

    identificador_externo = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    # =====================================================
    # SUCURSAL PREDETERMINADA
    # =====================================================

    sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.PROTECT,
        related_name="canales",
    )

    # =====================================================
    # SUCURSALES HABILITADAS
    # =====================================================

    sucursales_habilitadas = models.ManyToManyField(
        Sucursal,
        blank=True,
        related_name="canales_habilitados",
    )

    # =====================================================
    # TIPO
    # =====================================================

    tipo = models.CharField(
        max_length=50,
        choices=TipoCanal.choices,
        default=TipoCanal.CORPORATIVO,
    )

    # =====================================================
    # PROPIETARIO
    # =====================================================

    propietario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="canales_propios",
    )

    # =====================================================
    # USUARIOS AUTORIZADOS
    # =====================================================

    usuarios_autorizados = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="canales_autorizados",
    )

    activo = models.BooleanField(
        default=True,
    )

    class Meta:
        verbose_name = "Número/Canal"
        verbose_name_plural = "Números/Canales"

    def clean(self):
        super().clean()

        if self.tipo in [
            self.TipoCanal.MIXTO,
            self.TipoCanal.EXTERNO_PERSONAL,
        ]:
            if not self.propietario:
                raise ValidationError(
                    {
                        "propietario": (
                            "Los canales de tipo MIXTO o "
                            "EXTERNO_PERSONAL requieren un "
                            "propietario asignado."
                        )
                    }
                )

    def permite_sucursal(self, sucursal):
        if not sucursal:
            return False

        if self.sucursal_id == sucursal.pk:
            return True

        if not self.pk:
            return False

        return (
            self.sucursales_habilitadas
            .filter(
                pk=sucursal.pk,
                activa=True,
            )
            .exists()
        )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.nombre} "
            f"({self.numero_telefonico or 'Sin número'}) "
            f"- {self.tipo}"
        )


# =========================================================
# CONTACTO
# =========================================================


class Contacto(models.Model):
    """
    Representa una identidad externa que interactúa
    con los canales de comunicación.
    """

    nombre = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    nombre_perfil = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    numero_telefonico = models.CharField(
        max_length=50,
        null=True,
        blank=True,
    )

    identificador_externo = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Contacto"
        verbose_name_plural = "Contactos"

    def __str__(self):
        return (
            self.nombre
            or self.nombre_perfil
            or self.numero_telefonico
            or f"Contacto #{self.id}"
        )


# =========================================================
# IDENTIDAD EXTERNA DEL CONTACTO
# =========================================================


class IdentidadContactoExterna(models.Model):
    contacto = models.ForeignKey(
        Contacto,
        on_delete=models.CASCADE,
        related_name="identidades_externas",
    )

    proveedor = models.CharField(
        max_length=50,
    )

    identificador_externo = models.CharField(
        max_length=255,
    )

    class Meta:
        verbose_name = "Identidad Contacto Externa"
        verbose_name_plural = "Identidades Contactos Externas"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "proveedor",
                    "identificador_externo",
                ],
                name="unique_identidad_proveedor_externo",
            )
        ]

    def __str__(self):
        return (
            f"[{self.proveedor}] "
            f"{self.identificador_externo} "
            f"-> Contacto #{self.contacto_id}"
        )


# =========================================================
# CONVERSACIÓN
# =========================================================


class Conversacion(models.Model):
    class TipoConversacion(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        GRUPO = "GRUPO", "Grupo"

    class PrivacidadConversacion(models.TextChoices):
        EMPRESARIAL = "EMPRESARIAL", "Empresarial"
        PRIVADA = "PRIVADA", "Privada"
        SIN_CLASIFICAR = "SIN_CLASIFICAR", "Sin Clasificar"

    numero_canal = models.ForeignKey(
        NumeroCanal,
        on_delete=models.PROTECT,
        related_name="conversaciones",
    )

    sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.PROTECT,
        related_name="conversaciones",
    )

    contacto = models.ForeignKey(
        Contacto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversaciones",
    )

    tipo = models.CharField(
        max_length=50,
        choices=TipoConversacion.choices,
        default=TipoConversacion.INDIVIDUAL,
    )

    privacidad = models.CharField(
        max_length=50,
        choices=PrivacidadConversacion.choices,
        default=PrivacidadConversacion.SIN_CLASIFICAR,
    )

    usuarios_autorizados = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="conversaciones_autorizadas",
    )

    asignado_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversaciones_asignadas",
    )

    pendiente = models.BooleanField(
        default=False,
        db_index=True,
    )

    ultimo_mensaje_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Conversación"
        verbose_name_plural = "Conversaciones"

        permissions = [
            (
                "cambiar_privacidad_conversacion",
                "Can change conversation privacy classification",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "numero_canal",
                    "contacto",
                ],
                name="unique_conversacion_individual_por_contacto",
                condition=models.Q(
                    tipo="INDIVIDUAL",
                    contacto__isnull=False,
                ),
            )
        ]

    def clean(self):
        super().clean()

        if self.numero_canal_id and self.sucursal_id:
            if not self.numero_canal.permite_sucursal(
                self.sucursal
            ):
                raise ValidationError(
                    {
                        "sucursal": (
                            "La sucursal de la conversación "
                            "no está habilitada para este canal."
                        )
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.tipo == self.TipoConversacion.GRUPO:
            tipo_label = "Grupo"
        else:
            tipo_label = f"Individual con {self.contacto}"

        return (
            f"Chat #{self.id} "
            f"[{tipo_label}] "
            f"- Canal: {self.numero_canal.nombre}"
        )


# =========================================================
# GRUPO
# =========================================================


class Grupo(models.Model):
    conversacion = models.OneToOneField(
        Conversacion,
        on_delete=models.PROTECT,
        related_name="grupo",
    )

    identificador_externo = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    nombre = models.CharField(
        max_length=255,
    )

    descripcion = models.TextField(
        null=True,
        blank=True,
    )

    activo = models.BooleanField(
        default=True,
    )

    class Meta:
        verbose_name = "Grupo"
        verbose_name_plural = "Grupos"

    def clean(self):
        super().clean()

        if (
            self.conversacion_id
            and self.conversacion.tipo
            != Conversacion.TipoConversacion.GRUPO
        ):
            raise ValidationError(
                {
                    "conversacion": (
                        "Un grupo solo puede asociarse "
                        "a una conversación de tipo GRUPO."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"Grupo: {self.nombre} "
            f"(Chat #{self.conversacion_id})"
        )


# =========================================================
# PARTICIPANTE
# =========================================================


class Participante(models.Model):
    grupo = models.ForeignKey(
        Grupo,
        on_delete=models.CASCADE,
        related_name="participantes",
    )

    contacto = models.ForeignKey(
        Contacto,
        on_delete=models.PROTECT,
        related_name="membresias",
    )

    es_administrador = models.BooleanField(
        default=False,
    )

    fecha_union = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Participante de Grupo"
        verbose_name_plural = "Participantes de Grupos"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "grupo",
                    "contacto",
                ],
                name="unique_contacto_per_grupo",
            )
        ]

    def __str__(self):
        admin_flag = (
            " (Admin)"
            if self.es_administrador
            else ""
        )

        return (
            f"{self.contacto} "
            f"en {self.grupo.nombre}"
            f"{admin_flag}"
        )


# =========================================================
# MENSAJE
# =========================================================


class Mensaje(models.Model):
    class TipoMensaje(models.TextChoices):
        TEXT = "TEXT", "Texto"
        AUDIO = "AUDIO", "Audio"
        IMAGE = "IMAGE", "Imagen"
        VIDEO = "VIDEO", "Video"
        DOCUMENT = "DOCUMENT", "Documento"
        LOCATION = "LOCATION", "Ubicación"
        CONTACT = "CONTACT", "Contacto"
        REACTION = "REACTION", "Reacción"
        STICKER = "STICKER", "Sticker"
        UNKNOWN = "UNKNOWN", "Desconocido"

    class DireccionMensaje(models.TextChoices):
        ENTRANTE = "ENTRANTE", "Entrante"
        SALIENTE = "SALIENTE", "Saliente"
        SISTEMA = "SISTEMA", "Sistema"

    class EstadoMensaje(models.TextChoices):
        RECIBIDO = "RECIBIDO", "Recibido"
        ENVIADO = "ENVIADO", "Enviado"
        ENTREGADO = "ENTREGADO", "Entregado"
        LEIDO = "LEIDO", "Leído"
        FALLIDO = "FALLIDO", "Fallido"

    conversacion = models.ForeignKey(
        Conversacion,
        on_delete=models.PROTECT,
        related_name="mensajes",
    )

    external_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    remitente = models.ForeignKey(
        Contacto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mensajes_enviados",
    )

    direccion = models.CharField(
        max_length=50,
        choices=DireccionMensaje.choices,
    )

    tipo = models.CharField(
        max_length=50,
        choices=TipoMensaje.choices,
        default=TipoMensaje.TEXT,
    )

    texto_original = models.TextField(
        null=True,
        blank=True,
    )

    estado = models.CharField(
        max_length=50,
        choices=EstadoMensaje.choices,
        default=EstadoMensaje.RECIBIDO,
    )

    fecha_mensaje = models.DateTimeField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    respuesta_a = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="respuestas",
    )

    class Meta:
        verbose_name = "Message"
        verbose_name_plural = "Messages"

        ordering = [
            "fecha_mensaje",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "conversacion",
                    "external_id",
                ],
                name="unique_external_id_per_conversation",
                condition=models.Q(
                    external_id__isnull=False
                ),
            )
        ]

    def __str__(self):
        sender_label = (
            self.remitente.nombre
            if self.remitente
            else self.direccion
        )

        contenido = (
            self.texto_original
            or self.tipo
        )

        return (
            f"[{self.fecha_mensaje.strftime('%Y-%m-%d %H:%M')}] "
            f"{sender_label}: "
            f"{contenido[:30]}"
        )


# =========================================================
# ARCHIVO MULTIMEDIA
# =========================================================


class ArchivoMultimedia(models.Model):
    mensaje = models.ForeignKey(
        Mensaje,
        on_delete=models.CASCADE,
        related_name="archivos_multimedia",
    )

    archivo = models.FileField(
        upload_to="multimedia/",
    )

    identificador_externo = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    nombre_original = models.CharField(
        max_length=255,
    )

    mime_type = models.CharField(
        max_length=127,
    )

    size_bytes = models.IntegerField(
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Archivo Multimedia"
        verbose_name_plural = "Archivos Multimedia"

    def __str__(self):
        return (
            f"{self.nombre_original} "
            f"({self.mime_type})"
        )