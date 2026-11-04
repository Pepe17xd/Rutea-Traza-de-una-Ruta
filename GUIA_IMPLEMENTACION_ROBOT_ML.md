# Sistema inteligente de navegación horizontal para un carrito autónomo

> **Guía de implementación --- MVP académico**\
> Stack: React + TypeScript + MapLibre + MapTiler (opcional) + FastAPI +
> Python + scikit-learn + AWS EC2 + DynamoDB + WebSocket/MQTT.\
> Escenario: campo abierto, sin obstáculos; robot con conectividad y
> telemetría de posición/orientación.\
> **Definición de horizontal:** movimiento sobre un plano 2D (x, y), no
> únicamente a lo largo de un eje. Si el prototipo solo admite un eje,
> reducir el modelo a 1D.

## 1. Objetivo y alcance

El operador selecciona un destino B desde una aplicación web; el robot
transmite su posición A y orientación. El backend transforma coordenadas
GPS a un plano métrico local, genera la recta de referencia A→B y
supervisa la navegación. El controlador convierte los errores de
seguimiento en comandos de velocidad y giro. DynamoDB conserva la
trayectoria ideal, la real, los comandos y las métricas. El frontend
muestra las posiciones y los estados en tiempo casi real.

**Alcance MVP:** un robot, una misión activa, terreno plano, sin
obstáculos, punto A fijo al iniciar misión, destino B elegido por
coordenadas o clic en mapa, simulador reproducible, control clásico de
referencia y modelo ML entrenado *offline*. No se implementan rutas
viales ni evasión de obstáculos.

**Requisito físico indispensable:** definir si la plataforma es
diferencial (dos ruedas motrices) o tipo automóvil (dirección
Ackermann). Los comandos y ecuaciones de actuadores dependen de ello. La
guía asume un robot diferencial simulado, con comandos `linear_mps` y
`angular_rps`; adaptar al hardware real antes de pruebas.

## 2. Principios de diseño

1.  **El mapa no navega:** MapLibre renderiza posiciones y líneas;
    MapTiler suministra mosaicos satelitales si se requiere. La ruta en
    campo abierto la calcula nuestra geometría, no un servicio de rutas
    de carreteras.
2.  **El GPS no proporciona conectividad:** asumimos que el robot ya
    cuenta con un enlace de datos separado.
3.  **Control local preferido:** la planificación y la visualización
    pueden residir en AWS, pero el bucle rápido de control debe
    ejecutarse en el robot o un controlador local. La nube envía
    destino/parámetros y recibe telemetría. Para demostración inicial se
    admite simulación centralizada.
4.  **La base de datos no es el lazo de control:** guardar registros
    asíncronamente; nunca leer DynamoDB para decidir cada corrección.
5.  **ML no sustituye a la geometría:** la ruta A→B es determinista. ML
    aprende una corrección o parámetros a partir de ejemplos.
6.  **Sin precisión suficiente, no hay seguimiento demostrable:**
    evaluar GPS/RTK y la frecuencia de muestreo; nunca asumir exactitud
    centimétrica de un GPS convencional.

## 3. Arquitectura de componentes

``` mermaid
flowchart TD
  U[Operador / React + MapLibre] -->|POST misión: B| API[FastAPI en EC2]
  API -->|Misión y waypoints| BUS[Canal de comunicación: MQTT o WebSocket]
  BUS --> ROBOT[Robot: GPS + brújula/IMU + control local]
  ROBOT -->|Telemetría: pose, velocidad, estado| BUS
  BUS --> API
  API -->|Eventos de posición| U
  API -->|Escrituras asíncronas| DB[(DynamoDB)]
  API -->|Carga de artefacto versionado| ML[Modelo ML entrenado offline]
  SIM[Simulador y entrenamiento Python] --> ML
```

