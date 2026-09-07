"""
Se conecta a tu Gmail (solo lectura) y trae los correos de notificaciones
bancarias que todavía no hemos procesado.

La primera vez que corras esto se va a abrir el navegador para que
autorices el acceso (login con Google). Luego guarda un token local
(token.json) para no pedirte login cada vez.
"""
import base64
import os
from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_PATH = Path(__file__).parent / "token.json"
CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"

# Ajusta esta lista a los remitentes de tus bancos/billeteras.
REMITENTES_BANCARIOS = [
    "notificaciones@notificacionesbcp.com.pe",
    "notificaciones@yape.pe",
    "no-reply@ligo.pe",
    "servicioalcliente@netinterbank.com.pe",
]

# La búsqueda se construye para el día actual al momento de revisar.


def _query_hoy():
    remitentes = " OR ".join(REMITENTES_BANCARIOS)
    return f"from:({remitentes}) newer_than:2d"


def _get_service():
    if not CREDENTIALS_PATH.exists():
        return None
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


class _TextoHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []
        self.ignorar = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.ignorar += 1

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self.ignorar:
            self.ignorar -= 1

    def handle_data(self, data):
        if not self.ignorar:
            self.partes.append(data)

    def texto(self):
        return " ".join(self.partes)


def _decodificar(data) -> str:
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")


def _html_a_texto(html) -> str:
    parser = _TextoHTML()
    parser.feed(html)
    parser.close()
    return parser.texto()


def _extraer_texto(payload) -> str:
    """Extrae texto de partes MIME anidadas y convierte HTML a texto plano."""
    mime_type = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if data and mime_type == "text/plain":
        return _decodificar(data)
    if data and mime_type == "text/html":
        return _html_a_texto(_decodificar(data))

    texto_plano = ""
    for part in payload.get("parts", []):
        texto = _extraer_texto(part)
        if not texto:
            continue
        if part.get("mimeType") == "text/html":
            return texto
        if not texto_plano:
            texto_plano = texto
    return texto_plano


def obtener_correos_nuevos(ya_procesados_fn):
    """
    Devuelve una lista de dicts: {id, asunto, remitente, texto}
    para correos bancarios que aún no están en la base de datos.
    ya_procesados_fn: función que recibe un email_id y devuelve True/False
    """
    service = _get_service()
    if not service:
        print("⚠️  credentials.json no configurado. Modo demo: sin scraping de Gmail")
        return []
    query = _query_hoy()
    resultado = service.users().messages().list(userId="me", q=query).execute()
    mensajes = resultado.get("messages", [])

    correos = []
    for m in mensajes:
        if ya_procesados_fn(m["id"]):
            continue
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="full"
        ).execute()
        fecha_gmail = int(msg.get("internalDate", "0")) / 1000
        if fecha_gmail:
            fecha_local = datetime.fromtimestamp(
                fecha_gmail, ZoneInfo("America/Lima")
            ).date()
            if fecha_local != datetime.now(ZoneInfo("America/Lima")).date():
                continue
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        texto = _extraer_texto(msg["payload"])
        correos.append({
            "id": m["id"],
            "asunto": headers.get("Subject", ""),
            "remitente": headers.get("From", ""),
            "fecha": headers.get("Date", ""),
            "texto": texto,
        })
    print(f"DEBUG: encontrados {len(correos)} correos con la búsqueda: {query}")
    return correos


def obtener_correos_por_ids(ids):
    """Vuelve a obtener mensajes concretos para reparar datos ya guardados."""
    if not ids:
        return []

    service = _get_service()
    if not service:
        return []
    correos = []
    for email_id in ids:
        msg = service.users().messages().get(
            userId="me", id=email_id, format="full"
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        correos.append({
            "id": email_id,
            "asunto": headers.get("Subject", ""),
            "remitente": headers.get("From", ""),
            "fecha": headers.get("Date", ""),
            "texto": _extraer_texto(msg["payload"]),
        })
    return correos
