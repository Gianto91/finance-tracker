"""
Capa de datos. Usa SQLite (un solo archivo, cero configuración,
perfecto para un proyecto personal que corre en tu propia laptop).
"""
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "gastos.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()

    # Crear tabla users
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            google_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            nombre TEXT,
            google_token TEXT,
            creado_en TEXT NOT NULL
        )
    """)
    conn.commit()

    # Crear tabla gastos con estructura new
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
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
    conn.commit()

    # Crear tabla emails_ignorados con estructura new
    conn.execute("""
        CREATE TABLE IF NOT EXISTS emails_ignorados (
            email_id TEXT,
            user_id TEXT,
            eliminado_en TEXT NOT NULL,
            PRIMARY KEY (user_id, email_id)
        )
    """)
    conn.commit()

    # Migraciones para tablas existentes
    try:
        conn.execute("ALTER TABLE gastos ADD COLUMN estado TEXT DEFAULT 'activo'")
        conn.commit()
    except:
        pass
    try:
        conn.execute("ALTER TABLE gastos ADD COLUMN user_id TEXT DEFAULT 'legacy-user'")
        conn.commit()
    except:
        pass
    try:
        conn.execute("ALTER TABLE emails_ignorados ADD COLUMN user_id TEXT DEFAULT 'legacy-user'")
        conn.commit()
    except:
        pass

    conn.close()
    _migrate_legacy_data()


def gasto_ya_existe(email_id: str, user_id: str = "legacy-user") -> bool:
    conn = get_connection()
    # Verificar si está en la tabla de ignorados (emails que el usuario eliminó)
    row_ignorado = conn.execute(
        "SELECT 1 FROM emails_ignorados WHERE email_id = ? AND user_id = ?", (email_id, user_id)
    ).fetchone()
    if row_ignorado:
        conn.close()
        return True
    # Verificar si ya existe en gastos (activo o eliminado)
    row = conn.execute(
        "SELECT 1 FROM gastos WHERE email_id = ? AND user_id = ? AND (estado = 'activo' OR estado = 'eliminado')", (email_id, user_id)
    ).fetchone()
    conn.close()
    return row is not None


def guardar_gasto(fecha, monto, comercio, categoria, metodo, email_id, user_id: str = "legacy-user"):
    conn = get_connection()
    conn.execute(
        """INSERT INTO gastos (user_id, fecha, monto, comercio, categoria, metodo, email_id, creado_en)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, fecha, monto, comercio, categoria, metodo, email_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def gastos_con_comercio_invalido():
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM gastos
           WHERE comercio IS NULL OR comercio = ''
              OR comercio LIKE '%max-width%'
              OR comercio LIKE 'sorteos o promociones%'
              OR comercio LIKE 'and (%'"""
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def actualizar_gasto(email_id, monto, comercio, categoria, metodo, fecha=None):
    conn = get_connection()
    if fecha:
        conn.execute(
            """UPDATE gastos
               SET fecha = ?, monto = ?, comercio = ?, categoria = ?, metodo = ?
               WHERE email_id = ?""",
            (fecha, monto, comercio, categoria, metodo, email_id),
        )
    else:
        conn.execute(
            """UPDATE gastos
               SET monto = ?, comercio = ?, categoria = ?, metodo = ?
               WHERE email_id = ?""",
            (monto, comercio, categoria, metodo, email_id),
        )
    conn.commit()
    conn.close()


def normalizar_categorias_existentes():
    conn = get_connection()
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
    for categoria, patrones in reglas.items():
        condiciones = " OR ".join("lower(comercio) LIKE ?" for _ in patrones)
        conn.execute(
            f"UPDATE gastos SET categoria = ? WHERE {condiciones}",
            (categoria, *patrones),
        )
    conn.commit()
    conn.close()


def resumen_semana(user_id: str = "legacy-user"):
    conn = get_connection()
    ahora = datetime.now()
    desde = (ahora - timedelta(days=ahora.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    rows = conn.execute(
        "SELECT * FROM gastos WHERE user_id = ? AND fecha >= ? AND estado = 'activo' ORDER BY fecha DESC", (user_id, desde)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resumen_mes(user_id: str = "legacy-user"):
    conn = get_connection()
    desde = datetime.now().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    rows = conn.execute(
        "SELECT * FROM gastos WHERE user_id = ? AND fecha >= ? AND estado = 'activo' ORDER BY fecha DESC", (user_id, desde)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def todos_los_gastos(user_id: str = "legacy-user"):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM gastos WHERE user_id = ? AND estado = 'activo' ORDER BY fecha DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def actualizar_gasto_por_id(gasto_id, monto=None, comercio=None, categoria=None, metodo=None):
    conn = get_connection()
    campos = []
    valores = []
    if monto is not None:
        campos.append("monto = ?")
        valores.append(monto)
    if comercio is not None:
        campos.append("comercio = ?")
        valores.append(comercio)
    if categoria is not None:
        campos.append("categoria = ?")
        valores.append(categoria)
    if metodo is not None:
        campos.append("metodo = ?")
        valores.append(metodo)
    if campos:
        valores.append(gasto_id)
        query = f"UPDATE gastos SET {', '.join(campos)} WHERE id = ?"
        conn.execute(query, valores)
        conn.commit()
    conn.close()


def marcar_email_ignorado(email_id, user_id: str = "legacy-user"):
    """Marca un email para que NUNCA sea scrappeado de nuevo (por usuario)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO emails_ignorados (user_id, email_id, eliminado_en) VALUES (?, ?, ?)",
            (user_id, email_id, datetime.now().isoformat())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


