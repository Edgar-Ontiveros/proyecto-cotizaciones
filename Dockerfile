# syntax=docker/dockerfile:1
# Imagen única de producción (F9): la MISMA imagen sirve la API (CMD default),
# el scheduler (command: python -m app.scheduler), las migraciones (alembic
# upgrade head) y el CLI (python -m app.cli). Los estáticos del frontend viajan
# en /app/frontend-dist y deploy.sh los extrae al host para que nginx los sirva.

# ---- Etapa 1: build del frontend --------------------------------------------
FROM node:22-alpine AS frontend-build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Etapa 2: imagen final --------------------------------------------------
# Python 3.12: el stack lo fija CLAUDE.md y pyproject exige >=3.12,<3.13.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

# postgresql-client-17 (PGDG): infra/backup.sh corre pg_dump con ESTA imagen;
# el cliente debe empatar la versión mayor del servidor RDS (PostgreSQL 17).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && apt-get purge -y gnupg curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias primero: esta capa solo se reconstruye si cambia el lockfile.
# Sin [build-system] el proyecto es virtual: uv instala SOLO las dependencias.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY --from=frontend-build /src/dist /app/frontend-dist

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
