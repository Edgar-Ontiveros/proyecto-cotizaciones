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

`compose.prod.yml`, `nginx/nginx.conf.tpl`, `deploy.sh` y `backup.sh` se editan
EN EL REPO (`infra/`) y se copian a la instancia vía el bucket de respaldos
(la instancia no tiene acceso a GitHub):

```bash
aws s3 cp infra/deploy.sh s3://<BUCKET>/bootstrap/deploy.sh --profile cotiza
# dentro de la instancia:
aws s3 cp s3://<BUCKET>/bootstrap/deploy.sh /opt/cotiza/deploy.sh && chmod +x /opt/cotiza/deploy.sh
```

(el mismo patrón aplica para los otros tres; la plantilla va en
`/opt/cotiza/nginx/nginx.conf.tpl`).

`/opt/cotiza/nginx/nginx.conf` **no se edita ni se copia**: lo genera
`deploy.sh` desde la plantilla en cada despliegue. Editarlo a mano en la
instancia se pierde en el siguiente deploy.

## Acceso al origen: sólo CloudFront

El origen no es alcanzable desde internet abierto. Hay dos capas y las dos
tienen que estar puestas:

1. **Red** — el security group `cotiza-prod-sg-ec2` sólo admite el puerto 80
   desde la prefix list `com.amazonaws.global.cloudfront.origin-facing`
   (`pl-3b927c52`). El 8090 de órdenes vive en `cotiza-prod-sg-ordenes`,
   aparte, porque una referencia a esa prefix list pesa ~55 reglas y el límite
   por security group es 60: dos no caben en el mismo grupo.
2. **Aplicación** — esa prefix list es de TODA CloudFront, así que cualquiera
   podría apuntar su propia distribución aquí. La distribución de cotizaciones
   (`E2T3ZVD4KDNIRO`) inyecta la cabecera `X-Origin-Verify` con un secreto y
   nginx devuelve 403 a lo que no la traiga.

El secreto vive **sólo** en Secrets Manager, en `cotiza/prod/origin-verify`, y
de ahí lo leen los dos consumidores: el render de nginx.conf y el smoke test,
ambos en `deploy.sh`. El rol de la instancia ya lo alcanza por el comodín
`cotiza/prod/*` de `cotiza-prod-app-permisos`; no hace falta tocar IAM.

**Rotación** (los dos pasos, en este orden, o el sitio devuelve 403):

```bash
aws secretsmanager put-secret-value --secret-id cotiza/prod/origin-verify \
  --secret-string "$(openssl rand -hex 24)"
# 1) actualizar el custom header del origen en la distribución E2T3ZVD4KDNIRO
#    (update-distribution con el DistributionConfig completo + IfMatch)
# 2) re-desplegar, o re-renderizar nginx.conf a mano, para que el origen
#    acepte el valor nuevo
```

Durante la ventana entre ambos pasos conviene dejar el valor viejo también
válido, o hacerlo en horario de bajo tráfico: nginx sólo acepta un valor.

Para diagnosticar, el `access_log` marca cada petición con `cf=1` (llegó con
cabecera válida) o `cf=0` (llegó directa al origen):

```bash
docker logs --since 15m cotiza-nginx-1 | grep -oE 'cf=[01]' | sort | uniq -c
```

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
| 403 en todo el sitio | el secreto de `X-Origin-Verify` no coincide entre CloudFront y nginx; comparar el custom header de `E2T3ZVD4KDNIRO` con `cotiza/prod/origin-verify` y re-desplegar |
| Deploy falla en el paso 8 | el smoke test recibe 403: normalmente el render de nginx.conf tomó un secreto distinto del que manda CloudFront |
| Estáticos viejos tras deploy | `ls -l /opt/cotiza/static/current` — ¿apunta a la release nueva? |
