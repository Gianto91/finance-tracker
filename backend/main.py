import os
from datetime import datetime
from email.utils import parsedate_to_datetime

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Cookie, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, HTMLResponse

import database
import email_parser
import gmail_scraper
import telegram_notifier
import auth

load_dotenv()

app = FastAPI(title="Hormiguita - Gestión de Gastos")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

database.init_db()
database.normalizar_categorias_existentes()


def obtener_user_id(request: Request) -> str:
    """Extrae user_id del JWT en el header Authorization."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return "legacy-user"
    token = auth_header.split(" ")[1]
    user_id = auth.verify_jwt_token(token)
    if not user_id:
        return "legacy-user"
    return user_id


def revisar_correos_nuevos():
    """Job que corre cada N minutos: trae correos, los parsea y guarda."""
    print(f"[{datetime.now()}] ✨ NUEVO: Revisando correos nuevos...")
    _reparar_gastos_anteriores()
    correos = gmail_scraper.obtener_correos_nuevos(database.gasto_ya_existe)
    guardados = 0
    descartados = 0

    for correo in correos:
        datos = email_parser.parsear_correo(correo["texto"])

        if not datos.get("es_gasto"):
            descartados += 1
            print(
                f"  -> Correo descartado: {correo['id']} | "
                f"asunto: {correo.get('asunto', '')}"
            )
            continue

        fecha_gasto = datos.get("fecha") or _fecha_del_correo(correo)
        if not _es_de_hoy(fecha_gasto):
            print(
                f"  -> Correo fuera de fecha: {correo['id']} | "
                f"asunto: {correo.get('asunto', '')} | fecha: {fecha_gasto}"
            )
            continue

        database.guardar_gasto(
            fecha=fecha_gasto,
            monto=datos["monto"],
            comercio=datos.get("comercio") or "Desconocido",
            categoria=datos.get("categoria") or "Otros",
            metodo=datos.get("metodo") or "Otro",
            email_id=correo["id"],
        )
        telegram_notifier.notificar_gasto(
            monto=datos["monto"],
            comercio=datos.get("comercio") or "Desconocido",
            categoria=datos.get("categoria") or "Otros",
            metodo=datos.get("metodo") or "Otro",
        )
        guardados += 1
        print(f"  -> Gasto guardado: S/ {datos['monto']} en {datos.get('comercio')}")

    print(
        f"Resumen de revisión: {guardados} guardados, "
        f"{descartados} descartados de {len(correos)} correos nuevos"
    )


def _reparar_gastos_anteriores():
    gastos = database.todos_los_gastos()
    if not gastos:
        return

    correos = gmail_scraper.obtener_correos_por_ids(
        [gasto["email_id"] for gasto in gastos]
    )
    reparados = 0
    for correo in correos:
        datos = email_parser.parsear_correo(correo["texto"])
        if not datos.get("es_gasto"):
            continue
        if not _es_de_hoy(datos.get("fecha")):
            continue
        database.actualizar_gasto(
            email_id=correo["id"],
            monto=datos["monto"],
            comercio=datos.get("comercio") or "Desconocido",
            categoria=datos.get("categoria") or "Otros",
            metodo=datos.get("metodo") or "Otro",
            fecha=datos.get("fecha") or _fecha_del_correo(correo),
        )
        reparados += 1
    print(f"Reparación de movimientos anteriores: {reparados} actualizados")


def _fecha_del_correo(correo):
    from zoneinfo import ZoneInfo
    try:
        dt = parsedate_to_datetime(correo["fecha"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("America/Lima")).replace(tzinfo=None).isoformat()
    except (KeyError, TypeError, ValueError):
        return datetime.now(ZoneInfo("America/Lima")).isoformat()


def _es_de_hoy(fecha):
    if not fecha:
        return True
    try:
        return datetime.fromisoformat(fecha).date() == datetime.now().date()
    except ValueError:
        return False


# Programa el job para que corra solo, cada X minutos
scheduler = BackgroundScheduler()
intervalo = int(os.environ.get("SCAN_INTERVAL_MINUTES", 2))  # 2 minutos es el estándar
scheduler.add_job(revisar_correos_nuevos, "interval", minutes=intervalo)
scheduler.start()


@app.get("/api/gastos/dia")
def gastos_dia(user_id: str = Depends(obtener_user_id)):
    from datetime import datetime
    hoy = datetime.now().date().isoformat()
    gastos = database.todos_los_gastos(user_id)
    return [g for g in gastos if g["fecha"].startswith(hoy)]


@app.get("/api/gastos/semana")
def gastos_semana(user_id: str = Depends(obtener_user_id)):
    return database.resumen_semana(user_id)


@app.get("/api/gastos/mes")
def gastos_mes(user_id: str = Depends(obtener_user_id)):
    return database.resumen_mes(user_id)


@app.get("/api/gastos/todos")
def gastos_todos(user_id: str = Depends(obtener_user_id)):
    return database.todos_los_gastos(user_id)


@app.post("/api/revisar-ahora")
def revisar_ahora():
    """Dispara manualmente una revisión de correos (botón del dashboard)."""
    revisar_correos_nuevos()
    return {"status": "ok"}


@app.post("/api/gastos/crear")
def crear_gasto(monto: float, comercio: str, categoria: str = "Otros", metodo: str = "Otro", user_id: str = Depends(obtener_user_id)):
    """Crea un gasto manualmente (útil en modo demo sin Gmail)."""
    database.guardar_gasto(
        fecha=datetime.now().isoformat(),
        monto=monto,
        comercio=comercio,
        categoria=categoria,
        metodo=metodo,
        email_id=f"manual-{datetime.now().timestamp()}",
        user_id=user_id
    )
    return {"status": "ok", "monto": monto, "comercio": comercio}


@app.put("/api/gastos/{gasto_id}")
def editar_gasto(gasto_id: int, monto: float = None, comercio: str = None,
                  categoria: str = None, metodo: str = None, user_id: str = Depends(obtener_user_id)):
    """Edita un gasto existente."""
    database.actualizar_gasto_por_id(gasto_id, monto, comercio, categoria, metodo)
    return {"status": "ok", "gasto_id": gasto_id}


@app.delete("/api/gastos/{gasto_id}")
def eliminar_gasto(gasto_id: int, user_id: str = Depends(obtener_user_id)):
    """Elimina un gasto."""
    database.eliminar_gasto(gasto_id, user_id)
    return {"status": "ok", "gasto_id": gasto_id}


@app.post("/api/admin/borrar-todos")
def borrar_todos():
    """⚠️ SOLO PARA ADMIN: Borra todos los gastos. USAR CON CUIDADO."""
    conn = database.get_connection()
    conn.execute("DELETE FROM gastos")
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Todos los gastos fueron eliminados"}


@app.get("/api/gastos/buscar")
def buscar_gastos(q: str = "", categoria: str = "", desde: str = "", hasta: str = "", user_id: str = Depends(obtener_user_id)):
    """Busca y filtra gastos por comercio, categoría y rango de fechas."""
    return database.buscar_gastos(q, categoria, desde, hasta, user_id)


@app.get("/api/auth/login")
def auth_login():
    """Redirige a Google OAuth para que el usuario se autentique."""
    client_id = auth.GOOGLE_CLIENT_ID
    redirect_uri = auth.GOOGLE_REDIRECT_URI
    scope = "openid%20profile%20email"

    if not client_id:
        return {"error": "GOOGLE_CLIENT_ID no configurado"}

    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={redirect_uri}&"
        f"response_type=code&"
        f"scope={scope}"
    )
    return RedirectResponse(url=google_auth_url)


@app.get("/api/auth/callback")
def auth_callback(code: str):
    """Callback de Google OAuth. Intercambia el código por un JWT token."""
    result = auth.handle_oauth_callback(code)
    if not result:
        return {"error": "Error durante la autenticación"}

    user_id, jwt_token = result

    # Retornar HTML que guarda el token en localStorage y redirige al dashboard
    html = f"""
    <html>
        <head>
            <title>Autenticando...</title>
        </head>
        <body>
            <script>
                localStorage.setItem('jwt_token', '{jwt_token}');
                window.location.href = '/';
            </script>
        </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/api/auth/logout")
def auth_logout():
    """Logout: el cliente elimina el JWT token."""
    return {"status": "ok", "message": "Sesión cerrada. Elimina el token del cliente."}


# Sirve el dashboard (index.html) en la raíz
app.mount("/", StaticFiles(directory="static", html=True), name="static")
