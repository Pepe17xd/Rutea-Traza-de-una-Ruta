# Despliegue futuro en AWS Academy

La preparación serverless y sus límites, cuotas y costos están en [AWS_ACADEMY_SERVERLESS.md](AWS_ACADEMY_SERVERLESS.md). Este documento conserva la alternativa EC2 + HTTPS/WSS.

Esta carpeta documenta la reconstrucción del despliegue. No aprovisiona recursos.

## Variables de runtime

Configurar desde un gestor seguro/entorno de servicio, sin introducir secretos en Git:

| Variable | Uso |
|---|---|
| `HECTOR_STORAGE=dynamodb` | Selecciona adaptador AWS |
| `AWS_REGION` | Región permitida por el laboratorio |
| `MISSIONS_TABLE` | Tabla con partition key `mission_id` (String) |
| `TELEMETRY_TABLE` | Tabla con partition key `mission_id` (String) y sort key `sample_key` (String) |
| `HECTOR_ALLOWED_ORIGINS` | Orígenes exactos del frontend, separados por coma |
| `HECTOR_DEVICE_TOKEN`, `HECTOR_OPERATOR_TOKEN` | Tokens de MVP; producción requiere autenticación gestionada |
| `HECTOR_TELEMETRY_MAX_AGE_S` | Antigüedad máxima de muestras |
| `HECTOR_TELEMETRY_MAX_ACCURACY_M` | Rechazo de precisión inadecuada |
| `HECTOR_MODEL_PATH` | Directorio de artefacto ML confiable |

La app usa credenciales por defecto de boto3 (preferir IAM instance profile/role de Academy). No configurar access keys permanentes en el código.

## DynamoDB y límites actuales

Crear `Missions` con PK `mission_id` (String) y GSI `robot_created` con PK `robot_id` (String), SK `created_at` (String ISO UTC), proyección `ALL`; `Telemetry` usa PK `mission_id` (String), SK `sample_key` (String). El GSI permite historial paginado por robot en orden descendente. El adaptador guarda las muestras de una misión ordenables por timestamp/sequence. En la tabla `Telemetry` también se usan particiones reservadas `DEVICE#<robot_id>` para el vínculo del dispositivo y el estado de secuencia/timestamp monotónico. Aplicar retención TTL si la política del laboratorio lo requiere.

El rol EC2 debe tener solo `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `Query`, `Scan`, `TransactWriteItems` en los ARN de estas dos tablas e índice `robot_created`, además de permisos mínimos de logs/SSM que el despliegue use. La última telemetría usa `GetItem`; Scan solo se conserva para listados administrativos sin filtro de robot. No conceder `CreateTable` al rol de runtime.

## EC2 + HTTPS/WSS

1. Confirmar en AWS Academy región, vigencia, límites y servicios habilitados; no usar IoT Core sin confirmar disponibilidad/cuota.
2. Crear EC2 Linux pequeña con profile IAM anterior; restringir SSH a IP administrativa. Permitir internet público solo por 80/443 hacia el proxy. Mantener API en `127.0.0.1:8000`.
3. Copiar el backend y artefacto confiable, crear venv, instalar `pip install .`, configurar variables por systemd `EnvironmentFile` protegido, y ejecutar `uvicorn app.main:app --host 127.0.0.1 --port 8000` como usuario sin privilegios.
4. Usar Nginx/Caddy o proxy equivalente con certificado TLS. Proxy WebSocket debe enviar `Upgrade` y `Connection`; los clientes usan `wss://`. Habilitar renovación del certificado y reinicio automático del servicio.
5. Servir `Frontend/dist` con hosting estático o proxy. Establecer `VITE_API_BASE=https://<host>/api/v1`, `VITE_MAP_STYLE_URL` y orígenes CORS exactos antes del build. No incluir secretos en el bundle.
6. Revisar logs, espacio, rotación y política de retención. Probar recuperación recreando la instancia desde este documento y tablas respaldadas/exportadas según lo que permita Academy.

Esqueleto de proxy (adaptar y verificar antes de publicar):

```nginx
location /api/ {
  proxy_pass http://127.0.0.1:8000/api/;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto $scheme;
}
location /api/v1/ws/ {
  proxy_pass http://127.0.0.1:8000/api/v1/ws/;
  proxy_http_version 1.1;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_read_timeout 3600s;
}
```

Validar dominio, HTTPS, WSS, CORS, auth, IAM y comportamiento ante desconexión antes de la prueba de campo. Un corte de nube nunca puede ser el mecanismo de parada; el watchdog y E-stop deben residir en el robot.

