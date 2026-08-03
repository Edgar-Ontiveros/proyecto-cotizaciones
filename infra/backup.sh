#!/usr/bin/env bash
# backup.sh — respaldo diario (lo dispara cotiza-backup.timer a las 02:00
# America/Chihuahua). Corre EN la EC2 con el rol de instancia.
#
# 1. pg_dump de la base (usuario de cotiza/prod/db-app) usando pg_dump 17 de
#    la MISMA imagen desplegada → gzip → S3 /pg/FECHA.sql.gz
# 2. aws s3 sync de los comprobantes (/opt/cotiza/archivos) → S3 /archivos/
#
# La retención la maneja el LIFECYCLE del bucket: aquí no se borra nada de S3.
set -euo pipefail

REGION="us-east-1"
BUCKET="cotiza-prod-s3-backups-588301175237"
BASE="/opt/cotiza"
CA="/opt/rds-ca.pem"
FECHA="$(TZ=America/Chihuahua date +%F)"

# La imagen actualmente desplegada (deploy.sh la deja registrada en .env).
ECR_REGISTRY="$(grep '^ECR_REGISTRY=' "${BASE}/.env" | cut -d= -f2)"
TAG="$(grep '^TAG=' "${BASE}/.env" | cut -d= -f2)"
IMAGE="${ECR_REGISTRY}/cotiza-api:${TAG}"

echo "==> Respaldo ${FECHA} con imagen ${TAG}"

db_json="$(aws secretsmanager get-secret-value --secret-id cotiza/prod/db-app \
    --query SecretString --output text --region "$REGION")"
PGURL="postgresql://$(jq -r .username <<<"$db_json"):$(jq -r '.password|@uri' <<<"$db_json")@$(jq -r .host <<<"$db_json"):$(jq -r .port <<<"$db_json")/$(jq -r .dbname <<<"$db_json")?sslmode=verify-full&sslrootcert=${CA}"

# La URL viaja por un env-file temporal 0600, nunca como argumento (ps) ni eco.
umask 077
tmp_envfile="$(mktemp)"
tmp_dump="$(mktemp --suffix=.sql.gz)"
trap 'rm -f "$tmp_envfile" "$tmp_dump"' EXIT
printf 'PGURL=%s\n' "$PGURL" > "$tmp_envfile"

echo "==> pg_dump → gzip"
docker run --rm --env-file "$tmp_envfile" -v "${CA}:${CA}:ro" "$IMAGE" \
    sh -c 'pg_dump --dbname="$PGURL"' | gzip > "$tmp_dump"

destino="s3://${BUCKET}/pg/${FECHA}.sql.gz"
echo "==> Subiendo a ${destino}"
aws s3 cp "$tmp_dump" "$destino" --region "$REGION" --only-show-errors
echo "dump: $(du -h "$tmp_dump" | cut -f1)"

echo "==> Sincronizando comprobantes → s3://${BUCKET}/archivos/"
aws s3 sync "${BASE}/archivos" "s3://${BUCKET}/archivos/" \
    --region "$REGION" --only-show-errors

echo "==> Respaldo ${FECHA} completo"
