from django.core.exceptions import ValidationError
from django.db import models

from organizacion.models import Sucursal


# =========================================================
# NÚMERO / CANAL
# =========================================================


class NumeroCanal(models.Model):
    """
    Representa un punto de comunicación administrado por
    MAO Comunicaciones.

    Ejemplos:

        - WhatsApp principal de MAO.
        - WhatsApp de un asesor.
        - WhatsApp específico de MAO Norte.
        - WhatsApp específico de MAO Sur.

    La sucursal NO es propiedad de MAO Comunicaciones.

    Cuando existe una relación con una sucursal, esta apunta
    a una referencia local sincronizada desde MAO ERP.

    Un canal corporativo puede no pertenecer a ninguna
    sucursal concreta y operar para varias.
    """

    # =====================================================
    # PROVEEDOR
    # =====================================================

    class Proveedor(models.TextChoices):
        WHATSAPP = "WHATSAPP", "WhatsApp"
        OTRO = "OTRO", "Otro"

    # =====================================================
    # TIPO
    # =====================================================

    class TipoCanal(models.TextChoices):
        CORPORATIVO = "CORPORATIVO", "Corporativo"
        SUCURSAL = "SUCURSAL", "Sucursal"
        ASESOR = "ASESOR", "Asesor"
        OTRO = "OTRO", "Otro"

    # =====================================================
    # IDENTIFICACIÓN
    # =====================================================

    nombre = models.CharField(
        max_length=255,
    )

    proveedor = models.CharField(
        max_length=50,
        choices=Proveedor.choices,
        default=Proveedor.WHATSAPP,
        db_index=True,
    )

    tipo = models.CharField(
        max_length=50,
        choices=TipoCanal.choices,
        default=TipoCanal.CORPORATIVO,
        db_index=True,
    )

    numero_telefonico = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
    )

    # Ejemplo para Meta:
    #
    #     phone_number_id
    #
    identificador_externo = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
    )

    # =====================================================
    # CANAL PRINCIPAL
    # =====================================================

    es_principal = models.BooleanField(
        default=False,
        db_index=True,
    )

    # =====================================================
    # SUCURSAL PREDETERMINADA
    # =====================================================
    #
    # NULL significa:
    #
    #     canal corporativo / sin sucursal predeterminada.
    #
    # Nunca se crea una sucursal empresarial desde aquí.
    # Es únicamente una referencia sincronizada desde ERP.
    # =====================================================

    sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="canales",
    )

    # =====================================================
    # SUCURSALES HABILITADAS
    # =====================================================
    #
    # Permite que el mismo canal corporativo pueda operar
    # para varias sucursales.
    # =====================================================

    sucursales_habilitadas = models.ManyToManyField(
        Sucursal,
        blank=True,
        related_name="canales_habilitados",
    )

    # =====================================================
    # ESTADO
    # =====================================================

    activo = models.BooleanField(
        default=True,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    # =====================================================
    # META
    # =====================================================

    class Meta:
        verbose_name = "Número/Canal"
        verbose_name_plural = "Números/Canales"

        ordering = [
            "-es_principal",
            "nombre",
        ]

        constraints = [
            # El identificador de un canal debe ser único
            # dentro de un proveedor.
            models.UniqueConstraint(
                fields=[
                    "proveedor",
                    "identificador_externo",
                ],
                condition=models.Q(
                    identificador_externo__isnull=False,
                ),
                name=(
                    "unique_canal_proveedor_identificador"
                ),
            ),

            # Solo un canal principal activo por proveedor.
            models.UniqueConstraint(
                fields=[
                    "proveedor",
                ],
                condition=models.Q(
                    es_principal=True,
                    activo=True,
                ),
                name=(
                    "unique_canal_principal_activo_proveedor"
                ),
            ),
        ]

    # =====================================================
    # VALIDACIONES
    # =====================================================

    def clean(self):
        super().clean()

        # Un canal marcado como SUCURSAL debe tener
        # una sucursal predeterminada.
        if (
            self.tipo == self.TipoCanal.SUCURSAL
            and not self.sucursal_id
        ):
            raise ValidationError(
                {
                    "sucursal": (
                        "Un canal de tipo SUCURSAL debe "
                        "tener una sucursal asociada."
                    )
                }
            )

    # =====================================================
    # SUCURSALES
    # =====================================================

    def permite_sucursal(self, sucursal):
        """
        Indica si este canal puede utilizarse para una
        determinada sucursal.

        La sucursal recibida siempre debe ser una referencia
        local sincronizada desde MAO ERP.
        """

        if not sucursal:
            return False

        if not sucursal.activa:
            return False

        # Sucursal predeterminada.
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

    # =====================================================
    # GUARDADO
    # =====================================================

    def save(self, *args, **kwargs):
        self.full_clean()

        super().save(
            *args,
            **kwargs,
        )

    # =====================================================
    # REPRESENTACIÓN
    # =====================================================

    def __str__(self):
        principal = (
            " [PRINCIPAL]"
            if self.es_principal
            else ""
        )

        return (
            f"{self.nombre}"
            f"{principal} "
            f"({self.numero_telefonico or 'Sin número'})"
        )


# =========================================================
# CONTACTO
# =========================================================


class Contacto(models.Model):
    """
    Representa una persona o entidad externa con la que
    MAO mantiene una comunicación.

    MAO Comunicaciones no necesita saber si el contacto
    es cliente, proveedor, empleado, prospecto, etc.

    Esa interpretación corresponde al ERP, MAO Citas,
    MAO Asistente u otros sistemas.
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
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Contacto"
        verbose_name_plural = "Contactos"

    def __str__(self):
        return (
            self.nombre
            or self.nombre_perfil
            or self.numero_telefonico
            or f"Contacto #{self.pk}"
        )


# =========================================================
# IDENTIDAD EXTERNA DEL CONTACTO
# =========================================================


class IdentidadContactoExterna(models.Model):
    """
    Vincula un Contacto con la identidad que utiliza
    dentro de un proveedor externo.

    Ejemplo:

        proveedor = META
        identificador_externo = wa_id
    """

    contacto = models.ForeignKey(
        Contacto,
        on_delete=models.CASCADE,
        related_name="identidades_externas",
    )

    proveedor = models.CharField(
        max_length=50,
        db_index=True,
    )

    identificador_externo = models.CharField(
        max_length=255,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Identidad externa del contacto"
        verbose_name_plural = "Identidades externas de contactos"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "proveedor",
                    "identificador_externo",
                ],
                name=(
                    "unique_identidad_proveedor_externo"
                ),
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
    """
    Contenedor lógico de mensajes entre un canal de MAO
    y un contacto externo.

    Una conversación puede comenzar sin sucursal.

    Ejemplo:

        cliente
            ↓
        WhatsApp principal MAO
            ↓
        Conversacion.sucursal = NULL

    Posteriormente ERP, MAO Citas, un asesor u otro sistema
    puede determinar:

        Conversacion.sucursal = referencia ERP de MAO Norte

    MAO Comunicaciones no inventa esa sucursal.
    """

    class TipoConversacion(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        GRUPO = "GRUPO", "Grupo"

    # =====================================================
    # CANAL
    # =====================================================

    numero_canal = models.ForeignKey(
        NumeroCanal,
        on_delete=models.PROTECT,
        related_name="conversaciones",
    )

    # =====================================================
    # SUCURSAL
    # =====================================================

    sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="conversaciones",
    )

    # =====================================================
    # CONTACTO PRINCIPAL
    # =====================================================

    contacto = models.ForeignKey(
        Contacto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversaciones",
    )

    # =====================================================
    # TIPO
    # =====================================================

    tipo = models.CharField(
        max_length=50,
        choices=TipoConversacion.choices,
        default=TipoConversacion.INDIVIDUAL,
        db_index=True,
    )

    # =====================================================
    # ESTADO
    # =====================================================

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

    # =====================================================
    # META
    # =====================================================

    class Meta:
        verbose_name = "Conversación"
        verbose_name_plural = "Conversaciones"

        ordering = [
            "-ultimo_mensaje_at",
            "-created_at",
        ]

        constraints = [
            # Para un mismo canal no necesitamos dos chats
            # individuales distintos con el mismo contacto.
            models.UniqueConstraint(
                fields=[
                    "numero_canal",
                    "contacto",
                ],
                condition=models.Q(
                    tipo="INDIVIDUAL",
                    contacto__isnull=False,
                ),
                name=(
                    "unique_conversacion_individual_por_contacto"
                ),
            )
        ]

    # =====================================================
    # VALIDACIÓN
    # =====================================================

    def clean(self):
        super().clean()

        if (
            self.sucursal_id
            and self.numero_canal_id
        ):
            if not self.numero_canal.permite_sucursal(
                self.sucursal
            ):
                raise ValidationError(
                    {
                        "sucursal": (
                            "La sucursal no está habilitada "
                            "para este canal."
                        )
                    }
                )

    # =====================================================
    # GUARDADO
    # =====================================================

    def save(self, *args, **kwargs):
        self.full_clean()

        super().save(
            *args,
            **kwargs,
        )

    # =====================================================
    # REPRESENTACIÓN
    # =====================================================

    def __str__(self):
        contacto = (
            str(self.contacto)
            if self.contacto_id
            else "Sin contacto"
        )

        return (
            f"Conversación #{self.pk or 'NUEVA'} "
            f"- {self.numero_canal.nombre} "
            f"- {contacto}"
        )


# =========================================================
# GRUPO
# =========================================================


class Grupo(models.Model):
    """
    Extensión opcional de una conversación grupal.

    Actualmente WhatsApp Cloud API puede no utilizar esta
    funcionalidad, pero el modelo permanece genérico para
    otros canales futuros.
    """

    conversacion = models.OneToOneField(
        Conversacion,
        on_delete=models.CASCADE,
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

    created_at = models.DateTimeField(
        auto_now_add=True,
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
                        "Un Grupo requiere una conversación "
                        "de tipo GRUPO."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()

        super().save(
            *args,
            **kwargs,
        )

    def __str__(self):
        return self.nombre


# =========================================================
# PARTICIPANTE
# =========================================================


class Participante(models.Model):
    """
    Participación de un Contacto dentro de un Grupo.
    """

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
        verbose_name = "Participante"
        verbose_name_plural = "Participantes"

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
        return (
            f"{self.contacto} "
            f"en {self.grupo}"
        )


# =========================================================
# MENSAJE
# =========================================================


class Mensaje(models.Model):
    """
    Unidad fundamental de MAO Comunicaciones.

    MAO Comunicaciones registra el mensaje y su estado
    de transporte.

    No interpreta intención, citas, órdenes de trabajo,
    alertas ni lógica de negocio.
    """

    # =====================================================
    # TIPO
    # =====================================================

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

    # =====================================================
    # DIRECCIÓN
    # =====================================================

    class DireccionMensaje(models.TextChoices):
        ENTRANTE = "ENTRANTE", "Entrante"
        SALIENTE = "SALIENTE", "Saliente"
        SISTEMA = "SISTEMA", "Sistema"

    # =====================================================
    # ESTADO
    # =====================================================

    class EstadoMensaje(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        RECIBIDO = "RECIBIDO", "Recibido"
        ENVIADO = "ENVIADO", "Enviado"
        ENTREGADO = "ENTREGADO", "Entregado"
        LEIDO = "LEIDO", "Leído"
        FALLIDO = "FALLIDO", "Fallido"

    # =====================================================
    # CONVERSACIÓN
    # =====================================================

    conversacion = models.ForeignKey(
        Conversacion,
        on_delete=models.PROTECT,
        related_name="mensajes",
    )

    # =====================================================
    # ID DEL PROVEEDOR
    # =====================================================
    #
    # Ejemplo Meta:
    #
    #     wamid....
    # =====================================================

    external_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
    )

    # =====================================================
    # REMITENTE EXTERNO
    # =====================================================

    remitente = models.ForeignKey(
        Contacto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mensajes_enviados",
    )

    # =====================================================
    # MENSAJE
    # =====================================================

    direccion = models.CharField(
        max_length=50,
        choices=DireccionMensaje.choices,
        db_index=True,
    )

    tipo = models.CharField(
        max_length=50,
        choices=TipoMensaje.choices,
        default=TipoMensaje.TEXT,
        db_index=True,
    )

    texto_original = models.TextField(
        null=True,
        blank=True,
    )

    # =====================================================
    # ESTADO DE TRANSPORTE
    # =====================================================

    estado = models.CharField(
        max_length=50,
        choices=EstadoMensaje.choices,
        default=EstadoMensaje.PENDIENTE,
        db_index=True,
    )

    error_codigo = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )

    error_detalle = models.TextField(
        null=True,
        blank=True,
    )

    # =====================================================
    # FECHAS
    # =====================================================

    fecha_mensaje = models.DateTimeField(
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    # =====================================================
    # RESPUESTA
    # =====================================================

    respuesta_a = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="respuestas",
    )

    # =====================================================
    # METADATOS TÉCNICOS
    # =====================================================
    #
    # Payloads complementarios del proveedor.
    # No se utiliza para lógica de negocio.
    # =====================================================

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    # =====================================================
    # META
    # =====================================================

    class Meta:
        verbose_name = "Mensaje"
        verbose_name_plural = "Mensajes"

        ordering = [
            "fecha_mensaje",
            "pk",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "conversacion",
                    "external_id",
                ],
                condition=models.Q(
                    external_id__isnull=False,
                ),
                name=(
                    "unique_external_id_per_conversation"
                ),
            )
        ]

    # =====================================================
    # REPRESENTACIÓN
    # =====================================================

    def __str__(self):
        contenido = (
            self.texto_original
            or self.tipo
        )

        return (
            f"[{self.direccion}] "
            f"{contenido[:50]}"
        )


# =========================================================
# ARCHIVO MULTIMEDIA
# =========================================================


class ArchivoMultimedia(models.Model):
    """
    Archivo asociado a un mensaje.

    Puede representar:

        - imagen;
        - audio;
        - video;
        - PDF;
        - documento;
        - sticker;
        - etc.
    """

    mensaje = models.ForeignKey(
        Mensaje,
        on_delete=models.CASCADE,
        related_name="archivos_multimedia",
    )

    # Puede estar vacío temporalmente si primero recibimos
    # el media_id del proveedor y el archivo todavía no
    # ha sido descargado.
    archivo = models.FileField(
        upload_to="multimedia/%Y/%m/",
        null=True,
        blank=True,
    )

    # Ejemplo Meta:
    #
    #     media_id
    #
    identificador_externo = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
    )

    nombre_original = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    mime_type = models.CharField(
        max_length=127,
        null=True,
        blank=True,
    )

    size_bytes = models.BigIntegerField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Archivo multimedia"
        verbose_name_plural = "Archivos multimedia"

    def __str__(self):
        return (
            self.nombre_original
            or self.identificador_externo
            or f"Archivo #{self.pk}"
        )