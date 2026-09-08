"""
Capa de datos. Usa PostgreSQL para persistencia en producción.
"""
import os
import psycopg2
import uuid
from datetime import datetime, timedelta
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
                creado_en TEXT NOT NULL
            )
        """)

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