**Despliegue simplificado en AWS Academy:** una EC2 para FastAPI,
servidor WebSocket y opcionalmente servir el frontend compilado;
DynamoDB para persistencia. Para MQTT, AWS IoT Core solo si la cuenta
del laboratorio permite usarlo; de lo contrario, WebSocket sobre
HTTPS/WSS en EC2. Consultar límites, IAM, presupuesto y reglas de red
del laboratorio antes de desplegar.

### Flujo de misión

1.  El robot reporta su pose actual
    `(lat, lon, heading_deg, speed_mps, timestamp)`.
2.  El usuario marca B en el mapa o introduce coordenadas y confirma la
    misión.
3.  FastAPI valida el destino, congela A como origen de misión y genera
    waypoints a intervalos métricos.
4.  El robot recibe `mission_id`, destino, referencia local y parámetros
    del controlador.
5.  En cada tick local, estima la pose, calcula errores y aplica comando
    limitado de velocidad/giro.
6.  Publica telemetría a intervalos definidos; FastAPI la difunde a la
    web y persiste una muestra.
7.  Al llegar dentro de la tolerancia de posición **y** con velocidad
    reducida, detiene motores y cierra misión.
8.  Si falla comunicación, sensor, timestamps o límites operativos,
    ejecuta parada segura local.

## 4. Sistema de coordenadas y matemática

### 4.1 GPS → coordenadas métricas locales

Los sensores pueden entregar latitud y longitud en WGS84. Para
recorridos pequeños, convertirlas a un marco local Este-Norte (ENU)
centrado en A. Usar `pyproj` con transformación geodésica/proyección
local adecuada (por ejemplo, topocéntrica o azimutal equidistante
centrada en A); **no tratar grados como metros**. Guardar `origin_lat`,
`origin_lon`, `crs` y convención de ejes. Para distancias cortas se
admite aproximación local solo tras validar su error.

-   `x`: este positivo; `y`: norte positivo; unidades en metros.
-   `theta`: rumbo del robot en radianes, medido desde el eje +x en
    sentido antihorario; convertir brújula/GPS a esta convención
    explícitamente.
-   `A=(ax, ay)`, `B=(bx, by)`, `P=(x,y)`.

### 4.2 Ruta ideal

Para `d=B-A` y `L=||d||`, si `L < epsilon` rechazar misión como ya
completada. De lo contrario:

``` text
u = d / L                          # vector tangente unitario
R(s) = A + s*u, 0 <= s <= L       # segmento ideal
waypoint_i = A + min(i*delta, L)*u
```

Usar `delta=1 m` en simulación como valor inicial configurable; no es un
requisito físico. Mantener A y B originales: **no sustituir A por la
posición actual en cada tick**, porque se perdería la referencia de la
ruta ideal.

### 4.3 Errores de seguimiento

``` text
s = clamp(dot(P-A, u), 0, L)
Q = A + s*u                        # proyección más cercana en el segmento
n = (-u_y, u_x)                    # normal izquierda
cross_track_error = dot(P-Q, n)   # error lateral con signo
heading_ref = atan2(u_y, u_x)
heading_error = wrap_to_pi(heading_ref - theta)
distance_to_goal = ||B-P||
```

La distancia al segmento se calcula respecto de `Q`, no de una recta
infinita. Al aproximarse a B, reducir velocidad y considerar el error de
distancia al objetivo.

### 4.4 Modelo cinemático (robot diferencial)

``` text
x[k+1] = x[k] + v[k]*cos(theta[k])*dt
y[k+1] = y[k] + v[k]*sin(theta[k])*dt
theta[k+1] = wrap(theta[k] + omega[k]*dt)
```

`v` en m/s y `omega` en rad/s. El simulador debe incluir opcionalmente
ruido, retraso y perturbaciones; registrar la semilla aleatoria para
reproducibilidad.

## 5. Controlador base (obligatorio antes de ML)

Un controlador de referencia sencillo para velocidad angular es:

