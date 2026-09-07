import re

NUMERO_MONTO = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:[.,]\d{1,2})?)"

# Mi patrón nuevo
PATRON_MONTO_INTERBANK_PLIN = re.compile(
    rf"monto\s+y\s+moneda[\s\S]*?(?:S/\.?\s*)?({NUMERO_MONTO})",
    re.IGNORECASE,
)

# Simular el texto del email (con salto de línea)
texto_email = """
Monto y moneda
S/ 10.00
"""

match = PATRON_MONTO_INTERBANK_PLIN.search(texto_email)
if match:
    print(f"✅ Match encontrado: {match.group(1)}")
else:
    print("❌ No hay match")

# También probar con formato diferente
texto_email2 = "Monto y moneda S/ 10.00"
match2 = PATRON_MONTO_INTERBANK_PLIN.search(texto_email2)
if match2:
    print(f"✅ Match encontrado (sin salto): {match2.group(1)}")
else:
    print("❌ No hay match (sin salto)")
