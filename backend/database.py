"""
Capa de datos. Usa PostgreSQL para persistencia en producción.
"""
import os
import psycopg2
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import contextmanager
from urllib.parse import urlparse

# Obtener DATABASE_URL de variables de entorno (Railway lo proporciona automáticamente)
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL no está configurada. Vincula el PostgreSQL service en Railway.")


def get_connection():
    """Conecta a PostgreSQL."""
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def get_cursor():
    """Context manager para cursor."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


def init_db():
    """Inicializa la BD con las tablas necesarias."""
    with get_cursor() as cur:
        # Crear tabla users
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                google_id TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                nombre TEXT,
                google_token TEXT,
                creado_en TEXT NOT NULL,
                last_scrape_error TEXT
            )
        """)

        # Agregar columna last_scrape_error si no existe (para usuarios existentes)
        try:
            cur.execute("ALTER TABLE users ADD COLUMN last_scrape_error TEXT")
        except psycopg2.ProgrammingError:
            pass  # Columna ya existe

        # Agregar columna scraping_in_progress si no existe
        try:
            cur.execute("ALTER TABLE users ADD COLUMN scraping_in_progress BOOLEAN DEFAULT FALSE")
        except psycopg2.ProgrammingError:
            pass  # Columna ya existe

        # Crear tabla gastos
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gastos (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                fecha TEXT NOT NULL,
                monto REAL NOT NULL,
                comercio TEXT,
                categoria TEXT DEFAULT 'Otros',
                metodo TEXT,
                email_id TEXT,
                creado_en TEXT NOT NULL,
                estado TEXT DEFAULT 'activo'
            )
        """)

        # Crear tabla emails_ignorados
        cur.execute("""
            CREATE TABLE IF NOT EXISTS emails_ignorados (
                email_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                eliminado_en TEXT NOT NULL,
                PRIMARY KEY (user_id, email_id)
            )
        """)

        # Crear índice único para (user_id, email_id) en gastos para prevenir duplicados
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_gastos_user_email
            ON gastos(user_id, email_id)
            WHERE estado = 'activo'
        """)

        # Crear tabla budget_limits
        cur.execute("""
            CREATE TABLE IF NOT EXISTS budget_limits (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL UNIQUE,
                limite_mensual REAL NOT NULL,
                creado_en TEXT NOT NULL,
                actualizado_en TEXT NOT NULL
            )
        """)


def gasto_ya_existe(email_id: str, user_id: str = "legacy-user") -> bool:
    """Verifica si un gasto ya existe."""
    with get_cursor() as cur:
        # Verificar si está en la tabla de ignorados
        cur.execute(
            "SELECT 1 FROM emails_ignorados WHERE email_id = %s AND user_id = %s",
            (email_id, user_id)
        )
        if cur.fetchone():
            return True

        # Verificar si ya existe en gastos (activo o eliminado)
        cur.execute(
            "SELECT 1 FROM gastos WHERE email_id = %s AND user_id = %s AND (estado = 'activo' OR estado = 'eliminado')",
            (email_id, user_id)
        )
        return cur.fetchone() is not None


def guardar_gasto(fecha, monto, comercio, categoria, metodo, email_id, user_id: str = "legacy-user"):
    """Guarda un gasto."""
    with get_cursor() as cur:
        try:
            cur.execute(
                """INSERT INTO gastos (user_id, fecha, monto, comercio, categoria, metodo, email_id, creado_en)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (user_id, fecha, monto, comercio, categoria, metodo, email_id, datetime.now().isoformat()),
            )
        except psycopg2.IntegrityError:
            print(f"⚠️ Gasto {email_id} ya existe para {user_id}, ignorando duplicado")


def todos_los_gastos(user_id: str = "legacy-user"):
    """Obtiene todos los gastos de un usuario."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, user_id, fecha, monto, comercio, categoria, metodo, email_id, creado_en, estado FROM gastos WHERE user_id = %s AND estado = 'activo' ORDER BY fecha DESC",
            (user_id,)
        )
        rows = cur.fetchall()
        return [{
            'id': row[0], 'user_id': row[1], 'fecha': row[2], 'monto': row[3],
            'comercio': row[4], 'categoria': row[5], 'metodo': row[6], 'email_id': row[7],
            'creado_en': row[8], 'estado': row[9]
        } for row in rows]


