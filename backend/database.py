"""
Capa de datos. Usa SQLite (un solo archivo, cero configuración,
perfecto para un proyecto personal que corre en tu propia laptop).
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "gastos.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            monto REAL NOT NULL,
            comercio TEXT,
            categoria TEXT DEFAULT 'Otros',
            metodo TEXT,
            email_id TEXT UNIQUE,
            creado_en TEXT NOT NULL,
            estado TEXT DEFAULT 'activo'
        )
    """)
    # Agregar columna estado si no existe (para tablas existentes)
    try:
        conn.execute("ALTER TABLE gastos ADD COLUMN estado TEXT DEFAULT 'activo'")
        conn.commit()
    except:
        pass
    conn.close()


def gasto_ya_existe(email_id: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM gastos WHERE email_id = ?", (email_id,)
    ).fetchone()
    conn.close()
    return row is not None


def guardar_gasto(fecha, monto, comercio, categoria, metodo, email_id):
    conn = get_connection()
    conn.execute(
        """INSERT INTO gastos (fecha, monto, comercio, categoria, metodo, email_id, creado_en)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (fecha, monto, comercio, categoria, metodo, email_id, datetime.now().isoformat()),
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


def resumen_semana():
    conn = get_connection()
    ahora = datetime.now()
    desde = (ahora - timedelta(days=ahora.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    rows = conn.execute(
        "SELECT * FROM gastos WHERE fecha >= ? AND estado = 'activo' ORDER BY fecha DESC", (desde,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resumen_mes():
    conn = get_connection()
    desde = datetime.now().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    rows = conn.execute(
        "SELECT * FROM gastos WHERE fecha >= ? AND estado = 'activo' ORDER BY fecha DESC", (desde,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def todos_los_gastos():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM gastos WHERE estado = 'activo' ORDER BY fecha DESC").fetchall()
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


def eliminar_gasto(gasto_id):
    conn = get_connection()
    conn.execute("UPDATE gastos SET estado = 'eliminado' WHERE id = ?", (gasto_id,))
    conn.commit()
    conn.close()


def buscar_gastos(q="", categoria="", desde="", hasta=""):
    conn = get_connection()
    query = "SELECT * FROM gastos WHERE estado = 'activo'"
    params = []
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
