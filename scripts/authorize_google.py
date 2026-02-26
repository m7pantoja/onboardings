"""Script de autorización OAuth para Google APIs.

Ejecutar una sola vez para generar secrets/token_google.json:

    uv run python scripts/authorize_google.py

Abrirá un navegador para que autorices el acceso a Google Sheets.
"""

import sys
from pathlib import Path

# Añadir la raíz del proyecto al path para resolver imports de src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.clients.google_auth import run_oauth_flow

# Rutas relativas a la raíz del proyecto
CLIENT_SECRET = Path("secrets/client_secret_google.json")
TOKEN_PATH = Path("secrets/token_google.json")


def main() -> None:
    print("Iniciando flujo de autorización OAuth para Google Sheets...")
    print(f"  Client secret: {CLIENT_SECRET}")
    print(f"  Token se guardará en: {TOKEN_PATH}")
    print()

    creds = run_oauth_flow(
        client_secret_path=CLIENT_SECRET,
        token_path=TOKEN_PATH,
    )

    print()
    print(f"Autorización completada. Token guardado en {TOKEN_PATH}")
    print(f"  Scopes: {creds.scopes}")
    print()
    print("Ya puedes usar el cliente de Google Sheets.")


if __name__ == "__main__":
    main()