``` text
omega = clamp(k_heading*heading_error - k_lateral*cross_track_error,
              -omega_max, +omega_max)
v = clamp(k_speed*distance_to_goal, 0, v_max)
```

Con `n=(-u_y,u_x)`, un error lateral positivo indica que el robot está a
la izquierda de la ruta; el término `-k_lateral*error` corrige hacia la
derecha. Ajustar ganancias en simulación. La velocidad debe reducirse
también si `abs(heading_error)` es grande. Filtrar medidas ruidosas,
limitar aceleraciones y velocidades, y definir `dt` real de muestreo.
Para el robot físico, calibrar conversión de `v, omega` a velocidades de
rueda.

**Criterio de llegada:** `distance_to_goal <= goal_tolerance_m` y
`abs(speed_mps) <= stop_speed_mps` durante un número configurable de
muestras válidas. No declarar llegada por cruce de un waypoint
intermedio.

## 6. Machine Learning: diseño defendible

### 6.1 Qué predice el modelo

El modelo **no predice la ruta geométrica**: estima un **ajuste acotado
a la velocidad angular** del controlador clásico (`delta_omega`). Salida
final:

``` text
omega_final = clamp(omega_baseline + clamp(delta_omega_ml, -ml_limit, ml_limit),
                    -omega_max, +omega_max)
```

Esto permite comparar **controlador base** vs. **controlador base + ML**
y desactivar ML sin perder navegación.

### 6.2 Entradas (features)

`cross_track_error_m`, `heading_error_rad`, `distance_to_goal_m`,
`speed_mps`, `previous_omega_rps`, `dt_s`. Opcional: variación de error
lateral y calidad del GPS. Normalizar usando estadísticas **solo del
conjunto de entrenamiento**.

### 6.3 Generación de datos etiquetados

1.  Simular cientos de episodios con diferentes A/B, posiciones
    iniciales, rumbos, ruido, velocidades y perturbaciones.
2.  Ejecutar un controlador experto de referencia (por ejemplo,
    controlador ajustado en simulación o MPC simple) para obtener la
    corrección angular deseada.
3.  Etiqueta: `delta_omega_target = omega_expert - omega_baseline`,
    recortada al límite permitido.
4.  Registrar cada observación con `episode_id`, `timestamp`, features,
    acción experta y resultado.
5.  Separar por **episodios completos** en
    entrenamiento/validación/prueba (70/15/15, orientativo), evitando
    mezclar ticks del mismo episodio entre particiones.

**No entrenar usando el error actual como si fuese por sí solo la
etiqueta de corrección.** Es necesario definir una acción objetivo o una
optimización de control que produzca las etiquetas.

### 6.4 Entrenamiento con descenso del gradiente

Primera versión: regresión con `MLPRegressor` de scikit-learn
(optimizador `adam`) o una red pequeña en PyTorch con MSE y Adam/SGD.
Usar una `Pipeline` con `StandardScaler` + estimador. Ajustar
hiperparámetros únicamente con validación, fijar semillas y versionar
artefactos. `MLPRegressor` emplea optimización basada en gradientes,
satisfaciendo el componente de aprendizaje por descenso de gradiente.

``` python
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPRegressor

model = make_pipeline(
    StandardScaler(),
    MLPRegressor(hidden_layer_sizes=(32, 16), activation="relu",
                 solver="adam", max_iter=500, random_state=42)
)
model.fit(X_train, y_train)
# evaluar X_val, y_val; probar después en episodios nunca vistos
```

Guardar el modelo solo desde una fuente confiable; no cargar archivos
`pickle`/`joblib` de usuarios desconocidos. Versionar el esquema de
features y el modelo junto con sus métricas. La inferencia debe ser
determinista, rápida y estar acotada; ante errores, datos fuera de rango
o incertidumbre excesiva, volver al controlador clásico.

### 6.5 Métricas de evaluación

