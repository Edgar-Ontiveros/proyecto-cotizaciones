# CLAUDE.md — Sistema de Cotizaciones Herinox

## Qué es este proyecto

Plataforma interna de solicitudes de cotización de pedido especial para Comercializadora de Inoxidables Hernández S.A. de C.V. (Herinox), distribuidora de acero: ~35 vendedores piden cotizaciones a 6 compradores (~250/semana, 11 sucursales en 5+ zonas horarias de México). Mide tiempos de respuesta de forma objetiva (bandas en horas hábiles) y dinero cotizado/confirmado por sucursal, comprador, vendedor y cliente.

## Fuente de verdad

`docs/especificacion.md` define TODA la lógica de negocio. Si algo en el código, en este archivo o en un prompt contradice la especificación, **la especificación manda**. Si una regla de negocio no está definida ahí, **NO la inventes: detente y pregunta a Edgar**.

## Flujo de trabajo

- **Una fase por sesión.** El prompt de la fase (Edgar lo pega en la terminal) define el alcance exacto. No implementes nada de fases futuras, aunque "ya estés ahí".
- Al terminar una fase: suite completa en verde (`uv run pytest`), `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app` sin errores, y un resumen corto: hecho + decisiones + dudas.
- Nunca declares una fase terminada con tests fallando o saltados.

## Stack (fijo — no cambies librerías ni agregues dependencias sin autorización explícita)

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 (sintaxis 2.0) · Alembic · Pydantic v2 + pydantic-settings · psycopg 3 (sync) · PyJWT · argon2-cffi · structlog · APScheduler (solo proceso scheduler) · openpyxl · boto3 |
| Base de datos | PostgreSQL 17 |
| Frontend | React 19 · TypeScript strict · Vite 7 · Mantine 9 · mantine-datatable 9 · TanStack Query 5 · React Router 7 · Recharts 3 · @mantine/form + Zod 4 · dayjs (utc+timezone) |
| Tooling | uv · ruff (lint+format) · mypy · pytest (+cov) · Vitest + RTL · Docker Compose · GitHub Actions |

### Prohibiciones explícitas
- NO async en la capa de datos: endpoints `def`, SQLAlchemy sync (async solo para I/O externo real: S3/SES).
- NO SQLModel, NO axios (wrapper propio sobre fetch), NO Redis/Celery, NO microservicios, NO localStorage/sessionStorage para tokens.
- NO archivos adjuntos en ninguna parte del sistema.
- NO estados materializados que un job "mueva": las bandas de tiempo SIEMPRE se calculan.

## Estructura del monorepo

```
/backend
  /app
    main.py            # FastAPI app (API pura, sin scheduler)
    /core              # config, database, security, permissions, logging, horario_habil
    /models            # SQLAlchemy (un módulo por agregado)
    /modules/<dominio> # router.py, service.py, schemas.py
    /scheduler         # proceso aparte: python -m app.scheduler
    /cli               # comandos: seed, create-admin
  /alembic
  /tests
/frontend
  /src/{api,auth,views/{vendedor,comprador,admin},components}
/infra                 # compose.dev.yml, compose.prod.yml, nginx, deploy.sh
/docs                  # especificacion.md
```

## Convenciones innegociables

1. **UTC siempre**: toda columna de tiempo es `timestamptz`; conversión a zona local SOLO en presentación y en `core/horario_habil.py` (cada sucursal tiene `timezone` IANA).
2. **`naming_convention` estándar** en el `MetaData` (ix/uq/ck/fk/pk) desde la primera migración.
3. **Todo cambio de esquema por Alembic**; nunca `create_all` fuera de tests.
4. **Transiciones de estado**: SIEMPRE en transacción con `SELECT ... FOR UPDATE` de la solicitud, validando estado actual contra la matriz; escriben estado + evento en `historial_estados` atómicamente. Conflicto → HTTP 409 con el estado real.
5. **Folios**: `{PREFIJO_SUCURSAL}-{CONSECUTIVO}` **sin año** (convención real: `CCN-3036`), consecutivo corrido por sucursal vía `folio_counters(sucursal_id, ultimo)` con `FOR UPDATE` en la misma transacción del envío. Prefijo y contador inicial editables por admin.
6. **API**: prefijo `/api/v1`, errores `{"detail": str, "code": str}`, paginación `limit/offset` (máx 100), routers delgados / lógica en services.
7. **Permisos en el query**: cada lectura filtra por rol/propiedad en SQL (vendedor: las suyas; comprador: las asignadas; gerente_sucursal: su sucursal — fail-closed sin sucursal; director_ventas y gerente_compras: global sin borradores; admin: todo). El frontend solo esconde botones.
8. **Logs**: structlog JSON a stdout; cada request loguea método, ruta, usuario, status, duración.
9. **Pool**: `pool_size=5, max_overflow=5, pool_pre_ping=True`.
10. **Tests contra PostgreSQL 17 real**, nunca SQLite. mypy `strict` en `core/`.
11. **Dinero**: `Numeric(14,2)` (cantidades `Numeric(14,3)`), nunca float. Importe = cantidad × precio_unitario; total de opción = suma de importes; los agregados NUNCA mezclan monedas (MXN y USD siempre separados).
12. **Git**: usa siempre la identidad configurada en git; NUNCA pases `user.name`/`user.email` con `-c` ni agregues trailers de atribución (Co-Authored-By, "Generated with").

## Máquina de estados (resumen — detalle en especificación §3)

