import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
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

app = FastAPI(title="Hormiguita - Gestión de Gastos v2")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# Middleware para desactivar caché en desarrollo
@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

database.init_db()
database.normalizar_categorias_existentes()


def obtener_user_id(request: Request) -> str:
    """Extrae user_id del JWT en el header Authorization."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        print("⚠️ No hay Authorization header")
        return "legacy-user"
    token = auth_header.split(" ")[1]
    user_id = auth.verify_jwt_token(token)
    print(f"DEBUG: Token={token[:20]}..., user_id={user_id}")
    if not user_id:
        print("⚠️ Token inválido")
        return "legacy-user"
    print(f"✅ Usando user_id={user_id}")
    return user_id


def revisar_correos_nuevos(user_id: str = "legacy-user"):
    """Job que corre cada N minutos: trae correos, los parsea y guarda."""
    print(f"[{datetime.now()}] ✨ NUEVO: Revisando correos para user_id={user_id}...")
    _reparar_gastos_anteriores(user_id)

    # Obtener el token del usuario de la BD
    user = database.get_user(user_id)
    token_json_str = None
    if user and user.get("google_token"):
        token_json_str = user["google_token"]
        print(f"✅ Usando token del usuario {user_id}")
    else:
        print(f"⚠️  No hay token para {user_id}, intentando token global")

    # Crear callback que filtre por user_id
    def gasto_existe_para_user(email_id):
        return database.gasto_ya_existe(email_id, user_id)

    correos = gmail_scraper.obtener_correos_nuevos(gasto_existe_para_user, token_json_str)
    print(f"📧 Se encontraron {len(correos)} correos nuevos")
    guardados = 0
    descartados = 0
    fuera_fecha = 0

    for correo in correos:
        datos = email_parser.parsear_correo(correo["texto"])

        if not datos.get("es_gasto"):
            descartados += 1
            print(
                f"  -> ❌ Correo descartado (no es gasto): {correo['id']} | "
                f"asunto: {correo.get('asunto', '')}"
            )
            continue

        fecha_gasto = datos.get("fecha") or _fecha_del_correo(correo)
        print(f"  -> Fecha extraída: {fecha_gasto}")
        if not _es_de_hoy(fecha_gasto):
            fuera_fecha += 1
            print(
                f"  -> ⏰ Correo fuera de fecha (hoy={datetime.now(ZoneInfo('America/Lima')).date()}): {correo['id']} | "
                f"fecha: {fecha_gasto}"
            )
            continue

        database.guardar_gasto(
            fecha=fecha_gasto,
            monto=datos["monto"],
            comercio=datos.get("comercio") or "Desconocido",
            categoria=datos.get("categoria") or "Otros",
            metodo=datos.get("metodo") or "Otro",
            email_id=correo["id"],
            user_id=user_id,
        )
        telegram_notifier.notificar_gasto(
            monto=datos["monto"],
            comercio=datos.get("comercio") or "Desconocido",
            categoria=datos.get("categoria") or "Otros",
            metodo=datos.get("metodo") or "Otro",
        )
        guardados += 1
        print(f"  -> ✅ Gasto guardado: S/ {datos['monto']} en {datos.get('comercio')}")

    print(
        f"Resumen: {guardados} guardados, {descartados} no-gastos, {fuera_fecha} fuera de fecha de {len(correos)} correos"
    )


def _reparar_gastos_anteriores(user_id: str = "legacy-user"):
    gastos = database.todos_los_gastos(user_id)
    if not gastos:
        return

    # Obtener el token del usuario
    user = database.get_user(user_id)
    token_json_str = None
    if user and user.get("google_token"):
        token_json_str = user["google_token"]

    # Solo reparar gastos con email_id válido de Gmail (no gastos manuales con "manual-" prefix)
    email_ids = [gasto["email_id"] for gasto in gastos if gasto.get("email_id") and not gasto["email_id"].startswith("manual-")]
    if not email_ids:
        return

    correos = gmail_scraper.obtener_correos_por_ids(email_ids, token_json_str)
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
        from zoneinfo import ZoneInfo
        fecha_dt = datetime.fromisoformat(fecha).date()
        hoy = datetime.now(ZoneInfo("America/Lima")).date()
        return fecha_dt == hoy
    except ValueError:
        return False


def revisar_todos_los_usuarios():
    """Revisa correos para TODOS los usuarios que tienen token de Gmail."""
    conn = database.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, google_token FROM users WHERE google_token IS NOT NULL")
    usuarios = cur.fetchall()
    cur.close()
    conn.close()

    if not usuarios:
        print("⚠️ No hay usuarios con token de Gmail para revisar")
        return

    print(f"📧 Revisando correos para {len(usuarios)} usuarios")
    for usuario in usuarios:
        try:
            revisar_correos_nuevos(usuario[0])  # usuario[0] es el id
        except Exception as e:
            print(f"❌ Error scrappeando para usuario {usuario[0]}: {e}")

# Programa el job para que corra solo, cada X minutos
scheduler = BackgroundScheduler()
intervalo = int(os.environ.get("SCAN_INTERVAL_MINUTES", 2))  # 2 minutos es el estándar
scheduler.add_job(revisar_todos_los_usuarios, "interval", minutes=intervalo)
scheduler.start()


@app.get("/api/gastos/dia")
def gastos_dia(user_id: str = Depends(obtener_user_id)):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    hoy = datetime.now(ZoneInfo("America/Lima")).date().isoformat()
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


@app.get("/api/insights")
def insights(user_id: str = Depends(obtener_user_id)):
    """Retorna insights: promedio diario, proyección, alertas."""
    return database.obtener_insights(user_id)


@app.post("/api/budget-limit")
def set_budget(monto: float, user_id: str = Depends(obtener_user_id)):
    """Establece el límite mensual de presupuesto."""
    if monto <= 0:
        return {"status": "error", "message": "El límite debe ser mayor a 0"}
    database.set_budget_limit(user_id, monto)
    return {"status": "ok", "message": f"Límite establecido en S/ {monto:.2f}"}


@app.get("/api/hormiguitas")
def hormiguitas(user_id: str = Depends(obtener_user_id)):
    """Retorna gastos hormiga (< S/5) del día actual."""
    return database.detectar_gastos_hormiga(user_id)


@app.get("/api/recurrentes")
def recurrentes(user_id: str = Depends(obtener_user_id)):
    """Retorna gastos recurrentes detectados (últimos 3 meses)."""
    return database.detectar_gastos_recurrentes(user_id)


@app.post("/api/revisar-ahora")
def revisar_ahora(user_id: str = Depends(obtener_user_id)):
    """Dispara manualmente una revisión de correos (botón del dashboard)."""
    print(f"🔍 /revisar-ahora: Revisando para user_id={user_id}")

    # Verificar si el usuario tiene token de Gmail
    user = database.get_user(user_id)

    if not user:
        return {"status": "error", "message": "Usuario no encontrado"}

    if not user.get("google_token"):
        return {"status": "error", "message": "Necesitas conectar tu Gmail para scrapear. Vuelve a iniciar sesión."}

    # Ejecutar en thread separado para responder inmediatamente
    thread = threading.Thread(target=revisar_correos_nuevos, args=(user_id,), daemon=True)
    thread.start()
    return {"status": "ok", "message": "Revisando correos... (checa el dashboard en unos segundos)"}



@app.post("/api/gastos/crear")
def crear_gasto(monto: float, comercio: str, categoria: str = "Otros", metodo: str = "Otro", user_id: str = Depends(obtener_user_id)):
    """Crea un gasto manualmente (útil en modo demo sin Gmail)."""
    from zoneinfo import ZoneInfo
    ahora_lima = datetime.now(ZoneInfo("America/Lima"))
    database.guardar_gasto(
        fecha=ahora_lima.isoformat(),
        monto=monto,
        comercio=comercio,
        categoria=categoria,
        metodo=metodo,
        email_id=f"manual-{ahora_lima.timestamp()}",
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
    cur = conn.cursor()
    cur.execute("DELETE FROM gastos")
    conn.commit()
    cur.close()
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
    # Agregar scope de Gmail para que cada usuario pueda scrapear sus propios emails
    scope = "openid%20profile%20email%20https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly"

    if not client_id:
        return {"error": "GOOGLE_CLIENT_ID no configurado"}

    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={redirect_uri}&"
        f"response_type=code&"
        f"scope={scope}&"
        f"access_type=offline"
    )
    return RedirectResponse(url=google_auth_url)


@app.get("/api/auth/callback")
def auth_callback(code: str):
    """Callback de Google OAuth. Intercambia el código por un JWT token."""
    result = auth.handle_oauth_callback(code)
    if not result:
        return {"error": "Error durante la autenticación"}

    user_id, jwt_token, user_info = result

    # Retornar HTML que guarda el token y nombre en localStorage y redirige al dashboard
    nombre = user_info.get("name", "Usuario").split()[0] if user_info else "Usuario"
    html = f"""
    <html>
        <head>
            <title>Autenticando...</title>
        </head>
        <body>
            <script>
                localStorage.setItem('jwt_token', '{jwt_token}');
                localStorage.setItem('user_name', '{nombre}');
                localStorage.setItem('user_id', '{user_id}');
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


@app.post("/api/auth/migrate-legacy")
def auth_migrate_legacy(user_id: str = Depends(obtener_user_id)):
    """Migra gastos legacy al usuario actual."""
    database.migrar_gastos_legacy(user_id)
    return {"status": "ok", "message": "Datos migrados"}


# Sirve el dashboard (index.html) en la raíz
app.mount("/", StaticFiles(directory="static", html=True), name="static")
