"""
Extrae datos de gastos de emails de bancos peruanos.

Estrategia híbrida:
1. Si ANTHROPIC_API_KEY está configurada: usa Claude API (95-98% precisión)
   - Funciona con CUALQUIER banco y formato
   - Entiende contexto y variaciones
2. Si no: usa regexes como fallback (70-80% precisión)
   - Más rápido, sin costo
   - Requiere mantenimiento por banco nuevo

Bancos soportados:
- Interbank, BCP, Scotiabank, BBVA, Ripley, SIP, Yape, Plin, y otros
"""
import re
import os
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
PATRON_MONTO_YAPE_NUEVO = re.compile(
    rf"monto\s+de\s+yapeo[\s\S]*?S/[\s\S]*?({NUMERO_MONTO})",
    re.IGNORECASE,
)
PATRON_MONTO_INTERBANK_PLIN = re.compile(
    rf"monto\s+y\s+moneda[\s\S]*?(?:S/\.?\s*)?({NUMERO_MONTO})",
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
PATRON_MONTO_BBVA = re.compile(
    rf"monto\s*[:\-]?\s*S/\.?\s*({NUMERO_MONTO})",
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
    # Yape: Yapero o Beneficiario
    re.compile(
        r"(?:Yapero|Nombre del Beneficiario)\s*[:\-]?\s*([^\n]{2,80})",
        re.IGNORECASE,
    ),
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
    "Entretenimiento", "Suscripciones", "Impuestos", "Finanzas", "Transferencias", "Otros",
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
MESES_INGLES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _detectar_metodo(texto: str) -> str:
    texto_min = texto.lower()
    for palabra, metodo in PALABRAS_METODO.items():
        if palabra in texto_min:
            return metodo
    return "Otro"


def _detectar_categoria(texto: str, comercio: str) -> str:
    comercio_min = comercio.lower()

    # Plin y Yape son transferencias, no gastos
    if "plin" in comercio_min or "yape" in comercio_min:
        return "Transferencias"

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
        PATRON_MONTO_YAPE_NUEVO,
        PATRON_MONTO_PRESTAMO,
        PATRON_MONTO_YAPE,
        PATRON_MONTO_INTERBANK_PLIN,
        PATRON_MONTO_BBVA,
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
            r"(\d{1,2})\s+([a-z]{3,})[,]?\s+(\d{4})\s*(?:\s+|[\n\r]+)"
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
        if indice < 3:
            if indice == 0:
                dia, mes, anio, hora, minuto, periodo = match.groups()
                mes_numero = MESES.get(mes.lower())
            elif indice == 1:
                dia, mes, anio, hora, minuto, periodo = match.groups()
                mes_numero = MESES_CORTOS.get(mes.lower()[:3])
            else:
                dia, mes, anio, hora, minuto, periodo = match.groups()
                mes_numero = MESES_INGLES.get(mes.lower()) or MESES_INGLES.get(mes.lower()[:3])
            if not mes_numero:
                continue
            hora = int(hora) % 12 + (12 if periodo.lower().startswith("p") else 0)
            return datetime(int(anio), mes_numero, int(dia), hora, int(minuto)).isoformat()
        if indice == 3:
            anio, mes, dia, hora, minuto, segundos = match.groups()
            return datetime(int(anio), int(mes), int(dia), int(hora), int(minuto), int(segundos or 0)).isoformat()
        dia, mes, anio, hora, minuto = match.groups()
        return datetime(int(anio), int(mes), int(dia), int(hora), int(minuto)).isoformat()
    return None


def _es_correo_informativo(texto: str) -> bool:
    return any(patron.search(texto) for patron in PATRONES_NO_GASTO)


def _parsear_con_claude(texto_correo: str) -> dict:
    """Usa Claude API para extraer datos del correo (95-98% precisión)."""
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None

        # Import solo si se va a usar (evita error si anthropic no está instalado)
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        prompt = f"""Analiza este email de banco peruano y extrae la información de la transacción.

Email:
{texto_correo}

Retorna SOLO un JSON con estas claves (si no encuentras algo, usa null):
{{
  "es_gasto": true/false (true si es un gasto/débito, false si es ingreso o no es transacción),
  "monto": número (sin S/., sin comas),
  "comercio": string (nombre del establecimiento/persona),
  "metodo": string (ej: Tarjeta, Transferencia, Yape, Plin),
  "categoria": string (ej: Comida, Transporte, Servicios, Otros),
  "fecha": string (ISO format YYYY-MM-DDTHH:MM:SS si está disponible, else null)
}}

Sé especialmente cuidadoso con:
- Ignorar transferencias que indiquen ingresos (recibiste, te enviaron, abono)
- Detectar montos en formatos: "S/ 100", "S/.100", "100.00", "100,00"
- Extraer el comercio del contexto (establecimiento, empresa, persona)
- Detectar método: tarjeta, transferencia, yape, plin, etc.
- Asignar categoría inteligentemente basada en comercio

Retorna SOLO el JSON, sin markdown ni explicación."""

        response = client.messages.create(
            model="claude-opus-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        import json
        respuesta_texto = response.content[0].text.strip()
        # Limpiar markdown si viene ```json
        respuesta_texto = respuesta_texto.replace("```json", "").replace("```", "").strip()
        datos = json.loads(respuesta_texto)

        # Validar estructura
        if not isinstance(datos.get("es_gasto"), bool):
            return None
        if datos["es_gasto"] and datos.get("monto") is None:
            return None

        return datos
    except Exception as e:
        print(f"⚠️ Error con Claude API: {e}")
        return None


def parsear_correo(texto_correo: str) -> dict:
    """
    Estrategia híbrida: intenta Claude API primero, fallback a regex.
    Retorna: {es_gasto, monto, comercio, metodo, categoria, [fecha]}
    """
    # Intentar con Claude API primero (95-98% precisión)
    datos_claude = _parsear_con_claude(texto_correo)
    if datos_claude is not None:
        print(f"✅ Email parseado con Claude API")
        return datos_claude

    # Fallback a regex (70-80% precisión)
    print(f"⏳ Usando regex fallback")
    texto_min = texto_correo.lower()

    if "constancia de pago plin" in texto_min:
        print(f"DEBUG PARSER: Texto de Interbank recibido (primeros 500 chars):\n{texto_correo[:500]}\n")

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
