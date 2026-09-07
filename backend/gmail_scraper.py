"""
Se conecta a tu Gmail (solo lectura) y trae los correos de notificaciones
bancarias que todavía no hemos procesado.

La primera vez que corras esto se va a abrir el navegador para que
autorices el acceso (login con Google). Luego guarda un token local
(token.json) para no pedirte login cada vez.
"""
import base64
import json
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
    creds = None

    print(f"DEBUG: Variables de entorno disponibles: {list(os.environ.keys())[:10]}")
    token_json_env = os.environ.get("GOOGLE_TOKEN_JSON")
    print(f"DEBUG: token_json_env = {str(token_json_env)[:50] if token_json_env else 'None'}")

    if token_json_env:
        try:
            print("📌 Leyendo token desde variable de entorno...")
            creds = Credentials.from_authorized_user_info(
                json.loads(token_json_env), SCOPES
            )
            print("✅ Token cargado desde env")
        except Exception as e:
            print(f"❌ Error al cargar token: {e}")
            return None
    elif TOKEN_PATH.exists():
        print("📌 Leyendo token desde archivo local...")
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        print("✅ Token cargado desde archivo")
    else:
        print("❌ No hay token (env ni local)")
        return None

    if not creds or not creds.valid:
        print(f"⚠️  Credenciales inválidas. Expired: {creds.expired if creds else 'N/A'}")
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refrescando token...")
            creds.refresh(Request())
            print("✅ Token refrescado")
        else:
            print("❌ No se puede refrescar, necesita re-autorizar")
            return None
    else:
        print("✅ Credenciales válidas")

    try:
        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        print(f"❌ Error al construir servicio de Gmail: {e}")
        return None


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
    print(f"DEBUG: Query Gmail: {query}")
    resultado = service.users().messages().list(userId="me", q=query).execute()
    mensajes = resultado.get("messages", [])
    print(f"DEBUG: Se encontraron {len(mensajes)} mensajes en Gmail con la búsqueda")

    correos = []
    for m in mensajes:
        if ya_procesados_fn(m["id"]):
            print(f"DEBUG: Email {m['id']} ya fue procesado, saltando")
            continue
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="full"
        ).execute()
        fecha_gmail = int(msg.get("internalDate", "0")) / 1000
        if fecha_gmail:
            fecha_local = datetime.fromtimestamp(
                fecha_gmail, ZoneInfo("America/Lima")
            ).date()
            hoy = datetime.now(ZoneInfo("America/Lima")).date()
            print(f"DEBUG: Email {m['id']}: fecha_local={fecha_local}, hoy={hoy}")
            if fecha_local != hoy:
                print(f"DEBUG: Email {m['id']} es de otro día, descartando")
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