def actualizar_gasto(email_id, monto, comercio, categoria, metodo, fecha=None):
    """Actualiza un gasto."""
    with get_cursor() as cur:
        if fecha:
            cur.execute(
                """UPDATE gastos SET fecha = %s, monto = %s, comercio = %s, categoria = %s, metodo = %s WHERE email_id = %s""",
                (fecha, monto, comercio, categoria, metodo, email_id),
            )
        else:
            cur.execute(
                """UPDATE gastos SET monto = %s, comercio = %s, categoria = %s, metodo = %s WHERE email_id = %s""",
                (monto, comercio, categoria, metodo, email_id),
            )


def normalizar_categorias_existentes():
    """Normaliza categorías."""
    reglas = {
        "Impuestos": ("%sunat%", "%impuesto%", "%tributo%"),
        "Finanzas": ("%préstamo%", "%prestamo%", "%cuota%"),
        "Suscripciones": ("%apple%", "%netflix%", "%spotify%"),
        "Servicios": (
            "%luz del sur%", "%calidda%", "%cálidda%", "%claro%",
            "%movistar%", "%entel%", "%win internet%", "%internet%",
        ),
        "Transporte": ("%uber%", "%yango%", "%taxi%", "%grifo%"),
        "Salud": ("%farmacia%", "%botica%", "%inkafarma%", "%mifarma%"),
        "Comida": ("%restaurant%", "%restaurante%", "%pollería%", "%polleria%"),
    }

    with get_cursor() as cur:
        for categoria, patrones in reglas.items():
            for patron in patrones:
                cur.execute(
                    "UPDATE gastos SET categoria = %s WHERE lower(comercio) LIKE %s",
                    (categoria, patron),
                )


