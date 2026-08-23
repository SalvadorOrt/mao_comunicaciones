import copy
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from organizacion.models import Sucursal

from comunicaciones.models import (
    ArchivoMultimedia,
    Contacto,
    Conversacion,
    IdentidadContactoExterna,
    Mensaje,
    NumeroCanal,
)

from comunicaciones.services import (
    crear_conversacion,
    obtener_o_crear_contacto_whatsapp,
)

from integraciones.whatsapp.client import (
    enviar_mensaje_texto_meta,
)

from integraciones.whatsapp.parser import (
    parse_whatsapp_payload,
)

from integraciones.whatsapp.services import (
    enviar_mensaje_saliente,
)


# =========================================================
# CONFIGURACIÓN DE PRUEBAS
# =========================================================


@override_settings(
    META_VERIFY_TOKEN="verify_test_123",
    META_APP_SECRET="app_secret_test_456",
    META_ACCESS_TOKEN="access_token_test_789",
    META_API_VERSION="v20.0",
)
class IntegracionWhatsAppTests(TestCase):

    def setUp(self):

        # =====================================================
        # SUCURSAL
        # =====================================================

        self.sucursal = Sucursal.objects.create(
            erp_sucursal_id=999,
            codigo="TEST",
            nombre="Sucursal Test",
            activa=True,
        )

        # =====================================================
        # CANAL WHATSAPP
        # =====================================================

        self.canal = NumeroCanal.objects.create(
            nombre="WhatsApp Test",
            numero_telefonico="+593981577789",
            identificador_externo="999999999",
            sucursal=self.sucursal,
            tipo="CORPORATIVO",
            activo=True,
        )

        # =====================================================
        # CONTACTO
        # =====================================================

        self.contacto = Contacto.objects.create(
            nombre_perfil="Cliente Prueba",
            numero_telefonico="+593990000001",
        )

        # =====================================================
        # IDENTIDAD META
        # =====================================================

        self.identidad = (
            IdentidadContactoExterna.objects.create(
                contacto=self.contacto,
                proveedor="META",
                identificador_externo="593990000001",
            )
        )

        # =====================================================
        # CONVERSACIÓN
        # =====================================================

        self.conversacion = crear_conversacion(
            numero_canal=self.canal,
            sucursal=self.sucursal,
            tipo="INDIVIDUAL",
            privacidad="SIN_CLASIFICAR",
            contacto=self.contacto,
        )

        self.webhook_url = reverse(
            "whatsapp:webhook"
        )

    # =========================================================
    # UTILIDADES
    # =========================================================

    def _firma_meta(self, body: bytes) -> str:

        digest = hmac.new(
            b"app_secret_test_456",
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        return f"sha256={digest}"

    def _post_webhook(self, payload):

        body = json.dumps(
            payload
        ).encode("utf-8")

        return self.client.post(
            self.webhook_url,
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=self._firma_meta(body),
        )

    def _payload_texto(
        self,
        *,
        wamid="wamid.TEST.IN.001",
        texto="Hola desde prueba",
        wa_id="593990000001",
        phone_number_id="999999999",
    ):

        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_TEST",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number":
                                        "593981577789",
                                    "phone_number_id":
                                        phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "profile": {
                                            "name":
                                                "Cliente Prueba",
                                        },
                                        "wa_id":
                                            wa_id,
                                    }
                                ],
                                "messages": [
                                    {
                                        "from":
                                            wa_id,
                                        "id":
                                            wamid,
                                        "timestamp":
                                            "1787461200",
                                        "type":
                                            "text",
                                        "text": {
                                            "body":
                                                texto,
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

    def _payload_status(
        self,
        *,
        wamid,
        status,
        phone_number_id="999999999",
    ):

        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_TEST",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product":
                                    "whatsapp",
                                "metadata": {
                                    "phone_number_id":
                                        phone_number_id,
                                },
                                "statuses": [
                                    {
                                        "id":
                                            wamid,
                                        "status":
                                            status,
                                        "timestamp":
                                            "1787461200",
                                        "recipient_id":
                                            "593990000001",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

    # =========================================================
    # WEBHOOK - VERIFICACIÓN GET
    # =========================================================

    def test_webhook_verificacion_correcta(self):

        response = self.client.get(
            self.webhook_url,
            {
                "hub.mode": "subscribe",
                "hub.verify_token":
                    "verify_test_123",
                "hub.challenge":
                    "CHALLENGE_TEST",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.content.decode(),
            "CHALLENGE_TEST",
        )

    def test_webhook_verificacion_token_incorrecto(self):

        response = self.client.get(
            self.webhook_url,
            {
                "hub.mode": "subscribe",
                "hub.verify_token":
                    "token_incorrecto",
                "hub.challenge":
                    "CHALLENGE_TEST",
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    # =========================================================
    # WEBHOOK - FIRMA HMAC
    # =========================================================

    def test_webhook_rechaza_firma_incorrecta(self):

        payload = self._payload_texto()

        body = json.dumps(
            payload
        ).encode("utf-8")

        response = self.client.post(
            self.webhook_url,
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=(
                "sha256=firma_incorrecta"
            ),
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_webhook_acepta_firma_correcta(self):

        payload = {
            "object": "whatsapp_business_account",
            "entry": [],
        }

        response = self._post_webhook(
            payload
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    # =========================================================
    # RECEPCIÓN DE MENSAJES
    # =========================================================

    def test_recibe_y_guarda_mensaje_entrante(self):

        # Evitamos utilizar la conversación creada en setUp
        # para comprobar creación completa desde webhook.

        self.conversacion.delete()
        self.identidad.delete()
        self.contacto.delete()

        payload = self._payload_texto(
            wamid="wamid.TEST.IN.100",
            texto="Hola MAO",
        )

        response = self._post_webhook(
            payload
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        mensaje = Mensaje.objects.get(
            external_id="wamid.TEST.IN.100"
        )

        self.assertEqual(
            mensaje.texto_original,
            "Hola MAO",
        )

        self.assertEqual(
            mensaje.direccion,
            Mensaje.DireccionMensaje.ENTRANTE,
        )

        self.assertEqual(
            mensaje.estado,
            Mensaje.EstadoMensaje.RECIBIDO,
        )

        self.assertEqual(
            mensaje.conversacion.numero_canal,
            self.canal,
        )

        self.assertTrue(
            mensaje.conversacion.pendiente
        )

    # =========================================================
    # IDEMPOTENCIA
    # =========================================================

    def test_webhook_no_duplica_mismo_wamid(self):

        payload = self._payload_texto(
            wamid="wamid.TEST.DUPLICADO.001",
        )

        response_1 = self._post_webhook(
            payload
        )

        response_2 = self._post_webhook(
            payload
        )

        self.assertEqual(
            response_1.status_code,
            200,
        )

        self.assertEqual(
            response_2.status_code,
            200,
        )

        cantidad = Mensaje.objects.filter(
            external_id="wamid.TEST.DUPLICADO.001"
        ).count()

        self.assertEqual(
            cantidad,
            1,
        )

    # =========================================================
    # CANAL DESCONOCIDO
    # =========================================================

    def test_webhook_ignora_phone_number_id_desconocido(self):

        payload = self._payload_texto(
            wamid="wamid.TEST.UNKNOWN.CHANNEL",
            phone_number_id="111111111111111",
        )

        response = self._post_webhook(
            payload
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        existe = Mensaje.objects.filter(
            external_id=(
                "wamid.TEST.UNKNOWN.CHANNEL"
            )
        ).exists()

        self.assertFalse(
            existe
        )

    # =========================================================
    # CONTACTO / IDENTIDAD META
    # =========================================================

    def test_reutiliza_contacto_por_identidad_meta(self):

        contacto, creado = (
            obtener_o_crear_contacto_whatsapp(
                wa_id="593990000001",
                nombre_perfil="Otro nombre",
            )
        )

        self.assertFalse(
            creado
        )

        self.assertEqual(
            contacto.pk,
            self.contacto.pk,
        )

    def test_crea_contacto_e_identidad_meta(self):

        contacto, creado = (
            obtener_o_crear_contacto_whatsapp(
                wa_id="593990000777",
                nombre_perfil="Nuevo Cliente",
            )
        )

        self.assertTrue(
            creado
        )

        identidad = (
            IdentidadContactoExterna.objects.get(
                proveedor="META",
                identificador_externo=
                    "593990000777",
            )
        )

        self.assertEqual(
            identidad.contacto,
            contacto,
        )

    # =========================================================
    # CONVERSACIÓN
    # =========================================================

    def test_reutiliza_conversacion_individual(self):

        conversacion_2 = crear_conversacion(
            numero_canal=self.canal,
            sucursal=self.sucursal,
            tipo="INDIVIDUAL",
            privacidad="SIN_CLASIFICAR",
            contacto=self.contacto,
        )

        self.assertEqual(
            conversacion_2.pk,
            self.conversacion.pk,
        )

    # =========================================================
    # ESTADOS DE MENSAJES
    # =========================================================

    def test_estado_enviado_entregado_leido(self):

        mensaje = Mensaje.objects.create(
            conversacion=self.conversacion,
            external_id="wamid.TEST.OUT.STATUS",
            direccion=(
                Mensaje.DireccionMensaje.SALIENTE
            ),
            tipo=Mensaje.TipoMensaje.TEXT,
            texto_original="Mensaje prueba",
            estado=Mensaje.EstadoMensaje.ENVIADO,
            fecha_mensaje=timezone.now(),
        )

        # -----------------------------------------------------
        # DELIVERED
        # -----------------------------------------------------

        response = self._post_webhook(
            self._payload_status(
                wamid="wamid.TEST.OUT.STATUS",
                status="delivered",
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        mensaje.refresh_from_db()

        self.assertEqual(
            mensaje.estado,
            Mensaje.EstadoMensaje.ENTREGADO,
        )

        # -----------------------------------------------------
        # READ
        # -----------------------------------------------------

        response = self._post_webhook(
            self._payload_status(
                wamid="wamid.TEST.OUT.STATUS",
                status="read",
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        mensaje.refresh_from_db()

        self.assertEqual(
            mensaje.estado,
            Mensaje.EstadoMensaje.LEIDO,
        )

    def test_estado_no_regresa_de_leido_a_enviado(self):

        mensaje = Mensaje.objects.create(
            conversacion=self.conversacion,
            external_id="wamid.TEST.MONOTONICO",
            direccion=(
                Mensaje.DireccionMensaje.SALIENTE
            ),
            tipo=Mensaje.TipoMensaje.TEXT,
            texto_original="Mensaje prueba",
            estado=Mensaje.EstadoMensaje.LEIDO,
            fecha_mensaje=timezone.now(),
        )

        self._post_webhook(
            self._payload_status(
                wamid="wamid.TEST.MONOTONICO",
                status="sent",
            )
        )

        mensaje.refresh_from_db()

        self.assertEqual(
            mensaje.estado,
            Mensaje.EstadoMensaje.LEIDO,
        )

    def test_estado_fallido_se_registra(self):

        mensaje = Mensaje.objects.create(
            conversacion=self.conversacion,
            external_id="wamid.TEST.FAILED",
            direccion=(
                Mensaje.DireccionMensaje.SALIENTE
            ),
            tipo=Mensaje.TipoMensaje.TEXT,
            texto_original="Mensaje prueba",
            estado=Mensaje.EstadoMensaje.ENVIADO,
            fecha_mensaje=timezone.now(),
        )

        self._post_webhook(
            self._payload_status(
                wamid="wamid.TEST.FAILED",
                status="failed",
            )
        )

        mensaje.refresh_from_db()

        self.assertEqual(
            mensaje.estado,
            Mensaje.EstadoMensaje.FALLIDO,
        )

    # =========================================================
    # PARSER
    # =========================================================

    def test_parser_texto(self):

        payload = self._payload_texto(
            wamid="wamid.TEST.PARSER",
            texto="Prueba parser",
        )

        eventos = parse_whatsapp_payload(
            payload
        )

        self.assertEqual(
            len(eventos),
            1,
        )

        evento = eventos[0]

        self.assertEqual(
            evento["tipo_evento"],
            "message",
        )

        self.assertEqual(
            evento["texto_original"],
            "Prueba parser",
        )

        self.assertEqual(
            evento["phone_number_id"],
            "999999999",
        )

    def test_parser_tipo_desconocido(self):

        payload = self._payload_texto()

        payload = copy.deepcopy(
            payload
        )

        mensaje = (
            payload["entry"][0]
            ["changes"][0]
            ["value"]["messages"][0]
        )

        mensaje["type"] = "tipo_no_soportado"

        mensaje.pop(
            "text",
            None,
        )

        eventos = parse_whatsapp_payload(
            payload
        )

        self.assertEqual(
            len(eventos),
            1,
        )

        self.assertEqual(
            eventos[0]["tipo"],
            Mensaje.TipoMensaje.UNKNOWN,
        )

    # =========================================================
    # CLIENTE META
    # =========================================================

    @patch(
        "integraciones.whatsapp.client.requests.post"
    )
    def test_cliente_meta_envia_texto(
        self,
        mock_post,
    ):

        response_mock = MagicMock()

        response_mock.json.return_value = {
            "messaging_product": "whatsapp",
            "contacts": [
                {
                    "input":
                        "593990000001",
                    "wa_id":
                        "593990000001",
                }
            ],
            "messages": [
                {
                    "id":
                        "wamid.TEST.CLIENT.001",
                }
            ],
        }

        response_mock.raise_for_status.return_value = (
            None
        )

        mock_post.return_value = (
            response_mock
        )

        resultado = enviar_mensaje_texto_meta(
            phone_number_id="999999999",
            wa_id="593990000001",
            text="Hola desde MAO Comunicaciones",
        )

        self.assertTrue(
            resultado["success"]
        )

        self.assertEqual(
            resultado["wamid"],
            "wamid.TEST.CLIENT.001",
        )

        mock_post.assert_called_once()

    # =========================================================
    # SERVICIO DE ENVÍO SALIENTE
    # =========================================================

    @patch(
        "integraciones.whatsapp.services."
        "enviar_mensaje_texto_meta"
    )
    def test_envio_saliente_persiste_wamid(
        self,
        mock_enviar,
    ):

        mock_enviar.return_value = {
            "success": True,
            "wamid":
                "wamid.TEST.OUT.001",
        }

        mensaje = enviar_mensaje_saliente(
            self.conversacion,
            "Hola cliente",
        )

        self.assertEqual(
            mensaje.external_id,
            "wamid.TEST.OUT.001",
        )

        self.assertEqual(
            mensaje.estado,
            Mensaje.EstadoMensaje.ENVIADO,
        )

        self.assertEqual(
            mensaje.direccion,
            Mensaje.DireccionMensaje.SALIENTE,
        )

        self.assertEqual(
            mensaje.texto_original,
            "Hola cliente",
        )

        mock_enviar.assert_called_once_with(
            phone_number_id="999999999",
            wa_id="593990000001",
            text="Hola cliente",
        )

    @patch(
        "integraciones.whatsapp.services."
        "enviar_mensaje_texto_meta"
    )
    def test_fallo_meta_no_persiste_mensaje(
        self,
        mock_enviar,
    ):

        mock_enviar.return_value = {
            "error": "Network Error",
        }

        cantidad_antes = (
            Mensaje.objects.count()
        )

        with self.assertRaises(Exception):

            enviar_mensaje_saliente(
                self.conversacion,
                "Mensaje que fallará",
            )

        cantidad_despues = (
            Mensaje.objects.count()
        )

        self.assertEqual(
            cantidad_antes,
            cantidad_despues,
        )

    @patch(
        "integraciones.whatsapp.services."
        "enviar_mensaje_texto_meta"
    )
    def test_meta_sin_wamid_no_persiste_mensaje(
        self,
        mock_enviar,
    ):

        mock_enviar.return_value = {
            "success": True,
            "wamid": None,
        }

        cantidad_antes = (
            Mensaje.objects.count()
        )

        with self.assertRaises(Exception):

            enviar_mensaje_saliente(
                self.conversacion,
                "Mensaje sin wamid",
            )

        cantidad_despues = (
            Mensaje.objects.count()
        )

        self.assertEqual(
            cantidad_antes,
            cantidad_despues,
        )

    # =========================================================
    # MULTIMEDIA ENTRANTE
    # =========================================================

    @patch(
        "integraciones.whatsapp.views."
        "descargar_archivo_fisico"
    )
    @patch(
        "integraciones.whatsapp.views."
        "obtener_url_descarga_media"
    )
    def test_guarda_multimedia_entrante(
        self,
        mock_url,
        mock_descargar,
    ):

        mock_url.return_value = (
            "https://meta.test/media/123"
        )

        mock_descargar.return_value = (
            b"contenido-imagen-prueba",
            "image/jpeg",
        )

        payload = {
            "object":
                "whatsapp_business_account",

            "entry": [
                {
                    "id":
                        "WABA_TEST",

                    "changes": [
                        {
                            "field":
                                "messages",

                            "value": {
                                "metadata": {
                                    "phone_number_id":
                                        "999999999",
                                },

                                "contacts": [
                                    {
                                        "profile": {
                                            "name":
                                                "Cliente Prueba",
                                        },

                                        "wa_id":
                                            "593990000001",
                                    }
                                ],

                                "messages": [
                                    {
                                        "from":
                                            "593990000001",

                                        "id":
                                            "wamid.TEST.IMAGE.001",

                                        "timestamp":
                                            "1787461200",

                                        "type":
                                            "image",

                                        "image": {
                                            "id":
                                                "MEDIA_TEST_001",

                                            "mime_type":
                                                "image/jpeg",

                                            "caption":
                                                "Foto prueba",
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        response = self._post_webhook(
            payload
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        mensaje = Mensaje.objects.get(
            external_id=
                "wamid.TEST.IMAGE.001"
        )

        archivo = ArchivoMultimedia.objects.get(
            mensaje=mensaje
        )

        self.assertEqual(
            archivo.identificador_externo,
            "MEDIA_TEST_001",
        )

        self.assertEqual(
            archivo.mime_type,
            "image/jpeg",
        )

        self.assertGreater(
            archivo.size_bytes,
            0,
        )