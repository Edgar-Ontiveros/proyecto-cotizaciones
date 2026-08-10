# RUNBOOK — Operación de producción

Los identificadores concretos (cuenta, instancia, hosts) viven en
`MANUAL-DESPLIEGUE-EDGAR.md` (raíz del repo, **no versionado**). Aquí se citan
como `<CUENTA>`, `<INSTANCIA>`, `<HOST_RDS>` y `<BUCKET>`.

## Operación diaria

```bash
~/bin/aws-mfa <código-TOTP>       # abre sesión de 12 h en el perfil "cotiza"
aws sts get-caller-identity --profile cotiza   # ¿sigue viva la sesión?
```

**Entrar a la instancia** (no hay SSH; cada sesión queda grabada en CloudWatch):

```bash
aws ssm start-session --target <INSTANCIA> --profile cotiza
```

**Ver logs** (rotación ya configurada en el daemon de Docker):

```bash
# dentro de la instancia
cd /opt/cotiza
docker compose --env-file .env -f compose.prod.yml ps
docker compose --env-file .env -f compose.prod.yml logs -f api
docker compose --env-file .env -f compose.prod.yml logs -f scheduler
```

**Salud:** `curl -s http://127.0.0.1/api/v1/health` dentro de la instancia, o
`https://cotizaciones.appsherinox.com/api/v1/health` desde fuera. Reporta
estado de la base y del heartbeat del scheduler (`degraded` si lleva >30 min
sin correr).

## Desplegar y hacer rollback

Todo despliegue pasa por GitHub Actions (`deploy.yml`): push a `main` →
aprobación manual en el Environment `production` → build → push a ECR →
`deploy.sh <sha>` en la EC2 vía SSM.

**Rollback = redesplegar un sha anterior.** Las imágenes son inmutables por
sha; en la instancia:

```bash
cd /opt/cotiza && ./deploy.sh <sha-anterior>
```

`deploy.sh` es idempotente: si la imagen y la release ya están en la
instancia, solo re-apunta el symlink de estáticos y recrea los contenedores.
Ojo: el rollback NO deshace migraciones de Alembic; si la versión anterior es
incompatible con el esquema nuevo, hay que evaluar un `alembic downgrade`
manual (excepcional — las migraciones son aditivas por convención).

## Actualizar los artefactos de /opt/cotiza

`compose.prod.yml`, `nginx/nginx.conf`, `deploy.sh` y `backup.sh` se editan EN
EL REPO (`infra/`) y se copian a la instancia vía el bucket de respaldos
(la instancia no tiene acceso a GitHub):

```bash
aws s3 cp infra/deploy.sh s3://<BUCKET>/bootstrap/deploy.sh --profile cotiza
# dentro de la instancia:
aws s3 cp s3://<BUCKET>/bootstrap/deploy.sh /opt/cotiza/deploy.sh && chmod +x /opt/cotiza/deploy.sh
```

(el mismo patrón aplica para los otros tres; `nginx.conf` va en
`/opt/cotiza/nginx/` y requiere `docker compose ... restart nginx`).

## Port-forwarding a la base de datos

La RDS no es alcanzable desde internet; el túnel sale por la instancia:

```bash
aws ssm start-session --target <INSTANCIA> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<HOST_RDS>"],"portNumber":["5432"],"localPortNumber":["15432"]}' \
  --profile cotiza
# en otra terminal (la contraseña sale de Secrets Manager, jamás en el comando):
PGPASSWORD="$(aws secretsmanager get-secret-value --secret-id cotiza/prod/db-app \
  --query SecretString --output text --profile cotiza | jq -r .password)" \
  psql "host=localhost port=15432 dbname=cotiza user=cotiza_app sslmode=verify-ca sslrootcert=<RUTA_CA_LOCAL>"
```

> Nota: por el túnel el hostname no coincide con el certificado del servidor
> (`localhost` ≠ `<HOST_RDS>`), por eso `verify-ca` y no `verify-full`. La CA
> se descarga de https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem

## Respaldos y restore

`cotiza-backup.timer` (systemd, en la instancia) corre `/opt/cotiza/backup.sh`
diario a las 02:00 America/Chihuahua: `pg_dump` → gzip → `s3://<BUCKET>/pg/` y
sync de comprobantes → `s3://<BUCKET>/archivos/`. La retención la maneja el
lifecycle del bucket — el script no borra nada.

```bash
# estado del timer / última corrida (dentro de la instancia)
systemctl status cotiza-backup.timer
journalctl -u cotiza-backup.service -n 50
# corrida manual
sudo systemctl start cotiza-backup.service
```

**Restore (probado):** bajar el dump y restaurarlo en un Postgres 17 local
desechable — así se valida que el respaldo sirve de verdad:

```bash
aws s3 cp s3://<BUCKET>/pg/<FECHA>.sql.gz . --profile cotiza
docker run -d --name restore-test -e POSTGRES_PASSWORD=scratch -p 15433:5432 postgres:17
gunzip -c <FECHA>.sql.gz | docker exec -i restore-test psql -U postgres -d postgres
docker exec restore-test psql -U postgres -d postgres -c "select count(*) from usuarios;"
docker rm -f restore-test
```

Criterio de éxito: los conteos de `usuarios`, `sucursales` y `solicitudes`
coinciden con producción y `alembic_version` trae la revisión head esperada.
**Nota esperada:** el restore en un Postgres scratch imprime errores
`role "cotiza_app"/"cotiza_migrate" does not exist` — son los `GRANT` del
dump; no afectan los datos. Para un restore silencioso, crear antes los roles
(`CREATE ROLE cotiza_app; CREATE ROLE cotiza_migrate;`).

Prueba real ejecutada al cierre de F9 (día 1, dump `2026-08-04.sql.gz`):

```
usuarios: 54
sucursales: 11
solicitudes: 0
titularidades: 11
version alembic: 0f37792d31f7
```

Repetirla al menos tras cada cambio de esquema mayor.

## Reinicio pre-piloto (CLAUSURADO)

Reinicio pre-piloto ejecutado el 2026-08-10: `DROP SCHEMA public CASCADE` +
re-grants del §3.2 del manual (con `FOR ROLE cotiza_migrate`), `alembic
upgrade head` (2db348b42524), `seed-produccion` (54 usuarios, 11
titularidades, contadores en 0; segunda corrida 0/0), comprobantes de
`/opt/cotiza/archivos` vaciados y reinicio de api/scheduler. Verificado:
health ok/ok/ok y todas las cuentas con `must_change_password=true`.
Procedimiento CLAUSURADO — no volver a usar.

## Diagnóstico rápido

| Síntoma | Primer vistazo |
|---|---|
| 504 en el dominio | `docker compose ps` — ¿nginx/api arriba? ¿EC2 sana? |
| 502 en /api | logs de `api`; ¿migración fallida dejó imagen vieja? es lo esperado: la vieja sigue sirviendo |
| health `degraded` | logs de `scheduler`; el heartbeat lleva >30 min sin escribirse |
| Login devuelve 429 | rate-limit de nginx (10/min por IP); ¿algún cliente en bucle? |
| Estáticos viejos tras deploy | `ls -l /opt/cotiza/static/current` — ¿apunta a la release nueva? |
