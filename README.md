# Sistema de Cotizaciones Herinox

Plataforma interna de solicitudes de cotización de pedido especial:
los vendedores de las 11 sucursales piden cotizaciones al área de compras,
el sistema mide los tiempos de respuesta en horas hábiles (multi-zona
horaria) y el dinero cotizado/confirmado por sucursal, comprador, vendedor
y cliente.

## Stack

- **Backend:** Python 3.12 · FastAPI · SQLAlchemy 2.0 (sync) · PostgreSQL 17 · Alembic
- **Frontend:** React 19 · TypeScript · Vite 7 · Mantine 9 · TanStack Query 5
- **Infra:** Docker · nginx · GitHub Actions

La lógica de negocio está definida en `docs/especificacion.md`.

## Desarrollo

```bash
docker compose -f infra/compose.dev.yml up -d      # PostgreSQL 17 local
cd backend && uv sync && uv run alembic upgrade head
uv run python -m app.cli seed                      # datos demo (idempotente)
uv run uvicorn app.main:app --reload               # API en :8000
uv run python -m app.scheduler                     # scheduler (proceso aparte)
cd frontend && npm install && npm run dev          # Vite en :5173 (proxy /api → :8000)
```

Si la API no corre en `:8000`, apunta el proxy con `VITE_API_PROXY`.

## Tests

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd frontend && npm run test && npm run lint && npm run build
```

Los tests del backend corren contra un PostgreSQL 17 real (el del compose de
desarrollo), nunca SQLite.

## Despliegue

Producción se despliega vía GitHub Actions con aprobación manual —
ver `infra/RUNBOOK.md`.