-   **RMSE lateral (m)**: raíz de la media de `cross_track_error²`.
-   **Error lateral máximo (m)** y percentil 95.
-   **Tasa de llegada (%)** dentro del tiempo límite.
-   **Tiempo hasta destino (s)**.
-   **Esfuerzo de control**: suma/integral de `omega²`.
-   **Comparación base vs. base+ML** en **los mismos episodios de
    prueba**, perturbaciones y semillas.

ML solo se considera una mejora si reduce errores o mejora llegada **sin
comprometer estabilidad ni límites operativos**. No prometer
superioridad antes de medirla.

## 7. Contratos de API

Prefijo `/api/v1`. JSON con identificadores y timestamps ISO-8601 UTC.
Autenticación para operadores y dispositivos; validar rango de lat/lon,
secuencia temporal y `mission_id`.

  -------------------------------------------------------------------------
  Método                  Endpoint                  Propósito
  ----------------------- ------------------------- -----------------------
  `POST`                  `/missions`               Crear misión con
                                                    destino B y parámetros
                                                    permitidos

  `GET`                   `/missions/{id}`          Estado, origen,
                                                    destino, waypoints,
                                                    métricas

  `POST`                  `/missions/{id}/cancel`   Cancelar misión y
                                                    ordenar parada segura

  `GET`                   `/robots/{id}/latest`     Última telemetría
                                                    válida

  `POST`                  `/telemetry`              Ingestar telemetría
                                                    autenticada
                                                    (alternativa HTTP al
                                                    canal de eventos)

  `GET`                   `/missions/{id}/trace`    Trayectoria real
                                                    paginada

  `GET`                   `/health`                 Salud del backend

  `WS`                    `/ws/robots/{id}`         Actualizaciones en vivo
                                                    y eventos de misión
  -------------------------------------------------------------------------

**Ejemplo: crear misión**

``` json
{
  "robot_id": "CAR_01",
  "destination": {"lat": -12.04640, "lon": -77.04280},
  "goal_tolerance_m": 1.5,
  "max_speed_mps": 0.5
}
```

Las coordenadas son **ficticias e ilustrativas**, no un destino
sugerido. El servidor obtiene A de la telemetría reciente del robot, no
de un campo arbitrario enviado por el frontend. Rechazar si no hay
posición reciente o si la calidad del sensor es insuficiente.

**Ejemplo: telemetría**

``` json
{
  "robot_id": "CAR_01",
  "mission_id": "mission_001",
  "sequence": 24,
  "timestamp": "2026-10-21T20:00:00Z",
  "lat": -12.04641,
  "lon": -77.04290,
  "heading_deg": 89.0,
  "speed_mps": 0.3,
  "gps_accuracy_m": 1.2,
  "status": "MOVING"
}
```

**Ejemplo: mensaje de misión al robot**

``` json
{
  "type": "MISSION_ASSIGNED",
  "mission_id": "mission_001",
  "origin": {"lat": -12.04642, "lon": -77.04310},
  "destination": {"lat": -12.04640, "lon": -77.04280},
  "controller_version": "pd-1.0",
  "model_version": "mlp-1.0",
  "expires_at": "2026-10-21T20:10:00Z"
}
```

Si el control se ejecuta localmente, **no** enviar desde AWS una orden
nueva por cada tick. Enviar la misión y parámetros versionados;
transmitir posición y estados periódicamente. Si se implementa control
remoto experimental, usar secuencias, caducidad de órdenes y un watchdog
local; no depender del enlace para una parada segura.

## 8. Modelo de datos DynamoDB

Para MVP, dos tablas (o una tabla única si el equipo domina ese diseño):

### `Missions`

-   Clave primaria: `mission_id` (string).
-   Atributos: `robot_id`, `created_at`, `status`
    (`PENDING|ACTIVE|COMPLETED|CANCELLED|FAILED`), `origin_gps`,
    `destination_gps`, `local_frame`, `ideal_waypoints`,
    `controller_version`, `model_version`, `summary_metrics`.