def eliminar_gasto(gasto_id, user_id: str = "legacy-user"):
    conn = get_connection()
    # Obtener el email_id del gasto antes de eliminarlo
    row = conn.execute("SELECT email_id FROM gastos WHERE id = ? AND user_id = ?", (gasto_id, user_id)).fetchone()
    # Marcar como eliminado
    conn.execute("UPDATE gastos SET estado = 'eliminado' WHERE id = ? AND user_id = ?", (gasto_id, user_id))
    conn.commit()
    conn.close()
    # Si tiene email_id, marcar ese email como ignorado
    if row and row["email_id"]:
        marcar_email_ignorado(row["email_id"], user_id)


def _migrate_legacy_data():
    """Si hay gastos sin user_id, crea usuario legacy y asigna los datos."""
    conn = get_connection()
    legacy_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM gastos WHERE user_id = 'legacy-user'"
    ).fetchone()["cnt"]

    if legacy_count == 0:
        conn.close()
        return

    # Crear usuario legacy si no existe
    try:
        legacy_id = "legacy-user"
        conn.execute(
            """INSERT INTO users (id, google_id, email, nombre, creado_en)
               VALUES (?, ?, ?, ?, ?)""",
            (legacy_id, "legacy", "legacy@local", "Legacy User", datetime.now().isoformat())
        )
        conn.commit()
        print(f"✅ Usuario legacy creado con {legacy_count} gastos")
    except sqlite3.IntegrityError:
        pass
    conn.close()


def migrar_gastos_legacy(user_id: str):
    """Migra todos los gastos de 'legacy-user' o NULL al user_id especificado."""
    conn = get_connection()
    try:
        # Contar cuántos hay que migrar
        legacy_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM gastos WHERE user_id IS NULL OR user_id = 'legacy-user'"
        ).fetchone()["cnt"]

        if legacy_count > 0:
            # Actualizar gastos legacy (NULL o 'legacy-user')
            conn.execute(
                "UPDATE gastos SET user_id = ? WHERE user_id IS NULL OR user_id = 'legacy-user'",
                (user_id,)
            )
            # Actualizar emails ignorados legacy
            conn.execute(
                "UPDATE emails_ignorados SET user_id = ? WHERE user_id IS NULL OR user_id = 'legacy-user'",
                (user_id,)
            )
            conn.commit()
            print(f"✅ {legacy_count} gastos legacy migrados al usuario {user_id}")
        else:
            print(f"ℹ️ No hay gastos legacy para migrar")
    except Exception as e:
        print(f"❌ Error al migrar gastos legacy: {e}")
    conn.close()


def get_or_create_user(google_id: str, email: str, nombre: str) -> dict:
    """Obtiene o crea un usuario basado en google_id."""
    conn = get_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE google_id = ?", (google_id,)
    ).fetchone()

    if user:
        conn.close()
        return dict(user)

    user_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO users (id, google_id, email, nombre, creado_en)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, google_id, email, nombre, datetime.now().isoformat())
    )
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user)


def update_user_token(user_id: str, token_json: str):
    """Actualiza el token de Google OAuth del usuario."""
    conn = get_connection()
    conn.execute("UPDATE users SET google_token = ? WHERE id = ?", (token_json, user_id))
    conn.commit()
    conn.close()


def get_user(user_id: str):
    """Obtiene un usuario por su ID."""
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def buscar_gastos(q="", categoria="", desde="", hasta="", user_id: str = None):
    conn = get_connection()
    query = "SELECT * FROM gastos WHERE estado = 'activo'"
    params = []
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    if q:
        query += " AND lower(comercio) LIKE ?"
        params.append(f"%{q.lower()}%")
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
    if desde:
        query += " AND fecha >= ?"
        params.append(desde)
    if hasta:
        query += " AND fecha <= ?"
        params.append(hasta)
    query += " ORDER BY fecha DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
