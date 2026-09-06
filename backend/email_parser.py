"""
Extrae los datos del gasto usando expresiones regulares, directamente
del texto del correo. Cero costo, cero dependencia de una API externa.

Los patrones están ajustados a los formatos típicos de BCP, Yape y Plin.
Si un banco cambia el formato de su correo, o agregas un banco nuevo,
aquí es donde hay que ajustar el regex correspondiente.
"""
import re
from datetime import datetime

# Patrones para montos en las constancias conocidas.
NUMERO_MONTO = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
PATRON_MONTO = re.compile(rf"S/\.?\s*({NUMERO_MONTO})")
PATRON_MONTO_CONSUMO = re.compile(
    r"realizaste\s+un\s+consumo\s+de\s+S/\.?\s*"
    rf"({NUMERO_MONTO})",
    re.IGNORECASE,
)
PATRON_MONTO_YAPE = re.compile(
    rf"monto\s+total\s+S/\.?\s*({NUMERO_MONTO})",
    re.IGNORECASE,
)
PATRON_MONTO_INTERBANK_PLIN = re.compile(
    rf"monto\s+y\s+moneda\s*(?:[:\-])?\s*(?:S/\.?\s*)?({NUMERO_MONTO})",
    re.IGNORECASE,
)
PATRON_MONTO_LIGO = re.compile(
    rf"(?:monto\s+total|monto)\s*[:\-]?\s*S/\.?\s*({NUMERO_MONTO})",
    re.IGNORECASE,
)
PATRON_MONTO_YAPEO = re.compile(
    r"realizaste\s+un\s+yapeo\s+a\s+celular\s+de\s+S/\.?\s*"
    rf"({NUMERO_MONTO})",
    re.IGNORECASE,
)
PATRON_MONTO_PRESTAMO = re.compile(
    rf"cuota\s+\d+\s+S/\.?\s*({NUMERO_MONTO})",
    re.IGNORECASE,
)

# Palabras que indican que el correo es un INGRESO (no un gasto) —
# si aparecen, lo ignoramos para no contarlo como gasto
PALABRAS_INGRESO = [
    "te enviaron", "has recibido", "abono a tu cuenta", "recibiste",
    "depósito a tu favor", "te transfirieron",
]

PATRONES_NO_GASTO = [
    re.compile(r"aporte\s+autom[aá]tico|ahorro\s+mensual|wardadito|seguir\s+ahorrando\s+juntos", re.IGNORECASE),
    re.compile(r"recuerda\s+que\s+tu\s+aporte\s+autom[aá]tico\s+se|para\s+tu\s+wardadito", re.IGNORECASE),
    re.compile(r"saldo\s+en\s+tu\s+cuenta\s+vinculada\s+para\s+seguir\s+ahorrando", re.IGNORECASE),
]

