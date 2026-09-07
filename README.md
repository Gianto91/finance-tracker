# Finance Tracker 💰

Aplicación para rastrear gastos automáticamente desde correos bancarios y crear reportes visuales.

## Características

- 📧 **Escaneo automático de Gmail**: Detecta correos de bancos (Yape, BCP, Ligo, NetInterbank)
- 📊 **Gráficos visuales**: Pie, barras y tendencias con Chart.js
- ✏️ **CRUD completo**: Crear, editar, eliminar gastos
- 🔍 **Búsqueda y filtros**: Por comercio y categoría
- 📱 **Dashboard responsivo**: Tema oscuro, interfaz limpia
- 🔔 **Notificaciones**: Telegram bot para alertas de gastos

## Requisitos

- Python 3.8+
- SQLite (incluido)
- Variables de entorno (.env)

## Instalación local

```bash
cd backend
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

La app estará en: http://localhost:8000

## Variables de entorno

Crea un archivo `.env` en la carpeta `backend`:

```env
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
ANTHROPIC_API_KEY=your_api_key
SCAN_INTERVAL_MINUTES=2
```

## Despliegue en Railway

1. Conecta tu repositorio GitHub a Railway
2. Configura las variables de entorno en Railway
3. Deploy automático en cada push
