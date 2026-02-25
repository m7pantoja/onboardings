# Onboardings Automation - LeanFinance

## Proyecto
Automatización de onboardings de clientes para LeanFinance. Cuando un deal se marca como WON en HubSpot, se ejecuta un pipeline de pasos (crear carpeta Drive, contacto en Holded, notificaciones Slack/email).

## Stack
- Python 3.12+
- Gestión de dependencias: uv
- HTTP: httpx (async)
- Config: pydantic-settings
- Modelos: Pydantic v2
- Logging: structlog
- Scheduling: APScheduler
- Persistencia: SQLite (aiosqlite), migrable a PostgreSQL
- Tests: pytest + pytest-asyncio

## Convenciones de código
- Código y comentarios en español cuando aporten claridad, pero nombres de variables/funciones/clases en inglés
- Type hints en todas las funciones públicas
- Docstrings solo donde la lógica no sea evidente
- Async por defecto en clientes HTTP y persistencia
- Cada step del pipeline es idempotente
- Errores se manejan explícitamente, nunca se tragan silenciosamente

## Estructura
```
onboardings/
├── pyproject.toml
├── uv.lock
├── .env.example
├── .env                    # NO commitear
├── .claude.json            # NO commitear (contiene API keys de MCPs)
├── secrets/                # NO commitear
│   └── client_secret_google.json
├── config/
│   ├── settings.py         # pydantic-settings (lee .env)
│   └── logging.py          # structlog config
├── src/
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── deal.py         # Modelo del deal de HubSpot
│   │   ├── onboarding.py   # OnboardingRecord, TechnicianInfo, StepRecord
│   │   └── enums.py        # OnboardingStatus, StepStatus, StepName
│   ├── clients/            # Wrappers de APIs externas (vacío, pendiente)
│   ├── steps/              # Pasos atómicos del onboarding (vacío, pendiente)
│   ├── pipeline/           # Motor de ejecución (vacío, pendiente)
│   ├── services/           # DealDetector, ServiceMapper, etc. (vacío, pendiente)
│   └── persistence/
│       ├── __init__.py
│       ├── schema.sql      # DDL: onboardings, onboarding_technicians, onboarding_steps
│       └── repository.py   # OnboardingRepository (async, aiosqlite)
└── tests/
    ├── __init__.py
    ├── unit/
    └── integration/
```

## Archivos sensibles (NO commitear)
- .env
- .claude.json
- secrets/

## Naming de IDs de HubSpot
- `hubspot_owner_id`: comercial/dueño del deal (propiedad del deal)
- `hubspot_tec_id`: técnico asignado (propiedad del contacto, varía por departamento)

## Reglas para Claude Code
- No ejecutar código sin confirmación explícita del usuario
- Ir paso a paso, explicando qué se hace y por qué
- Priorizar calidad sobre velocidad
- No añadir features ni abstracciones innecesarias
- Cuando haya duda sobre una decisión de negocio, preguntar