# Detecta el comercio/persona: busca después de palabras clave típicas
PATRONES_COMERCIO = [
    re.compile(
        r"\bdestinatario\s*[:\-]?\s*([^\n]{2,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdestino\s*[:\-]?\s*([^\n]{2,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"enviado\s+a\s+(.+?)(?=\s+(?:destino|desde|moneda|mensaje|"
        r"canal|n[uú]mero)\b|[.;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"realizaste\s+un\s+consumo\s+de\s+S/\.?\s*"
        r"\d+(?:[.,]\d{1,2})?.*?\ben\s+(.{2,80}?)(?=\.\s|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"empresa\s*:?\s*(.*?)(?=\s+(?:servicio|c[oó]digo|"
        r"n[uú]mero|fecha|monto)\b|[.;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:en|a favor de|destinatario:?)\s+([^\.\n]{2,80})",
        re.IGNORECASE,
    ),
]

PALABRAS_METODO = {
    "yape": "Yape",
    "plin": "Plin",
    "transferencia": "Transferencia",
    "tarjeta de débito": "Tarjeta",
    "tarjeta de crédito": "Tarjeta",
    "pago con tarjeta": "Tarjeta",
    "tarjeta": "Tarjeta",
    "consumo con tarjeta": "Tarjeta",
}

# Categorías disponibles para el dashboard.
CATEGORIAS = [
    "Comida", "Transporte", "Servicios", "Hogar", "Salud",
    "Entretenimiento", "Suscripciones", "Impuestos", "Finanzas", "Otros",
]

# Palabras clave -> categoría. Se revisan en este orden.
PALABRAS_CATEGORIA = {
    "sunat": "Impuestos", "impuesto": "Impuestos", "tributo": "Impuestos",
    "préstamo": "Finanzas", "prestamo": "Finanzas", "cuota": "Finanzas",
    "apple.com/bill": "Suscripciones", "apple": "Suscripciones",
    "netflix": "Suscripciones", "spotify": "Suscripciones",
    "restaurant": "Comida", "restaurante": "Comida", "pollería": "Comida",
    "polleria": "Comida", "rappi": "Comida", "pedidos ya": "Comida",
    "market": "Comida", "supermercado": "Comida", "tottus": "Comida",
    "wong": "Comida", "plaza vea": "Comida",
    "grifo": "Transporte", "taxi": "Transporte", "uber": "Transporte",
    "yango": "Transporte", "cabify": "Transporte", "combustible": "Transporte",
    "farmacia": "Salud", "botica": "Salud", "inkafarma": "Salud",
    "mifarma": "Salud", "clínica": "Salud", "clinica": "Salud",
    "cine": "Entretenimiento", "teatro": "Entretenimiento",
    "luz del sur": "Servicios", "calidda": "Servicios", "cálidda": "Servicios",
    "agua": "Servicios", "claro": "Servicios", "movistar": "Servicios",
    "entel": "Servicios", "win internet": "Servicios", "internet": "Servicios",
    "alquiler": "Hogar", "ferretería": "Hogar", "ferreteria": "Hogar",
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
MESES_CORTOS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _detectar_metodo(texto: str) -> str:
    texto_min = texto.lower()
    for palabra, metodo in PALABRAS_METODO.items():
        if palabra in texto_min:
            return metodo
    return "Otro"


def _detectar_categoria(texto: str, comercio: str) -> str:
    comercio_min = comercio.lower()
    for palabra, categoria in PALABRAS_CATEGORIA.items():
        if palabra in comercio_min:
            return categoria

    texto_min = texto.lower()
    for palabra, categoria in PALABRAS_CATEGORIA.items():
        if palabra in texto_min:
            return categoria
    return "Otros"


def _detectar_comercio(texto: str) -> str:
    for patron in PATRONES_COMERCIO:
        match = patron.search(texto)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" .")
    return "Desconocido"


def _detectar_monto(texto: str):
    for patron in (
        PATRON_MONTO_CONSUMO,
        PATRON_MONTO_YAPEO,
        PATRON_MONTO_PRESTAMO,
        PATRON_MONTO_YAPE,
        PATRON_MONTO_INTERBANK_PLIN,
        PATRON_MONTO_LIGO,
        PATRON_MONTO,
    ):
        match = patron.search(texto)
        if match:
            return _convertir_monto(match.group(1))
    return None


def _convertir_monto(valor: str) -> float:
    """Convierte montos con separadores peruanos o anglosajones."""
    valor = valor.strip()
    if "," in valor and "." in valor:
        if valor.rfind(".") > valor.rfind(","):
            valor = valor.replace(",", "")
        else:
            valor = valor.replace(".", "").replace(",", ".")
    elif "," in valor:
        parte_entera, parte_decimal = valor.rsplit(",", 1)
        if len(parte_decimal) == 3 and parte_entera:
            valor = valor.replace(",", "")
        else:
            valor = valor.replace(",", ".")
    return float(valor)


def _es_pago_prestamo(texto: str) -> bool:
    texto_min = texto.lower()
    return "constancia de pago" in texto_min and "cuota" in texto_min


def _detectar_fecha(texto: str):
    patrones = [
        re.compile(
            r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})\s*-\s*"
            r"(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(\d{1,2})\s+([a-záéíóú]{3,})[,]?\s+(\d{4})\s*(?:-\s*)?"
            r"(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(?:hrs?|h\.)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s+(\d{1,2}):(\d{2})",
            re.IGNORECASE,
        ),
    ]
    for indice, patron in enumerate(patrones):
        match = patron.search(texto)
        if not match:
            continue
        if indice < 2:
            dia, mes, anio, hora, minuto, periodo = match.groups()
            mes_numero = MESES.get(mes.lower()) if indice == 0 else MESES_CORTOS.get(mes.lower()[:3])
            if not mes_numero:
                continue
            hora = int(hora) % 12 + (12 if periodo.lower().startswith("p") else 0)
            return datetime(int(anio), mes_numero, int(dia), hora, int(minuto)).isoformat()
        if indice == 2:
            anio, mes, dia, hora, minuto, segundos = match.groups()
            return datetime(int(anio), int(mes), int(dia), int(hora), int(minuto), int(segundos or 0)).isoformat()
        dia, mes, anio, hora, minuto = match.groups()
        return datetime(int(anio), int(mes), int(dia), int(hora), int(minuto)).isoformat()
    return None


def _es_correo_informativo(texto: str) -> bool:
    return any(patron.search(texto) for patron in PATRONES_NO_GASTO)


def parsear_correo(texto_correo: str) -> dict:
    """
    Misma interfaz que la versión con IA: devuelve un dict con
    es_gasto, monto, comercio, metodo, categoria.
    """
    texto_min = texto_correo.lower()

    if _es_correo_informativo(texto_correo):
        return {"es_gasto": False}

    if any(palabra in texto_min for palabra in PALABRAS_INGRESO):
        return {"es_gasto": False}

    monto = _detectar_monto(texto_correo)
    if monto is None:
        return {"es_gasto": False}

    es_prestamo = _es_pago_prestamo(texto_correo)
    comercio = "Pago de préstamo" if es_prestamo else _detectar_comercio(texto_correo)
    metodo = _detectar_metodo(texto_correo)
    if es_prestamo:
        metodo = "Transferencia"
    categoria = _detectar_categoria(texto_correo, comercio)
    fecha = _detectar_fecha(texto_correo)

    datos = {
        "es_gasto": True,
        "monto": monto,
        "comercio": comercio,
        "metodo": metodo,
        "categoria": categoria,
    }
    if fecha:
        datos["fecha"] = fecha
    return datos
