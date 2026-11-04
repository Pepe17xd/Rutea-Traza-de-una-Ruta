# RUTEA

RUTEA coordina misiones de navegación horizontal, recibe telemetría GPS/IMU y muestra el estado del robot fumigador. La plataforma no sustituye el controlador local de seguridad: el firmware no activa motores ni bomba física y una misión digital no prueba que el robot se haya movido.

## Arquitectura

```text
Navegador (React / Vite / MapLibre)
     │ HTTPS, polling de API en AWS
     ▼
API Gateway HTTP API ── Lambda Python 3.12 (FastAPI + Mangum)
                              │
                              ├── Frontend estático empaquetado en la misma Lambda
                              ├── DynamoDB (misiones y telemetría)
                              └── LabRole preexistente (sin crear IAM)

Desarrollo local: Vite + Uvicorn/SQLite + WebSocket
Firmware: ESP32 Dev Module / NEO-6M / MPU-6050 (PlatformIO; compilación local)
```

El API y la SPA AWS comparten la URL HTTPS de API Gateway. Así el navegador no requiere CORS entre dos dominios, ni se crea un bucket público, CloudFront, certificados o un hosting adicional. El build de Vite se copia temporalmente a `Backend/app/frontend_dist` antes de empaquetar la Lambda; esa carpeta generada está ignorada por Git. En AWS, la actualización en tiempo real usa polling moderado; WebSocket persiste solo en Uvicorn local.

Serverless Framework 4 usa la sintaxis `provider.iam.role` con ARN explícito. El ARN siempre se resuelve como `arn:aws:iam::<AWS_ACCOUNT_ID>:role/LabRole`; el preflight compara la cuenta proporcionada con STS y verifica el rol. RUTEA no crea roles ni políticas IAM. El framework requiere que el usuario inicie sesión en Serverless Dashboard, además de las credenciales AWS de Learner Lab.

## Estructura

- `Backend/`: FastAPI, contratos, navegación, DynamoDB/SQLite, ML offline, Lambda/Mangum y pruebas.
- `Frontend/`: React, TypeScript, Vite, MapLibre y cliente HTTP/WebSocket.
- `Firmware/`: PlatformIO para `esp32dev`, GPS NEO-6M, IMU MPU-6050, recepción de misiones y diagnósticos. Motores/bomba permanecen deshabilitados.
- `scripts/`: preflight, despliegue/verificación/limpieza, pruebas, builds y auditoría de secretos.
- `serverless-compose.yml`: manifiesto validado del monorepo para evolución futura. La ejecución actual usa el orquestador `npm run deploy:academy` sobre el único servicio API.
- `GUIA_IMPLEMENTACION_ROBOT_ML.md`: especificación funcional original.

## Desarrollo local en Windows 11

Backend (PowerShell):

```powershell
cd Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend en otra terminal:

```powershell
cd Frontend
Copy-Item .env.example .env
npm.cmd ci
npm.cmd run dev
```

Abrir `http://localhost:5173`. Vite reenvía `/api` al backend local en `127.0.0.1:8000`. La sesión de operador se solicita desde la interfaz y se guarda en `sessionStorage`; no debe definirse `VITE_OPERATOR_TOKEN` ni compilarse una credencial en el bundle. API docs local: `http://127.0.0.1:8000/docs`.

## Requisitos para VM Ubuntu de AWS Academy

- Ubuntu x86_64, Node.js 20 o superior, npm, Python 3.12, AWS CLI v2, Git y compilador C++ para firmware.
- Cuenta activa de AWS Academy Learner Lab y rol preexistente `LabRole` que confíe en Lambda y tenga permisos reales para DynamoDB y CloudWatch Logs.
- Serverless Framework 4 instalado por `Backend/package.json` e inicio de sesión Serverless Framework.
- Acceso a npm y PyPI para instalar dependencias.
- AWS Academy puede restringir servicios, cuotas o permisos de simulación IAM. `LabRole` no garantiza por sí solo acceso; el preflight puede detenerse si no es posible comprobar un permiso.

## Despliegue desde clon limpio

1. Clonar y entrar a la raíz:

   ```bash
   git clone https://github.com/Pepe17xd/Rutea-Traza-de-una-Ruta.git
   cd Rutea-Traza-de-una-Ruta
   ```

2. Instalar Node 20+, Python 3.12, AWS CLI v2 y Git si no están instalados. Instalar dependencias frontend y del backend:

   ```bash
   npm ci --prefix Frontend
   npm install --prefix Backend
   python3.12 -m venv Backend/.venv
   Backend/.venv/bin/python -m pip install -e 'Backend[dev]'
   npm install --global serverless@4.43.0
   serverless login
   ```

   `Backend/package.json` fija Serverless Framework exactamente en 4.43.0. El script usa `npm ci` si hay lockfile; si aún no existe, genera `Backend/package-lock.json` usando el paquete directo fijado y lo conserva localmente. Revise y versione ese lockfile en una actualización futura del repositorio para fijar también las dependencias transitivas.

