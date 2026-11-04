# AWS Academy: servicio RUTEA

El archivo fuente de despliegue es `Backend/serverless.yml`; `scripts/deploy-academy.mjs` realiza build, staging y verificación. Solo hay un servicio: `rutea-api`. FastAPI + Mangum y el build estático de React se empaquetan juntos en Lambda, servidos mediante API Gateway HTTP API bajo el mismo origen HTTPS. El manifiesto `serverless-compose.yml` queda validado para futuras necesidades multi-servicio; el deploy actual lo evita deliberadamente.

## IAM de Learner Lab

El proveedor declara el rol existente usando Serverless Framework v4:

```yaml
provider:
  iam:
    role: arn:aws:iam::${env:AWS_ACCOUNT_ID}:role/LabRole
```

`AWS_ACCOUNT_ID` se completa manualmente en el `.env` raíz, y el preflight requiere coincidencia con STS. No se crea rol ni política. Comprueba que el ARN real sea `arn:aws:iam::<cuenta>:role/LabRole`, que su trust permita Lambda y que tenga permisos runtime de DynamoDB y logs. La identidad temporal de despliegue también requiere permisos de CloudFormation, Lambda, API Gateway, artefactos Serverless en S3 e `iam:PassRole` sobre ese ARN. Si la Academy bloquea simulación IAM, el proceso se detiene y se debe confirmar permisos con el portal o administrador del laboratorio.

## Recursos y persistencia

Se publica una función Lambda Python 3.12 con Mangum, API Gateway HTTP API, dos tablas DynamoDB `PAY_PER_REQUEST` opcionales y un log group con retención de siete días. El default no crea tablas: deben existir y poder leerse. Solo activar `RUTEA_CREATE_DYNAMO_TABLES=true` si se verificó permiso de creación, TTL y tags. Las tablas tienen `DeletionPolicy: Retain`; cleanup conserva datos por defecto.

No se despliega un WebSocket persistente: el frontend AWS usa HTTP polling. Uvicorn local mantiene WebSocket. La API conserva los contratos HTTP de misión, telemetría, consulta/ACK de destinos, bomba simulada y métricas. No se afirma que una respuesta web haya sido recibida por hardware. La seguridad y control físico corren localmente en ESP32.

## Frontend

Vite se compila con `VITE_API_BASE=/api/v1`, transport polling y el `robot_id` configurado. El token de operador no se incrusta en el bundle; se ingresa en la interfaz y permanece en `sessionStorage`. Los archivos estáticos se copian a `Backend/app/frontend_dist` antes del paquete Lambda. FastAPI entrega `/`, assets y rutas SPA por el mismo HTTPS de API Gateway; `/api/v1` sigue resolviendo endpoints. CORS entre sitios no es requerido por el frontend same-origin.

Esta elección omite hosting estático S3 público, CloudFront, ACM y dominios. Serverless Framework aún necesita acceso a su bucket de artefactos para publicar Lambda. No se intenta crear ni abrir bucket web. Compose zero-config almacena state en un bucket S3 versionado y un parámetro SSM; con un solo servicio ese estado compartido no aporta valor y puede requerir permisos que Learner Lab no concede. Por eso el orquestador llama al servicio API directamente.

## Preparación y operación

Seguir instrucciones completas y exactas en el README raíz:

```bash
cp .env.example .env
# configurar AWS_PROFILE, AWS_ACCOUNT_ID, stage y tokens privados
npm run academy:check -- --dry-run
npm run academy:check
npm run deploy:academy
npm run verify:academy
```

Las credenciales temporales van en AWS CLI fuera del checkout. Serverless Framework v4 requiere `serverless login`. Se recomienda versionar `Backend/package-lock.json`; si falta, deploy lo crea localmente con Serverless Framework fijado directamente en `Backend/package.json`. No ejecutar deploy sin credenciales activas ni sin revisión de cuotas/saldo en el portal.

Para limpieza: `npm run cleanup:academy` solicita confirmación tipada, retira únicamente `rutea-api-<stage>` y conserva tablas. Borrar datos requiere `--delete-data`, estado de deploy coincidente, nombres exactos `rutea-<stage>-missions` / `rutea-<stage>-telemetry` y segunda confirmación. No borra LabRole ni el bucket de artefactos Serverless compartido.

## Limitaciones conocidas

- Saldo, restricciones temporales y varias cuotas deben revisarse en Learner Lab.
- `iam:SimulatePrincipalPolicy` puede estar denegado por políticas del laboratorio; preflight falla seguro en tal caso.
- Las tablas pueden no existir y la cuenta puede no autorizar su creación.
- El rol LabRole puede carecer de permisos DynamoDB/logs; RUTEA no modifica el rol.
- No se hicieron despliegues reales ni se ha verificado una cuenta Learner Lab en este entorno.