-   Si el arreglo de waypoints crece, almacenarlo como objeto en S3 y
    guardar referencia; respetar el límite de tamaño de ítem de
    DynamoDB.

### `Telemetry`

-   Clave de partición: `mission_id`.
-   Clave de ordenación: `sample_key` (timestamp ISO UTC + secuencia con
    ancho fijo, o entero temporal/seq que preserve orden).
-   Atributos: `robot_id`, `lat`, `lon`, `x_m`, `y_m`, `heading_rad`,
    `speed_mps`, `gps_accuracy_m`, `cross_track_error_m`,
    `heading_error_rad`, `omega_cmd_rps`, `model_version`, `status`.
-   Crear índice secundario solo si se necesitan consultas por robot;
    para el MVP, recuperar telemetría por misión y consultar con
    paginación.
-   Persistir por lotes o asíncronamente; nunca bloquear el control
    local por latencia de DB.

## 9. Frontend web

**Stack:** React + Vite + TypeScript, MapLibre GL JS, proveedor de
mosaicos MapTiler opcional, fetch/cliente HTTP y WebSocket.

### Pantallas y elementos

1.  **Panel principal:** mapa satelital/callejero, marcador del robot,
    marcador B, polilínea ideal (verde), trayectoria real (naranja),
    estado de conexión y antigüedad de telemetría.
2.  **Creación de misión:** clic sobre mapa o ingreso de lat/lon;
    mostrar distancia estimada, confirmar y botón Cancelar/Detener.
3.  **Telemetría:** coordenadas, rumbo, velocidad, precisión GPS, error
    lateral, estado y timestamp.
4.  **Resultados:** gráfica de error lateral contra tiempo, RMSE,
    distancia recorrida, duración y comparación base/ML.

### Implementación

-   `npm create vite@latest frontend -- --template react-ts`.
-   Instalar `maplibre-gl`; configurar estilos y API key de MapTiler por
    variable `VITE_MAPTILER_KEY` si se usan sus mosaicos. Las claves
    públicas de mapa deben restringirse por dominio y cuota; **nunca
    poner secretos AWS en el frontend**.
-   Al cargar, consultar `/robots/CAR_01/latest` y centrar mapa en
    última posición; si no hay telemetría, mostrar estado *Sin señal*.
-   En `map.on('click')`, capturar `lngLat`, actualizar marcador B y
    permitir confirmación antes de `POST /missions`.
-   Dibujar GeoJSON `LineString` de waypoints ideales y actualizar
    GeoJSON de posiciones reales recibidas por WebSocket.
-   Aplicar reconexión exponencial de WebSocket, descartar eventos
    duplicados por `sequence` y mostrar advertencia cuando la telemetría
    esté desactualizada.
-   No confundir interpolación visual entre puntos con posiciones
    realmente medidas.

### Organización sugerida

``` text
frontend/src/
  api/client.ts
  components/MapView.tsx
  components/MissionForm.tsx
  components/TelemetryPanel.tsx
  components/MetricCharts.tsx
  hooks/useRobotSocket.ts
  types/robot.ts
  App.tsx
```

## 10. Backend y motor de navegación

**Stack:** Python 3.11+, FastAPI, Pydantic, boto3, numpy, pyproj,
scikit-learn, pytest, uvicorn.

``` text
backend/
  app/main.py
  app/api/missions.py
  app/api/telemetry.py
  app/api/websocket.py
  app/core/config.py
  app/navigation/coordinates.py
  app/navigation/trajectory.py
  app/navigation/errors.py
  app/navigation/controller.py
  app/ml/inference.py
  app/db/dynamodb.py
  app/models/schemas.py
  tests/test_coordinates.py
  tests/test_trajectory.py
  tests/test_controller.py
ml/
  generate_episodes.py
  train.py
  evaluate.py
  artifacts/
simulator/
  differential_drive.py
  run_episode.py
infra/
  README.md
```

