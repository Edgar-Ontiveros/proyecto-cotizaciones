# nginx de producción (F9): sirve el build de Vite y hace proxy de /api al
# contenedor de la API. Corre DETRÁS de CloudFront: la remote_addr que ve es
# la del edge, la IP real del cliente viene en X-Forwarded-For.
#
# PLANTILLA: deploy.sh la renderiza sustituyendo __ORIGIN_VERIFY__ por el
# secreto de Secrets Manager (cotiza/prod/origin-verify) y escribe el
# resultado en /opt/cotiza/nginx/nginx.conf. No editar el fichero renderado
# en la instancia: el siguiente despliegue lo sobrescribe.

worker_processes auto;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    sendfile on;
    keepalive_timeout 65;
    server_tokens off;

    # cf=1 => la petición trae la cabecera secreta de CloudFront; cf=0 => llegó
    # directa al origen. Sirve para comprobar el filtro antes de activarlo.
    log_format origen '$remote_addr "$request" $status cf=$cf_verificado';
    access_log /dev/stdout origen;
    error_log /dev/stderr warn;

    # El comprobante de pedido (F8g) permite hasta 10 MB.
    client_max_body_size 10m;

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/css application/javascript application/json image/svg+xml;

    # La clave del map de X-Origin-Verify es un secreto de 48 hex y no cabe en el
    # bucket por defecto (64). Va AQUÍ, antes del primer `map`: nginx fija este
    # valor al procesar el primer map y declararlo después da "is duplicate".
    map_hash_bucket_size 128;

    # Rate-limit del login por la PRIMERA IP de X-Forwarded-For: detrás de
    # CloudFront la remote_addr es del edge y limitaría a TODOS los usuarios
    # como si fueran uno. Sin XFF (acceso directo al origen) cae a remote_addr.
    map $http_x_forwarded_for $ip_cliente {
        default                 $remote_addr;
        "~^\s*(?<primera>[^,\s]+)" $primera;
    }
    limit_req_zone $ip_cliente zone=login:10m rate=10r/m;
    limit_req_status 429;

    # Sólo CloudFront debe alcanzar el origen. El security group ya limita el
    # puerto 80 a la prefix list de CloudFront, pero esa lista es de TODA
    # CloudFront: cualquiera podría apuntar su propia distribución aquí. La
    # distribución de cotizaciones inyecta X-Origin-Verify con un secreto y
    # esto comprueba que venga.
    map $http_x_origin_verify $cf_verificado {
        default                0;
        "__ORIGIN_VERIFY__"    1;
    }

    # ÚNICA exención: el healthcheck del contenedor (compose.prod.yml) pega a
    # 127.0.0.1/nginx-health desde dentro y nunca trae la cabecera; sin esto
    # daría 403 y `restart: unless-stopped` reciclaría nginx en bucle. Es un
    # endpoint dedicado que sólo devuelve 200 y no expone nada de la app, por
    # eso puede quedar fuera sin abrir superficie. NO añadir aquí rutas reales
    # de la API: si algo interno necesita hablar con el origen, que mande la
    # cabecera (así lo hace el smoke test de deploy.sh).
    map $uri $ruta_exenta {
        default        0;
        /nginx-health  1;
    }

    map "$cf_verificado$ruta_exenta" $rechazar_origen_directo {
        "00"     1;
        default  0;
    }

    upstream api {
        server api:8000;
    }

    server {
        listen 80;
        server_name _;

        # `current` es un symlink relativo a releases/<TAG> que deploy.sh
        # intercambia atómicamente (ver montaje en compose.prod.yml).
        root /usr/share/nginx/html/current;
        index index.html;

        # Sólo pasa lo que viene por CloudFront con la cabecera correcta. El
        # security group ya limita el puerto 80 a la prefix list de CloudFront,
        # pero esa lista es de TODA CloudFront: sin esto, cualquiera podría
        # apuntar su propia distribución a este origen.
        if ($rechazar_origen_directo) {
            return 403;
        }

        # Healthcheck interno del contenedor; no sale de la instancia.
        location = /nginx-health {
            access_log off;
            return 200;
        }

        # index.html SIN cache: es el que apunta a los assets hasheados nuevos.
        location = /index.html {
            add_header Cache-Control "no-cache";
        }

        # Assets con hash de Vite en el nombre: cache larga e inmutable.
        location /assets/ {
            add_header Cache-Control "public, max-age=31536000, immutable";
        }

        # SPA: cualquier ruta del router de React cae a index.html.
        location / {
            try_files $uri /index.html;
        }

        # API: CloudFront NO debe cachear NINGUNA respuesta de la API.
        # proxy_hide_header + add_header always => no-store gana SIEMPRE.
        location /api/ {
            proxy_pass http://api;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_hide_header Cache-Control;
            add_header Cache-Control "no-store" always;
        }

        # Login con rate-limit: 10 req/min por IP real, ráfaga de 5 → 429.
        location = /api/v1/auth/login {
            limit_req zone=login burst=5 nodelay;
            proxy_pass http://api;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_hide_header Cache-Control;
            add_header Cache-Control "no-store" always;
        }
    }
}