def resumen_semana(user_id: str = "legacy-user"):
    """Resumen de gastos de la semana."""
    with get_cursor() as cur:
        ahora = datetime.now()
        desde = (ahora - timedelta(days=ahora.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        cur.execute(
            "SELECT id, user_id, fecha, monto, comercio, categoria, metodo, email_id, creado_en, estado FROM gastos WHERE user_id = %s AND fecha >= %s AND estado = 'activo' ORDER BY fecha DESC",
            (user_id, desde)
        )
        rows = cur.fetchall()
        return [{
            'id': row[0], 'user_id': row[1], 'fecha': row[2], 'monto': row[3],
            'comercio': row[4], 'categoria': row[5], 'metodo': row[6], 'email_id': row[7],
            'creado_en': row[8], 'estado': row[9]
        } for row in rows]


def resumen_mes(user_id: str = "legacy-user"):
    """Resumen de gastos del mes."""
    with get_cursor() as cur:
        desde = datetime.now().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        cur.execute(
            "SELECT id, user_id, fecha, monto, comercio, categoria, metodo, email_id, creado_en, estado FROM gastos WHERE user_id = %s AND fecha >= %s AND estado = 'activo' ORDER BY fecha DESC",
            (user_id, desde)
        )
        rows = cur.fetchall()
        return [{
            'id': row[0], 'user_id': row[1], 'fecha': row[2], 'monto': row[3],
            'comercio': row[4], 'categoria': row[5], 'metodo': row[6], 'email_id': row[7],
            'creado_en': row[8], 'estado': row[9]
        } for row in rows]


def actualizar_gasto_por_id(gasto_id, monto=None, comercio=None, categoria=None, metodo=None):
    """Actualiza un gasto por ID."""
    with get_cursor() as cur:
        campos = []
        valores = []
        if monto is not None:
            campos.append("monto = %s")
            valores.append(monto)
        if comercio is not None:
            campos.append("comercio = %s")
            valores.append(comercio)
        if categoria is not None:
            campos.append("categoria = %s")
            valores.append(categoria)
        if metodo is not None:
            campos.append("metodo = %s")
            valores.append(metodo)
        if campos:
            valores.append(gasto_id)
            query = f"UPDATE gastos SET {', '.join(campos)} WHERE id = %s"
            cur.execute(query, valores)


def marcar_email_ignorado(email_id, user_id: str = "legacy-user"):
    """Marca un email como ignorado."""
    with get_cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO emails_ignorados (user_id, email_id, eliminado_en) VALUES (%s, %s, %s)",
                (user_id, email_id, datetime.now().isoformat())
            )
        except psycopg2.IntegrityError:
            pass


def eliminar_gasto(gasto_id, user_id: str = "legacy-user"):
    """Elimina un gasto (soft delete)."""
    with get_cursor() as cur:
        # Obtener el email_id del gasto
        cur.execute("SELECT email_id FROM gastos WHERE id = %s AND user_id = %s", (gasto_id, user_id))
        row = cur.fetchone()

        if not row:
            print(f"⚠️ Gasto {gasto_id} no encontrado para user_id={user_id}")
            return

        # Marcar como eliminado
        cur.execute("UPDATE gastos SET estado = 'eliminado' WHERE id = %s AND user_id = %s", (gasto_id, user_id))
        print(f"✅ Gasto {gasto_id} eliminado")

        # Marcar email como ignorado
        if row[0]:
            marcar_email_ignorado(row[0], user_id)


def migrar_gastos_legacy(user_id: str):
    """Migra gastos legacy a un usuario nuevo."""
    with get_cursor() as cur:
        # Contar cuántos hay que migrar
        cur.execute("SELECT COUNT(*) FROM gastos WHERE user_id IS NULL OR user_id = 'legacy-user'")
        legacy_count = cur.fetchone()[0]

        if legacy_count > 0:
            cur.execute("UPDATE gastos SET user_id = %s WHERE user_id IS NULL OR user_id = 'legacy-user'", (user_id,))
            cur.execute("UPDATE emails_ignorados SET user_id = %s WHERE user_id IS NULL OR user_id = 'legacy-user'", (user_id,))
            print(f"✅ {legacy_count} gastos legacy migrados al usuario {user_id}")
        else:
            print(f"ℹ️ No hay gastos legacy para migrar")


def get_or_create_user(google_id: str, email: str, nombre: str) -> dict:
    """Obtiene o crea un usuario."""
    with get_cursor() as cur:
        cur.execute("SELECT id, google_id, email, nombre, google_token, creado_en FROM users WHERE google_id = %s", (google_id,))
        row = cur.fetchone()

        if row:
            return {
                'id': row[0], 'google_id': row[1], 'email': row[2], 'nombre': row[3],
                'google_token': row[4], 'creado_en': row[5]
            }

        user_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO users (id, google_id, email, nombre, creado_en)
               VALUES (%s, %s, %s, %s, %s)""",
            (user_id, google_id, email, nombre, datetime.now().isoformat())
        )
        cur.execute("SELECT id, google_id, email, nombre, google_token, creado_en FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return {
            'id': row[0], 'google_id': row[1], 'email': row[2], 'nombre': row[3],
            'google_token': row[4], 'creado_en': row[5]
        }


def update_user_token(user_id: str, token_json: str):
    """Actualiza el token del usuario."""
    with get_cursor() as cur:
        cur.execute("UPDATE users SET google_token = %s WHERE id = %s", (token_json, user_id))


def get_user(user_id: str):
    """Obtiene un usuario."""
    with get_cursor() as cur:
        cur.execute("SELECT id, google_id, email, nombre, google_token, creado_en FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            return {
                'id': row[0], 'google_id': row[1], 'email': row[2], 'nombre': row[3],
                'google_token': row[4], 'creado_en': row[5]
            }
        return None


def set_scrape_error(user_id: str, error_msg: str):
    """Guarda el último error de scraping para el usuario."""
    with get_cursor() as cur:
        cur.execute("UPDATE users SET last_scrape_error = %s WHERE id = %s", (error_msg, user_id))


def get_scrape_error(user_id: str):
    """Obtiene el último error de scraping del usuario."""
    with get_cursor() as cur:
        cur.execute("SELECT last_scrape_error FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def clear_scrape_error(user_id: str):
    """Limpia el error de scraping del usuario."""
    with get_cursor() as cur:
        cur.execute("UPDATE users SET last_scrape_error = NULL WHERE id = %s", (user_id,))


def marcar_scraping_iniciado(user_id: str):
    """Marca que el scraping comenzó para el usuario."""
    with get_cursor() as cur:
        cur.execute("UPDATE users SET scraping_in_progress = TRUE WHERE id = %s", (user_id,))


def marcar_scraping_terminado(user_id: str):
    """Marca que el scraping terminó para el usuario."""
    with get_cursor() as cur:
        cur.execute("UPDATE users SET scraping_in_progress = FALSE WHERE id = %s", (user_id,))


def is_scraping(user_id: str) -> bool:
    """Verifica si el usuario está actualmente scrapeando."""
    with get_cursor() as cur:
        cur.execute("SELECT scraping_in_progress FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return row[0] if row else False


def buscar_gastos(q="", categoria="", desde="", hasta="", user_id: str = None):
    """Busca gastos."""
    with get_cursor() as cur:
        query = "SELECT id, user_id, fecha, monto, comercio, categoria, metodo, email_id, creado_en, estado FROM gastos WHERE estado = 'activo'"
        params = []

        if user_id:
            query += " AND user_id = %s"
            params.append(user_id)
        if q:
            query += " AND lower(comercio) LIKE %s"
            params.append(f"%{q.lower()}%")
        if categoria:
            query += " AND categoria = %s"
            params.append(categoria)
        if desde:
            query += " AND fecha >= %s"
            params.append(desde)
        if hasta:
            query += " AND fecha <= %s"
            params.append(hasta)

        query += " ORDER BY fecha DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        return [{
            'id': row[0], 'user_id': row[1], 'fecha': row[2], 'monto': row[3],
            'comercio': row[4], 'categoria': row[5], 'metodo': row[6], 'email_id': row[7],
            'creado_en': row[8], 'estado': row[9]
        } for row in rows]


def set_budget_limit(user_id: str, limite_mensual: float):
    """Establece o actualiza el límite mensual de presupuesto."""
    with get_cursor() as cur:
        ahora = datetime.now().isoformat()
        # Usar UPSERT (INSERT ... ON CONFLICT ... DO UPDATE) para PostgreSQL
        cur.execute("""
            INSERT INTO budget_limits (user_id, limite_mensual, creado_en, actualizado_en)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
            SET limite_mensual = EXCLUDED.limite_mensual, actualizado_en = EXCLUDED.actualizado_en
        """, (user_id, limite_mensual, ahora, ahora))


def get_budget_limit(user_id: str) -> float:
    """Obtiene el límite mensual del usuario (None si no tiene)."""
    with get_cursor() as cur:
        cur.execute("SELECT limite_mensual FROM budget_limits WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None


def detectar_gastos_hormiga(user_id: str = "legacy-user", umbral: float = 5.0):
    """Detecta gastos pequeños (< umbral) del día actual."""
    with get_cursor() as cur:
        hoy = datetime.now(ZoneInfo("America/Lima")).date().isoformat()
        cur.execute(
            "SELECT id, fecha, monto, comercio, categoria FROM gastos WHERE user_id = %s AND fecha = %s AND monto < %s AND estado = 'activo' ORDER BY monto DESC",
            (user_id, hoy, umbral)
        )
        rows = cur.fetchall()
        hormiguitas = []
        for row in rows:
            hormiguitas.append({
                'id': row[0], 'fecha': row[1], 'monto': row[2],
                'comercio': row[3], 'categoria': row[4]
            })
        total_hormiga = sum(h['monto'] for h in hormiguitas)
        return {
            'gastos': hormiguitas,
            'total': round(total_hormiga, 2),
            'cantidad': len(hormiguitas)
        }


def detectar_gastos_recurrentes(user_id: str = "legacy-user"):
    """Detecta gastos que se repiten (probables pagos fijos como Netflix, internet, etc)."""
    from collections import Counter

    with get_cursor() as cur:
        # Obtener últimos 3 meses de gastos
        tres_meses_atras = (datetime.now(ZoneInfo("America/Lima")) - timedelta(days=90)).isoformat()
        cur.execute(
            "SELECT comercio, monto, categoria FROM gastos WHERE user_id = %s AND fecha >= %s AND estado = 'activo' ORDER BY comercio, monto",
            (user_id, tres_meses_atras)
        )
        rows = cur.fetchall()

        # Detectar patrones: mismo comercio + mismo monto = recurrente
        recurrentes = {}
        for comercio, monto, categoria in rows:
            key = (comercio, round(monto, 2))
            if key not in recurrentes:
                recurrentes[key] = {'count': 0, 'monto': monto, 'comercio': comercio, 'categoria': categoria}
            recurrentes[key]['count'] += 1

        # Filtrar: debe aparecer al menos 2 veces en 3 meses (probablemente recurrente)
        gastos_recurrentes = [
            {
                'comercio': v['comercio'],
                'monto': round(v['monto'], 2),
                'categoria': v['categoria'],
                'frecuencia': v['count']
            }
            for v in recurrentes.values() if v['count'] >= 2
        ]

        # Ordenar por frecuencia
        gastos_recurrentes.sort(key=lambda x: x['frecuencia'], reverse=True)

        # Calcular total mensual estimado
        total_mensual_estimado = sum(g['monto'] for g in gastos_recurrentes)

        return {
            'recurrentes': gastos_recurrentes,
            'total_mensual_estimado': round(total_mensual_estimado, 2),
            'cantidad': len(gastos_recurrentes)
        }


def obtener_insights(user_id: str = "legacy-user"):
    """Calcula insights: gasto mes actual, promedio diario, proyección fin de mes, alertas, límites."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    # Obtener límite de presupuesto
    limite = get_budget_limit(user_id)

    with get_cursor() as cur:
        ahora = datetime.now(ZoneInfo("America/Lima"))

        # Gasto TOTAL mes actual (desde día 1 hasta hoy)
        primer_dia_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        cur.execute(
            "SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE user_id = %s AND fecha >= %s AND estado = 'activo'",
            (user_id, primer_dia_mes.isoformat())
        )
        gasto_mes_actual = float(cur.fetchone()[0] or 0)

        # Gasto TOTAL mes pasado
        primer_dia_mes_pasado = (primer_dia_mes - timedelta(days=1)).replace(day=1)
        ultimo_dia_mes_pasado = primer_dia_mes - timedelta(days=1)
        cur.execute(
            "SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE user_id = %s AND fecha >= %s AND fecha <= %s AND estado = 'activo'",
            (user_id, primer_dia_mes_pasado.isoformat(), ultimo_dia_mes_pasado.isoformat())
        )
        gasto_mes_pasado = float(cur.fetchone()[0] or 0)

        # Días transcurridos en el mes actual
        dias_transcurridos = ahora.day

        # Promedio diario (gasto actual / días transcurridos)
        promedio_diario = gasto_mes_actual / dias_transcurridos if dias_transcurridos > 0 else 0

        # Proyección a fin de mes (promedio diario * 30 o 31)
        dias_en_mes = 31 if ahora.month in [1, 3, 5, 7, 8, 10, 12] else (30 if ahora.month != 2 else 28)
        proyeccion_fin_mes = promedio_diario * dias_en_mes

        # Diferencia con mes pasado
        diferencia_mes_pasado = gasto_mes_actual - gasto_mes_pasado
        porcentaje_diferencia = (diferencia_mes_pasado / gasto_mes_pasado * 100) if gasto_mes_pasado > 0 else 0

        # Alerta: Si gastó más del 20% comparado con mes pasado
        alerta = diferencia_mes_pasado > 0 and porcentaje_diferencia > 20

        # Calcular progreso de límite
        progreso_limite = None
        if limite:
            progreso_limite = min(100, (gasto_mes_actual / limite * 100))

        return {
            'gasto_mes_actual': round(gasto_mes_actual, 2),
            'gasto_mes_pasado': round(gasto_mes_pasado, 2),
            'promedio_diario': round(promedio_diario, 2),
            'proyeccion_fin_mes': round(proyeccion_fin_mes, 2),
            'diferencia_mes_pasado': round(diferencia_mes_pasado, 2),
            'porcentaje_diferencia': round(porcentaje_diferencia, 2),
            'alerta': alerta,
            'dias_transcurridos': dias_transcurridos,
            'dias_totales_mes': dias_en_mes,
            'limite_mensual': limite,
            'progreso_limite': round(progreso_limite, 1) if progreso_limite else None,
        }
