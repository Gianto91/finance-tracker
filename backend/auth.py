"""
Google OAuth 2.0 authentication y JWT token management para multiuser.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
import requests
from dotenv import load_dotenv

import database

load_dotenv()

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/callback")

JWT_EXPIRY_HOURS = 24


def create_jwt_token(user_id: str) -> str:
    """Crea un JWT token para un usuario."""
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_jwt_token(token: str) -> Optional[str]:
    """Verifica un JWT token y retorna el user_id, o None si es inválido."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("user_id")
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def exchange_google_code(code: str) -> Optional[dict]:
    """Intercambia un código de autorización de Google por un token de acceso."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        print("❌ GOOGLE_CLIENT_ID o GOOGLE_CLIENT_SECRET no configurados")
        return None

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    try:
        response = requests.post(token_url, data=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Error al intercambiar código: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error en exchange_google_code: {e}")
        return None


def get_google_user_info(access_token: str) -> Optional[dict]:
    """Obtiene la información del usuario desde Google usando el access token."""
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers=headers
        )
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Error al obtener info de usuario: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error en get_google_user_info: {e}")
        return None


def handle_oauth_callback(code: str) -> Optional[tuple[str, str]]:
    """
    Maneja el callback de OAuth.
    Retorna (user_id, jwt_token) si es exitoso, None si falla.
    """
    # Intercambiar código por token
    token_response = exchange_google_code(code)
    if not token_response:
        return None

    access_token = token_response.get("access_token")
    if not access_token:
        return None

    # Obtener información del usuario
    user_info = get_google_user_info(access_token)
    if not user_info:
        return None

    google_id = user_info.get("id")
    email = user_info.get("email")
    nombre = user_info.get("name", email)

    if not google_id or not email:
        print(f"❌ Información incompleta del usuario: {user_info}")
        return None

    # Obtener o crear usuario
    user = database.get_or_create_user(google_id, email, nombre)

    # Guardar el access token en la BD (en producción, encriptarlo)
    database.update_user_token(user["id"], token_response.get("refresh_token") or access_token)

    # Crear JWT token
    jwt_token = create_jwt_token(user["id"])

    print(f"✅ Usuario autenticado: {email} (ID: {user['id']})")
    return (user["id"], jwt_token)