3. En el portal de Learner Lab, iniciar el laboratorio y copiar las credenciales temporales mostradas. Mantenerlas fuera del repositorio. Una opción es configurar un perfil AWS CLI local (no subir `~/.aws/credentials`):

   ```bash
   aws configure --profile default
   read -rsp "AWS Academy session token: " AWS_SESSION_TOKEN; echo
   aws configure set aws_session_token "$AWS_SESSION_TOKEN" --profile default
   unset AWS_SESSION_TOKEN
   export AWS_PROFILE=default
   export AWS_REGION=us-east-1
   aws sts get-caller-identity
   ```

   Ingresar Access Key ID y Secret Access Key en el prompt interactivo de `aws configure`; no ponerlos en comandos, archivos versionados o capturas. Exportar el token de sesión desde el mecanismo seguro de la VM. Las credenciales expiran; renovar las del portal y actualizar el perfil al vencer.

4. Copiar `.env.example` a `.env` en la raíz y completar solo lo necesario:

   - `AWS_ACCOUNT_ID`: número real de cuenta de 12 dígitos mostrado por `aws sts get-caller-identity`; el script exige que coincida, no lo descubre para sustituirlo ni lo fija.
   - `AWS_REGION=us-east-1`, `AWS_PROFILE=default`, `AWS_STAGE=academy` (o stage elegido).
   - `HECTOR_OPERATOR_TOKEN` y `HECTOR_DEVICE_TOKEN`: tokens diferentes, aleatorios y privados, mínimo 24 caracteres. No se incluyen en frontend. La persona operadora los escribe en la interfaz; el firmware usa su token de dispositivo.
   - `RUTEA_CREATE_DYNAMO_TABLES=false` es el valor conservador. Si las tablas `rutea-<stage>-missions` y `rutea-<stage>-telemetry` no existen, el preflight se detiene. Solo cambiar a `true` si el laboratorio confirma `dynamodb:CreateTable`, `UpdateTimeToLive` y etiquetado. Las tablas quedan con `Retain` para preservar datos.

   Para crear tokens localmente sin mostrarlos, se puede usar un generador seguro del sistema y pegarlos directamente en `.env`; no escribirlos en el shell compartido ni en el historial. `.env` está ignorado por Git.

5. Revisar el plan sin llamadas AWS y validar la configuración:

   ```bash
   npm run academy:check -- --dry-run
   npm run config:validate
   npm run audit:secrets
   ```

6. Revisar las credenciales de Serverless v4 (`serverless login`) y ejecutar preflight real de solo lectura:

   ```bash
   npm run academy:check
   ```

   Comprueba STS/cuenta, región, tipo de sesión, `LabRole`, trust de Lambda, simulación de permisos disponibles, tablas, cuotas de servicios y acceso a registros npm/PyPI. El saldo y límite temporal se verifican en la consola de Learner Lab, pues no hay una API universal de presupuesto de Academy.

7. Desplegar todo con un comando:

   ```bash
   npm run deploy:academy
   ```

   El comando instala dependencias fijadas, repite el preflight, compila el frontend con `/api/v1` relativo y transporte polling, revisa que no incluya `localhost`, empaqueta SPA + FastAPI y despliega `Backend/serverless.yml` mediante el CLI local de Serverless Framework. Finalmente consulta los outputs HTTPS, solicita la web, sus bundles y `/api/v1/health`. Una fase fallida termina con error y no imprime éxito. La URL guardada también queda en `.rutea-deploy-state.json` (ignorado por Git).

8. Verificar más adelante, revisar los recursos y registros:

   ```bash
   npm run verify:academy
   aws cloudformation describe-stacks --stack-name rutea-api-academy --region us-east-1
   aws logs tail /aws/lambda/rutea-api-academy-api --since 30m --follow --region us-east-1
   ```

   El nombre real de la función puede consultarse como recurso `ApiLambdaFunction` del stack si difiere. API Gateway HTTPS tiene el formato `https://<api-id>.execute-api.us-east-1.amazonaws.com/`; la SPA está en `/` y la API en `/api/v1`. Las rutas protegidas requieren el token de operador ingresado en la aplicación. El dispositivo transmite su token en `X-Device-Token`.

9. Actualizar después de cambios: `git pull`, instalar dependencias con `npm ci --prefix Frontend` y `npm ci --prefix Backend` si existe lockfile backend, luego `npm run test:all`, `npm run build:all`, `npm run academy:check` y `npm run deploy:academy`. No volver a configurar credenciales si el perfil temporal sigue vigente.