### Implementación en orden

1.  Definir esquemas Pydantic para robot, misión, telemetría y eventos.
2.  Implementar conversión WGS84↔ENU y pruebas de ida/vuelta.
3.  Implementar `generate_waypoints(A,B,delta)` y
    `cross_track_error(A,B,P)`.
4.  Implementar simulador diferencial, controlador clásico y estados de
    misión.
5.  Implementar endpoints y WebSocket; probar con robot simulado.
6.  Integrar DynamoDB y operaciones idempotentes con
    `mission_id`/`sequence`.
7.  Generar dataset de episodios, entrenar y evaluar ML; activar
    inferencia solo tras superar criterios de prueba.
8.  Integrar hardware y calibración; empezar con velocidades muy bajas y
    zona de prueba controlada.

## 11. Infraestructura AWS Academy

1.  Comprobar servicios habilitados, región, duración del laboratorio,
    cuota y presupuesto.
2.  Crear roles/políticas IAM de privilegio mínimo para DynamoDB
    (lectura/escritura de tablas necesarias); evitar credenciales
    permanentes incrustadas.
3.  Crear tablas `Missions` y `Telemetry` con claves anteriores y modo
    de capacidad adecuado al laboratorio.
4.  Aprovisionar EC2 Linux con Python, HTTPS y servicio FastAPI
    gestionado (systemd o contenedor). Usar un proxy inverso para TLS y
    WSS; restringir puertos y orígenes CORS.
5.  Configurar variables `AWS_REGION`, `MISSIONS_TABLE`,
    `TELEMETRY_TABLE`, `ALLOWED_ORIGINS`, `MODEL_PATH`,
    `API_AUTH_CONFIG`.
6.  Servir el frontend compilado mediante hosting estático disponible o
    desde la misma EC2.
7.  Configurar autenticación del operador y del dispositivo, logs,
    límites de peticiones, retención de datos y alarmas básicas.
8.  Si el laboratorio expira, documentar cómo recrear tablas, variables
    y despliegue mediante scripts; no confiar en persistencia permanente
    de la cuenta.

**Seguridad operacional:** un botón de parada de emergencia físico/local
tiene prioridad; al perder telemetría válida, vencerse el comando o
excederse límites de precisión, el controlador debe detenerse de forma
segura. No depender del frontend para detener motores.

## 12. Plan de entregas

  -----------------------------------------------------------------------
  Fase                    Entregable verificable  Criterio de salida
  ----------------------- ----------------------- -----------------------
  1\. Matemática          `coordinates.py`,       Pruebas unitarias de
                          `trajectory.py`,        ruta, proyección y
                          `errors.py`             signos del error pasan

  2\. Simulador           Modelo diferencial +    Llega a B en escenarios
                          controlador base        nominales y reporta
                                                  métricas

  3\. API + Web           Selección de destino y  Operador inicia/cancela
                          trazas en vivo          misión simulada y ve
                                                  posición actualizada

  4\. Persistencia        DynamoDB + consulta de  Reconstruye misión
                          historial               completa y métricas sin
                                                  bloquear control

  5\. ML                  Dataset, entrenamiento, Comparativa
                          artefacto y evaluación  reproducible base
                                                  vs. ML con episodios no
                                                  vistos

  6\. Robot               Integración con         Prueba supervisada con
                          sensores y motores      límites, calibración y
                                                  parada segura
  -----------------------------------------------------------------------

## 13. Pruebas y criterios de aceptación

### Pruebas unitarias mínimas

-   A=(0,0), B=(10,0), P=(5,2): error lateral `+2 m`.
-   A=(0,0), B=(10,0), P=(5,-2): error lateral `-2 m`.
-   A=B: misión completada o rechazada sin división por cero.
-   Posición más allá de B: proyección limitada al extremo B.
-   Ángulos cercanos a ±π: `wrap_to_pi` produce el menor error angular.
-   GPS inválido, timestamps antiguos, secuencias duplicadas: telemetría
    rechazada o marcada inválida.