| De → A | Quién dispara |
|---|---|
| BORRADOR → ENVIADA | Vendedor (enviar): asigna comprador titular de la sucursal, genera folio, arranca ciclo |
| ENVIADA → EN_PROCESO | Comprador (abrir/empezar captura) |
| ENVIADA/EN_PROCESO → RECHAZADA | Comprador, con motivo del catálogo — detiene ciclo |
| EN_PROCESO → COTIZADA | Sistema, al marcar el comprador captura completa — detiene ciclo |
| RECHAZADA → ENVIADA | Vendedor (corregir y reenviar) — ciclo nuevo desde cero |
| COTIZADA → CONFIRMADA | Vendedor selecciona UNA opción (A–E): fija ganadora y monto oficial. Terminal |
| COTIZADA → NO_CONFIRMADA | Vendedor, con motivo (admin puede revertir a COTIZADA) |
| BORRADOR/ENVIADA/EN_PROCESO/RECHAZADA → CANCELADA | Vendedor. Terminal |

Reglas clave: el vendedor edita la solicitud solo en ENVIADA/EN_PROCESO (notifica al comprador, queda en historial); una COTIZADA no se reabre — correcciones las hace el comprador sobre las opciones; 1–5 opciones (letras A–E), cada una con vigencia; **moneda (MXN|USD), precio y tiempo de entrega se capturan POR RENGLÓN dentro de cada opción** (F8c) y los totales son subtotales por moneda.

## Solicitud — campos exactos (del formato real, especificación §4.1)

Encabezado automático: folio, fecha, vendedor, sucursal + cliente (autocomplete con alta al vuelo), prioridad (NORMAL|URGENTE), notas.
Partidas: `num_partida` (auto), `codigo_sap` (opcional; "SERVICIO" cuando no hay), `cantidad`*, `unidad`*, `tipo_acero` (opcional), `descripcion`*, `medidas` (opcional). (* = obligatorio.) **No existe campo "acabado".**

## Roles y permisos — modelo v2 por ÁREA (F8c)

| Rol | Área · alcance | Ve | Hace |
|---|---|---|---|
| `vendedor` | Ventas · propio | Solo SUS solicitudes | Crear/editar/enviar/reenviar/cancelar, seleccionar opción (TC si hay USD), marcar no confirmada |
| `comprador` | Compras · asignadas | Las asignadas, CON proveedor | Tomar, capturar renglón rico, completar, rechazar con motivo, corregir cotizadas |
| `gerente_sucursal` | Ventas · su sucursal (exige `sucursal_id`; sin BORRADOR ajenos; sin proveedor) | Su sucursal | Acciones de LADO VENTAS en su sucursal + administra VENDEDORES de su sucursal (crear/editar/reset/baja segura/reasignar). Nada de compras ni métricas de compradores |
| `gerente_compras` | Compras · global | Todo CON proveedor/costos, métricas de compras (% no encontrados incluido), territorios | Ejecuta el lado COMPRAS sobre cualquier solicitud (F8c.1: tomar/capturar/cotizar/corregir/rechazar; el ciclo se atribuye al comprador ASIGNADO, el historial registra al ejecutor) + administra COMPRADORES (CRUD, bajas, titularidades, reasignaciones). No ve métricas por vendedor |
| `director_ventas` | Ventas · global | Todo ventas SIN proveedor ni métricas de compradores | Acciones de ventas sobre cualquier solicitud + administra vendedores (todas) y gerentes_sucursal |
| `admin` | Todo | Todo | Control absoluto; ÚNICO que gestiona gerente_compras, director_ventas y admins |

- **Matriz de gestión como dato** (`usuarios/service.MATRIZ_GESTION`); NADIE se cambia a sí mismo rol ni activo. Sin registro público.
- El campo `proveedor` (POR RENGLÓN desde F8b) y cualquier costo interno: visibles SOLO para el área compras (`comprador`, `gerente_compras`) y `admin`. Se excluyen en los schemas de respuesta del lado ventas — no se ocultan en el frontend.
- Reset de contraseñas v1: admin genera temporal de un solo uso → `must_change_password=true`.

## Dinero y medición (resumen — especificación §4.7–4.9)

- **Monto confirmado** (F8c) = CONSOLIDADO EN MXN de la opción seleccionada: total_mxn + total_usd × tipo_cambio (obligatorio si hay USD; prohibido si es 100% MXN). **Referencia** de una COTIZADA = subtotales MXN/USD de la opción A, por moneda separada.
- Bandas por ciclo (ENVIADA/reenvío → COTIZADA|RECHAZADA) en horas hábiles de la **zona horaria de la sucursal**: esperada ≤1 día hábil, normal ≤2, lenta >2 (alerta a administración al iniciar el 3er día).
- Horario hábil: L–V 08:00–18:00, sábado 08:00–13:00, menos `dias_festivos`. Toda esta aritmética vive ÚNICAMENTE en `core/horario_habil.py`.

## Comandos

```bash
docker compose -f infra/compose.dev.yml up -d      # Postgres 17 local
cd backend && uv sync && uv run alembic upgrade head
uv run python -m app.cli seed                      # datos reales demo (idempotente)
uv run uvicorn app.main:app --reload               # API :8000
uv run python -m app.scheduler                     # scheduler (proceso aparte; SCHEDULER_BANDAS_SEGUNDOS para bajar el intervalo en dev)
cd frontend && npm install && npm run dev          # Vite :5173 (proxy /api → :8000)

# calidad (obligatorio antes de cerrar cualquier fase)
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd frontend && npm run test && npm run lint && npm run build
```
