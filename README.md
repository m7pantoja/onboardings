# Onboardings Automation - LeanFinance

Automatización de onboardings de clientes. Detecta deals cerrados (WON) en HubSpot y ejecuta un pipeline de pasos: crear carpeta en Drive, contacto en Holded, notificaciones por Slack y email.

## Setup

```bash
# Instalar dependencias
uv sync

# Copiar y rellenar variables de entorno
cp .env.example .env

# Colocar client_secret de Google OAuth en secrets/
```

## Stack

- Python 3.12+
- uv (gestión de dependencias)
- httpx (HTTP async)
- pydantic / pydantic-settings (modelos y config)
- structlog (logging estructurado)
- APScheduler (scheduling)
- aiosqlite (persistencia SQLite)

## Servicios externos

- HubSpot (detección de deals)
- Google Drive (carpetas de cliente)
- Google Sheets (mapeo servicios/técnicos)
- Holded (contactos)
- Slack (notificaciones)
- Gmail (emails)