-   Pérdida de conexión o sensores: el robot se detiene localmente.

### Evaluación experimental

Ejecutar al menos 30 episodios de prueba por variante (orientativo) con
mismas semillas, distancias y perturbaciones. Reportar RMSE lateral,
error máximo, tasa de llegada, tiempo y esfuerzo de control. Definir
tolerancias según precisión del sensor real **antes** de evaluar; no
fijar objetivos inferiores a su incertidumbre. Registrar tablas y
gráficas en el informe.

### Definición de terminado (MVP)

-   El usuario puede seleccionar B y confirmar misión.
-   La web muestra posición real y trayectoria ideal/real diferenciadas.
-   El robot simulado alcanza B y corrige desviaciones sin depender de
    DynamoDB.
-   El historial puede reconstruirse tras reiniciar el frontend.
-   Existe un controlador base probado y una comparación cuantitativa
    con ML.
-   Hay mecanismo local de parada y validación de telemetría.
-   Se documentan precisión, limitaciones y condiciones de operación.

## 14. Riesgos y decisiones pendientes

  -----------------------------------------------------------------------
  Riesgo                              Mitigación
  ----------------------------------- -----------------------------------
  GPS convencional impreciso para     Medir error en campo; considerar
  prototipo pequeño                   RTK-GNSS, odometría e IMU/fusión
                                      sensorial

  Brújula perturbada                  Calibrar, filtrar y comprobar
                                      consistencia de rumbo

  Latencia/red intermitente           Control rápido local; buffer de
                                      telemetría y watchdog

  Modelo ML inestable                 Limitar salida; fallback a
                                      controlador base; pruebas offline

  AWS Academy restringe IoT Core      Usar HTTPS/WebSocket en EC2

  Costos/cuotas de mapas              MapLibre con proveedor de mosaicos
                                      apropiado; limitar solicitudes

  Diferencia entre simulador y robot  Calibrar cinemática, ruido,
                                      fricción, velocidad y actuadores
  -----------------------------------------------------------------------

**Decisiones que el equipo debe cerrar antes de conectar hardware:**
tipo de tracción, sensor de posición exacto y su precisión, sensor de
orientación, frecuencia de telemetría, tamaño del terreno, tolerancia de
llegada, velocidad máxima, conectividad y recursos habilitados en AWS
Academy.

## 15. Comandos iniciales de desarrollo

``` bash
# Backend
python -m venv .venv
source .venv/bin/activate
pip install fastapi 'uvicorn[standard]' pydantic boto3 numpy pyproj scikit-learn pytest
uvicorn app.main:app --reload

# Frontend (en otra terminal)
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install maplibre-gl
npm run dev
```

Los comandos presuponen que ya se creó la estructura del backend y su
módulo `app.main`; no son un proyecto ejecutable completo por sí solos.

## 16. Referencias técnicas

-   MapLibre GL JS: https://maplibre.org/maplibre-gl-js/docs/
-   MapTiler Cloud: https://docs.maptiler.com/cloud/api/
-   FastAPI: https://fastapi.tiangolo.com/
-   AWS DynamoDB:
    https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html
-   AWS IoT Core:
    https://docs.aws.amazon.com/iot/latest/developerguide/what-is-aws-iot.html
-   scikit-learn MLPRegressor:
    https://scikit-learn.org/stable/modules/generated/sklearn.neural_network.MLPRegressor.html
-   pyproj: https://pyproj4.github.io/pyproj/stable/

------------------------------------------------------------------------

**Resumen arquitectónico:** la web define B; el robot reporta A y su
estado; la geometría fija la trayectoria; el controlador local la sigue;
ML aprende ajustes acotados; AWS coordina y registra; DynamoDB almacena
el historial; el mapa visualiza, pero no decide por dónde conducir.
