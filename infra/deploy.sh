#!/usr/bin/env bash
# deploy.sh <TAG> — despliegue idempotente. Corre EN la EC2 (lo invoca el
# workflow vía SSM RunShellScript) usando el ROL DE INSTANCIA: aquí jamás hay
# access keys. Reejecutarlo con el mismo TAG es seguro.
#
# Pasos: login ECR → pull → render de .env (Secrets Manager + Parameter Store)
# → MIGRACIONES (si fallan, aborta sin tocar los contenedores en marcha) →
# estáticos a releases/<TAG> + swap atómico de `current` → compose up -d →
# poda de imágenes (conserva las últimas 3).
set -euo pipefail

TAG="${1:?uso: deploy.sh <TAG>}"
REGION="us-east-1"
ECR_REGISTRY="588301175237.dkr.ecr.us-east-1.amazonaws.com"
IMAGE="${ECR_REGISTRY}/cotiza-api:${TAG}"
BASE="/opt/cotiza"
CA="/opt/rds-ca.pem"

paso() { echo ""; echo "==> $*"; }

paso "[1/8] Login a ECR (rol de instancia)"
aws ecr get-login-password --region "$REGION" |
    docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null
echo "ok"

paso "[2/8] Pull de la imagen ${TAG}"
docker pull "$IMAGE"

paso "[3/8] Render de ${BASE}/.env (Secrets Manager + Parameter Store)"
secreto() {
    aws secretsmanager get-secret-value --secret-id "$1" \
        --query SecretString --output text --region "$REGION"
}
parametro() {
    aws ssm get-parameter --name "$1" \
        --query Parameter.Value --output text --region "$REGION"
}
db_app_json="$(secreto cotiza/prod/db-app)"
jwt_secret="$(secreto cotiza/prod/jwt | jq -r .jwt_secret)"
db_user="$(jq -r .username <<<"$db_app_json")"
db_pass_enc="$(jq -r '.password|@uri' <<<"$db_app_json")"
db_host="$(jq -r .host <<<"$db_app_json")"
db_port="$(jq -r .port <<<"$db_app_json")"
db_name="$(jq -r .dbname <<<"$db_app_json")"
DATABASE_URL="postgresql+psycopg://${db_user}:${db_pass_enc}@${db_host}:${db_port}/${db_name}?sslmode=verify-full&sslrootcert=${CA}"

umask 077
tmp_env="$(mktemp "${BASE}/.env.XXXXXX")"
cat > "$tmp_env" <<EOF
# Generado por deploy.sh — NO editar a mano (se regenera en cada despliegue)
DATABASE_URL=${DATABASE_URL}
JWT_SECRET=${jwt_secret}
ENV=$(parametro /cotiza/prod/env)
LOG_LEVEL=$(parametro /cotiza/prod/log_level)
DB_POOL_SIZE=$(parametro /cotiza/prod/db_pool_size)
DB_MAX_OVERFLOW=$(parametro /cotiza/prod/db_max_overflow)
SCHEDULER_DB_POOL_SIZE=$(parametro /cotiza/prod/scheduler_db_pool_size)
SCHEDULER_DB_MAX_OVERFLOW=$(parametro /cotiza/prod/scheduler_db_max_overflow)
ARCHIVOS_DIR=/data/archivos
ECR_REGISTRY=${ECR_REGISTRY}
TAG=${TAG}
EOF
mv "$tmp_env" "${BASE}/.env"
chmod 600 "${BASE}/.env"
echo "ok (0600, secretos no impresos)"

paso "[4/8] Migraciones con cotiza_migrate (si fallan: ABORTA sin tocar nada)"
db_mig_json="$(secreto cotiza/prod/db-migrate)"
mig_user="$(jq -r .username <<<"$db_mig_json")"
mig_pass_enc="$(jq -r '.password|@uri' <<<"$db_mig_json")"
MIG_URL="postgresql+psycopg://${mig_user}:${mig_pass_enc}@${db_host}:${db_port}/${db_name}?sslmode=verify-full&sslrootcert=${CA}"
if ! docker run --rm --env-file "${BASE}/.env" -e DATABASE_URL="$MIG_URL" \
    -v "${CA}:${CA}:ro" "$IMAGE" alembic upgrade head; then
    echo "ERROR: migraciones fallidas. Los contenedores en marcha quedan INTACTOS." >&2
    exit 1
fi
echo "migraciones ok"

paso "[5/8] Estáticos → ${BASE}/static/releases/${TAG} + swap atómico"
release_dir="${BASE}/static/releases/${TAG}"
if [ ! -d "$release_dir" ]; then
    cid="$(docker create "$IMAGE")"
    trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT
    docker cp "${cid}:/app/frontend-dist" "${release_dir}.tmp"
    docker rm "$cid" >/dev/null
    trap - EXIT
    mv "${release_dir}.tmp" "$release_dir"
else
    echo "release ya extraída (idempotente)"
fi
# Symlink RELATIVO (nginx lo resuelve dentro del contenedor) y swap atómico:
# symlink nuevo + rename, nunca hay un instante sin `current`.
ln -s "releases/${TAG}" "${BASE}/static/current.nueva"
mv -T "${BASE}/static/current.nueva" "${BASE}/static/current"
echo "current -> releases/${TAG}"

paso "[6/8] docker compose up -d (tag ${TAG})"
docker compose --env-file "${BASE}/.env" -f "${BASE}/compose.prod.yml" \
    up -d --remove-orphans

paso "[7/8] Espera a que la API reporte salud"
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1/api/v1/health"; then
        echo "API sana"
        break
    fi
    sleep 2
done
curl -fsS "http://127.0.0.1/api/v1/health" || {
    echo "ERROR: la API no reporta salud tras el despliegue" >&2
    docker compose --env-file "${BASE}/.env" -f "${BASE}/compose.prod.yml" ps
    exit 1
}
echo ""

paso "[8/8] Poda de imágenes (conserva las últimas 3 de cotiza-api)"
docker images "${ECR_REGISTRY}/cotiza-api" --format '{{.Tag}}' |
    tail -n +4 |
    while read -r viejo; do
        [ "$viejo" = "$TAG" ] && continue
        docker rmi "${ECR_REGISTRY}/cotiza-api:${viejo}" || true
    done
docker compose --env-file "${BASE}/.env" -f "${BASE}/compose.prod.yml" ps
echo ""
echo "DESPLIEGUE COMPLETO: ${TAG}"
