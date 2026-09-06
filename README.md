# Mis Gastos — Tracker personal de finanzas

Lee automáticamente los correos de notificación de tu banco/billetera,
extrae el gasto con IA, lo guarda y te avisa por Telegram. 100% gratis
para uso personal.

## Cómo funciona

```
Gmail (tus correos) → gmail_scraper.py → email_parser.py (IA) → database.py (SQLite)
                                                                        ↓
                                                          telegram_notifier.py (aviso)
                                                                        ↓
                                                        Dashboard (static/index.html)
```

Corre un job cada 15 minutos (configurable) que revisa si llegaron
correos bancarios nuevos, los interpreta y los guarda. El dashboard
lee esa base de datos y se refresca solo.

---

## Paso 1 — Credenciales de Google (Gmail API)

1. Ve a https://console.cloud.google.com/
2. Crea un proyecto nuevo (arriba a la izquierda, "New Project")
3. Ve a **APIs & Services → Library**, busca "Gmail API" y actívala
4. Ve a **APIs & Services → OAuth consent screen**
   - Tipo: **External**
   - Completa nombre de la app, tu correo
   - En "Test users" agrégate a TI MISMO (tu correo de Gmail)
   - No necesitas publicar la app ni pedir verificación — al estar en
     modo "Testing" con tu correo como test user, funciona sin límites
     de tiempo para ti
5. Ve a **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Tipo de aplicación: **Desktop app**
   - Descarga el JSON generado
6. Renombra ese archivo a `credentials.json` y ponlo en `backend/`

## Paso 2 — Bot de Telegram

1. Abre Telegram, busca **@BotFather**
2. Mándale `/newbot`, ponle un nombre (ej: "Mis Gastos Bot")
3. Te va a dar un **token** — cópialo, va en `TELEGRAM_BOT_TOKEN`
4. Ahora necesitas tu **chat_id**: busca en Telegram **@userinfobot**,
   mándale cualquier mensaje, te devuelve tu ID numérico — va en
   `TELEGRAM_CHAT_ID`
5. Importante: mándale un mensaje a TU bot primero (cualquier cosa,
   ej "hola") para "activar" la conversación, si no, no te va a poder
   escribir

## Paso 3 — API Key de Anthropic (para leer los correos con IA)

1. Ve a https://console.anthropic.com/settings/keys
2. Crea una API key, va en `ANTHROPIC_API_KEY`
3. El costo por correo procesado es mínimo (centavos de dólar al mes
   para uso personal — cada correo son pocos tokens)

## Paso 4 — Instalar y correr

```bash
cd backend
python -m venv venv
source venv/bin/activate       # en Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# abre .env y pega tus 4 credenciales (Google, Telegram, Anthropic)

uvicorn main:app --reload --port 8000
```

La primera vez que corra, se va a abrir tu navegador pidiéndote
login con Google — autorizas, y listo, queda guardado en `token.json`
para las próximas veces.

Abre **http://localhost:8000** y ahí está tu dashboard.

## Ajustar los remitentes bancarios

En `gmail_scraper.py`, edita la lista `REMITENTES_BANCARIOS` con los
correos reales que te llegan de tus notificaciones. Para saber el
remitente exacto, abre uno de esos correos en Gmail y copia la
dirección completa (puede que no sea exactamente la que puse de
ejemplo — cada banco tiene su propio dominio de envío).

## Notas

- Todo corre localmente en tu laptop — la base de datos es un solo
  archivo (`gastos.db`), no hay servidor externo ni suscripción
- Si quieres que corra "siempre encendido" sin tener la laptop
  prendida 24/7, más adelante se puede desplegar gratis en Railway o
  Render (tier gratuito alcanza de sobra para esto)
- El único costo real es la API de Anthropic, y es centavos al mes
  para el volumen de correos de una sola persona
