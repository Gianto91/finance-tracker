import os
from datetime import datetime
from email.utils import parsedate_to_datetime

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import database
import email_parser
import gmail_scraper
import telegram_notifier

load_dotenv()

app = FastAPI(title="Mis Gastos")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

database.init_db()
database.normalizar_categorias_existentes()


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
        if not _es_de_hoy(datos.get("fecha")):
            print(
                f"  -> Correo fuera de fecha: {correo['id']} | "
                f"asunto: {correo.get('asunto', '')}"
            )
            continue

        database.guardar_gasto(
            fecha=datos.get("fecha") or _fecha_del_correo(correo),
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
def gastos_dia():
    from datetime import datetime
    hoy = datetime.now().date().isoformat()
    gastos = database.todos_los_gastos()
    return [g for g in gastos if g["fecha"].startswith(hoy)]


@app.get("/api/gastos/semana")
def gastos_semana():
    return database.resumen_semana()


@app.get("/api/gastos/mes")
def gastos_mes():
    return database.resumen_mes()


@app.get("/api/gastos/todos")
def gastos_todos():
    return database.todos_los_gastos()


@app.post("/api/revisar-ahora")
def revisar_ahora():
    """Dispara manualmente una revisión de correos (botón del dashboard)."""
    revisar_correos_nuevos()
    return {"status": "ok"}


@app.post("/api/gastos/crear")
def crear_gasto(monto: float, comercio: str, categoria: str = "Otros", metodo: str = "Otro"):
    """Crea un gasto manualmente (útil en modo demo sin Gmail)."""
    database.guardar_gasto(
        fecha=datetime.now().isoformat(),
        monto=monto,
        comercio=comercio,
        categoria=categoria,
        metodo=metodo,
        email_id=f"manual-{datetime.now().timestamp()}"
    )
    return {"status": "ok", "monto": monto, "comercio": comercio}


@app.put("/api/gastos/{gasto_id}")
def editar_gasto(gasto_id: int, monto: float = None, comercio: str = None,
                  categoria: str = None, metodo: str = None):
    """Edita un gasto existente."""
    database.actualizar_gasto_por_id(gasto_id, monto, comercio, categoria, metodo)
    return {"status": "ok", "gasto_id": gasto_id}


@app.delete("/api/gastos/{gasto_id}")
def eliminar_gasto(gasto_id: int):
    """Elimina un gasto."""
    database.eliminar_gasto(gasto_id)
    return {"status": "ok", "gasto_id": gasto_id}


@app.get("/api/gastos/buscar")
def buscar_gastos(q: str = "", categoria: str = "", desde: str = "", hasta: str = ""):
    """Busca y filtra gastos por comercio, categoría y rango de fechas."""
    return database.buscar_gastos(q, categoria, desde, hasta)


# Sirve el dashboard (index.html) en la raíz
app.mount("/", StaticFiles(directory="static", html=True), name="static")