## Comandos desde la raíz

| Comando | Acción |
|---|---|
| `npm run academy:check` | Preflight AWS de solo lectura; `--dry-run` valida solo local. |
| `npm run deploy:academy` | Build, empaquetado, despliegue API + frontend y verificación HTTPS. |
| `npm run verify:academy` | Comprueba outputs desplegados, SPA, assets y health API. |
| `npm run cleanup:academy` | Retira el stack con confirmación tipada; conserva tablas. |
| `npm run cleanup:academy -- --delete-data` | Retira stack y, tras doble confirmación, las tablas RUTEA listadas en el estado local. |
| `npm run test:all` | Backend, build frontend y pruebas nativas PlatformIO disponibles. |
| `npm run build:all` | Builds frontend y firmware configurados. |
| `npm run firmware:test` / `npm run firmware:build` | Suite nativa / build ESP32. No flashea la placa. |

La limpieza solo apunta al stack `rutea-api-<stage>`, exige cuenta coincidente con `AWS_ACCOUNT_ID`, nombre stage y confirmación escrita. No elimina `LabRole`, el bucket de artefactos de Serverless ni otros recursos compartidos. Por defecto, DynamoDB permanece retenido. La opción `--delete-data` requiere estado local de despliegue, nombres exactos permitidos y dos confirmaciones.

## API v1 y transporte

FastAPI documenta los contratos en `/docs` y `/openapi.json` local. La API incluye health, misiones, telemetría, latest, trazas, resultados, modelo, polling de destinos, ACK y contrato simulado de bomba. En AWS se publica HTTP API para HTTP; no se afirma que un WebSocket persistente de FastAPI funcione dentro de Lambda. El firmware usa HTTP polling para destino/ACK y telemetría hacia `/api/v1/telemetry`. HTTP 200 significa aceptación de la petición, no recepción ni ejecución física del comando.

El contrato de telemetría distingue datos `PHYSICAL`, `RECORDED` y `SYNTHETIC`; una ubicación caducada o GPS sin fix no se muestra como medición actual. Un MPU-6050 no da rumbo absoluto. El dashboard no habilita motores ni bomba.

## Firmware y seguridad física

Desde `Firmware/`, compilar con PlatformIO para ESP32 Dev Module y revisar el procedimiento en `Firmware/README.md`. El firmware registra checksum de NMEA/UBX, GPS, IMU, estados y watchdog. El hardware final puede requerir ajustar UART/I²C al carrier board concreto. No se fija alimentación ni cableado de módulo sin identificar su variante. No flashear remotamente ni energizar motores/relé/bomba; driver, tracción, e-stop físico y confirmaciones del estado de bomba siguen pendientes.

## Costos y restricciones

Recursos previstos: una Lambda Python 3.12 reservada a cinco concurrencias, una API Gateway HTTP API, dos tablas DynamoDB on-demand opcionales y CloudWatch Logs retenidos siete días. Serverless Framework mantiene sus propios artefactos del despliegue en S3; el script no crea hosting S3 ni CloudFront para la web. No ejecutamos Compose porque su modo cero-config crea un bucket versionado y una referencia SSM para compartir estado entre servicios, innecesarios para esta aplicación de un solo servicio. El costo depende de invocaciones, almacenamiento/lecturas/escrituras y logs. Comprueba cuotas, saldo y expiración en Learner Lab. No se desplegó infraestructura desde este repositorio de preparación.

El plan de despliegue puede quedar bloqueado si Learner Lab no permite `iam:SimulatePrincipalPolicy`, `iam:PassRole`, crear recursos/stack o acceder a DynamoDB/Logs. RUTEA no intenta modificar `LabRole`, crear otro rol, abrir un bucket público ni saltarse esas limitaciones.

## Desarrollo, ML y pruebas

```bash
npm run test:all
npm run build:all
```

Backend Python usa SQLite local y DynamoDB en AWS. Entrenamiento scikit-learn es offline; Lambda no entrena ni carga dependencias ML pesadas en la ruta HTTP. Métricas de una simulación sintética no demuestran mejoras físicas. Para Windows usar `npm.cmd` y `python -m pytest` dentro de `Backend`.

## GitHub y secretos

`.env`, credenciales AWS, tokens, `.venv`, `node_modules`, `.serverless`, `.pio`, DB locales, bundles y estado de deploy se excluyen. Comprobar `npm run audit:secrets` antes de commits. La VM debe obtener credenciales temporales directamente desde Learner Lab; no insertar access keys, session token o Wi-Fi en GitHub.
