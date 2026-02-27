"""Gestión de credenciales OAuth para Google APIs.

Primera vez: ejecutar scripts/authorize_google.py para completar el flujo
interactivo y generar secrets/token_google.json.
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
]

# Rutas por defecto relativas a la raíz del proyecto
_DEFAULT_CLIENT_SECRET = Path("secrets/client_secret_google.json")
_DEFAULT_TOKEN_PATH = Path("secrets/token_google.json")


def get_google_credentials(
    client_secret_path: Path = _DEFAULT_CLIENT_SECRET,
    token_path: Path = _DEFAULT_TOKEN_PATH,
) -> Credentials:
    """Obtiene credenciales OAuth válidas para Google APIs.

    - Si existe token_path y es válido → lo devuelve.
    - Si expiró pero tiene refresh_token → lo renueva y guarda.
    - Si no existe → lanza RuntimeError (ejecutar authorize_google.py primero).
    """
    creds: Credentials | None = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds, token_path)
        return creds

    raise RuntimeError(
        f"No se encontró token válido en {token_path}. "
        "Ejecuta 'uv run python scripts/authorize_google.py' para autorizar."
    )


def run_oauth_flow(
    client_secret_path: Path = _DEFAULT_CLIENT_SECRET,
    token_path: Path = _DEFAULT_TOKEN_PATH,
) -> Credentials:
    """Ejecuta el flujo OAuth interactivo (abre navegador).

    Uso: solo desde scripts/authorize_google.py, una vez.
    """
    if not client_secret_path.exists():
        raise FileNotFoundError(f"No se encontró {client_secret_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds, token_path)
    return creds


def _save_token(creds: Credentials, token_path: Path) -> None:
    """Guarda las credenciales en disco."""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
