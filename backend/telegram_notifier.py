"""
Manda un mensaje a tu Telegram cada vez que se registra un gasto nuevo.
Gratis, sin límites relevantes para uso personal.
"""
import os

import httpx

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def notificar_gasto(monto: float, comercio: str, categoria: str, metodo: str):
    if not BOT_TOKEN or not CHAT_ID:
        return  # notificaciones desactivadas si no configuraste el bot

    mensaje = (
        f"💸 *Nuevo gasto registrado*\n"
        f"S/ {monto:.2f} — {comercio}\n"
        f"Categoría: {categoria}\n"
        f"Método: {metodo}"
    )
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        httpx.post(
            url,
            json={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"},
            timeout=10,
        )
    except httpx.HTTPError:
        pass  # si falla la notificación, no debe tumbar el flujo principal
