# HECTOR Firmware V1.2 (ESP32 Dev Module)

Firmware de adquisición para un ESP32 Dev Module con u-blox NEO-6M y MPU-6050. Solo lee sensores, informa diagnóstico y publica el contrato normalizado de HECTOR. No implementa PWM, driver ni movimiento de motores.

## Arquitectura

```text
UART hardware -> parser NMEA + UBX -> fix GPS ─┐
                                                ├-> telemetría JSON -> POST /api/v1/telemetry
I²C Wire -> MPU-6050 -> aceleración/gyro ───────┘      HTTP + X-Device-Token
Wi-Fi STA + NTP -> UTC; supervisor -> estado seguro; watchdog local -> reinicio si se bloquea el loop
```

`gps_parser.cpp` no depende de Arduino y valida checksum NMEA y UBX, límites de trama, coordenadas y emparejamiento. El sistema Python de V1.1 continúa siendo la implementación de estimación/ML; el ESP32 publica mediciones crudas sincronizadas y no migra modelos scikit-learn.

## Requisitos y compilación

- PlatformIO Core instalado en un entorno con acceso al registro de PlatformIO la primera vez.
- PlatformIO Espressif32 8.0.0, `board = esp32dev`, framework Arduino ESP32.
- El proyecto no añade paquetes de terceros: usa Wi-Fi, HTTP/TLS, UART e I²C del framework Arduino-ESP32. El parser NMEA/UBX es código acotado del proyecto.

Desde `Firmware/`:

```powershell
pio run -e esp32dev
pio test -e native
pio device monitor -b 115200
```

`pio run` compila solamente; no flashea la placa. Para instalar PlatformIO en un entorno permitido: `python -m pip install platformio`. Si el registro no está disponible, la recuperación es instalar PlatformIO y descargar `platformio/espressif32@8.0.0` en una máquina con acceso, o usar un agente de CI con caché de paquetes. No se debe reportar la compilación como aprobada hasta ejecutar `pio run`.

## Configuración local

Copie `include/hector/secrets.example.h` como `include/hector/secrets.h` y complete localmente SSID, contraseña, URL base y token. El archivo local está ignorado por Git. Para HTTPS, proporcione un certificado CA PEM en `HECTOR_TLS_CA_CERT`; el cliente rechaza HTTPS sin CA y nunca deshabilita la validación TLS. HTTP sirve para una red de laboratorio controlada.

Configure `DEVICE_TOKEN` en `Backend/.env` y use el mismo valor como `HECTOR_DEVICE_TOKEN`. El ESP32 publica exactamente a `POST {HECTOR_API_BASE_URL}/api/v1/telemetry` mediante `X-Device-Token`. No se crea otro endpoint. `robot_id` debe coincidir con `VITE_ROBOT_ID`; el ID del dispositivo permanece estable y la secuencia se persiste en NVS.

La placa obtiene UTC por SNTP. No publica hasta que la hora del sistema sea razonable. Reintenta Wi-Fi con espera exponencial acotada; publica heartbeat nominal cada 1000 ms con dos intentos HTTP de timeout limitado. Reintenta la misma secuencia para el mismo evento y avanza NVS al aceptar. Revise en el monitor serie líneas `telemetry accepted` o `telemetry not accepted` (incluye código HTTP, nunca imprime credenciales).

## Interfaces lógicas

- **GPS:** UART2 de ESP32, 9600 baudios, 8N1 por defecto. GPIO RX/TX y baud son macros configurables. El NEO-6M usa típicamente NMEA a 1 Hz, pero la tasa y la salida UBX dependen de la configuración concreta del receptor.
- **IMU:** I²C `Wire`, dirección 0x68 por defecto (configurable; algunos módulos exponen 0x69). El firmware configura ±2 g y ±250 °/s, lee a 20 Hz, valida WHO_AM_I y rangos, y estima sesgo giroscópico con 200 muestras al inicio. Durante calibración el módulo debe permanecer inmóvil. Una calibración no estacionaria impide READY.
- **Parada de emergencia:** existe el estado e interfaz `SafetySupervisor::setEstopActive`, sin asignar GPIO ni asumir polaridad, resistencia o circuito. Debe integrarse con un circuito local seguro una vez conocida la placa y el sistema eléctrico.

Estos son mapeos lógicos editables, no una instrucción de cableado. Verifique el pinout de la variante exacta de ESP32 y de los módulos portadores, sus niveles lógicos y alimentación con las hojas técnicas correspondientes antes de conectar. Aquí no se fija tensión, conexión física ni pin de E-stop.

## GPS y precisión

El parser reconoce RMC (coordenadas, fecha/hora UTC, velocidad en nudos convertida a m/s, curso) y GGA (calidad de fix, satélites, HDOP). Sin fix no entrega latitud/longitud. Valida el checksum NMEA y descarta tramas mal formadas o coordenadas fuera de WGS84. 9600 baudios y 1 Hz son valores de referencia habituales, configurables.

El NEO-6M suele emitir NMEA por defecto; no se supone que NAV-POSLLH esté habilitado. Para recibir `hAcc`, configure el receptor concreto mediante una herramienta u-blox compatible para emitir `UBX-NAV-POSLLH` y `UBX-NAV-TIMEUTC` por su UART. El firmware valida clases/IDs, longitud exacta, checksum UBX, flags UTC, mismo `iTOW`, correspondencia UTC con RMC y proximidad entre coordenadas UBX/NMEA antes de asociar `hAcc`. Por defecto no cambia la salida del receptor. Para solicitar mensajes UBX al iniciar, agregue `-DHECTOR_ENABLE_UBX_OUTPUTS=1` a los build_flags de PlatformIO; el firmware envía CFG-MSG NAV-POSLLH y NAV-TIMEUTC a 1 Hz por UART1. No espera ni declara un ACK: valide hAcc en telemetría. También se pueden habilitar con una herramienta u-blox compatible. Si no llegan ambos mensajes UBX válidos, `gps_accuracy_m` es `null`; HDOP nunca se convierte a metros.

`UBX-NAV-POSLLH.hAcc` se transmite en metros con `gps_accuracy_source="UBX_NAV_POSLLH.hAcc"`, `gps_accuracy_status="ESTIMATED"` y `gps_accuracy_is_bound=false`. Es una estimación del receptor, no una medida independiente ni un límite de error garantizado. FastAPI y la interfaz no la usan para autorizar una misión física. Se necesita una fuente de incertidumbre/cota validada para habilitar esa operación.

## MPU-6050 y rumbo

Las muestras incluyen aceleración en m/s² y velocidad angular en rad/s con tiempos derivados de UTC sincronizado y marcas monotónicas de adquisición. El MPU-6050 carece de magnetómetro. No se publica una orientación absoluta integrada desde el gyro; el firmware declara fuente/rumbo no disponible hasta recibir curso GPS válido con velocidad suficiente. La integración relativa y la estimación de incertidumbre permanecen en el estimador Python V1.1; integrarla requiere calibración y validación adicionales.

## Estados, fallos y límites

- `DISCONNECTED`: Wi-Fi sin enlace.
- `CONNECTED`: Wi-Fi enlazado mientras aún no se ha recibido la primera muestra de GPS o IMU; no autoriza movimiento.
- `GPS_NO_FIX`: no hay fix válido o está caduco.
- `READY`: GPS fresco con al menos 4 satélites y HDOP presente de 5.0 o menor, e IMU presente, calibrada y fresca. Son umbrales configurables en `config.h`. Solo significa que hay sensores disponibles; no autoriza movimiento.
- `SENSOR_ERROR`: IMU desconectada, inválida o caducada.
- `ESTOP`: reservado para entrada local futura; no se asume circuito físico.

El watchdog de tarea local reinicia el ESP32 si el loop deja de ejecutarse. No implementa la parada de motores: no hay salidas de motor en el firmware. La pérdida de Wi-Fi solo detiene la publicación; no hay tarea de movimiento que pueda continuar sin supervisión. Una solicitud remota de parada de HECTOR sigue sin confirmar una parada física.

## Contrato de telemetría

Todos los campos de V1.1 se mantienen. Los valores desconocidos son `null`, y el objeto `sensor_status` incluye conectividad ESP32/Wi-Fi, estado de seguridad/sensores, errores/checksums acumulados y frecuencia de publicación. `timestamp` viene de SNTP; `gps_timestamp` viene de UTC NMEA y `imu_timestamp` mapea el instante monotónico de muestra a UTC.

```json
{
  "robot_id":"CAR_01","device_id":"esp32-hector-01","mission_id":null,
  "sequence":12,"timestamp":"2026-11-04T12:00:00Z",
  "lat":-12.0464,"lon":-77.0428,"heading_deg":null,"speed_mps":0.514,
  "gps_accuracy_m":1.234,"gps_accuracy_status":"ESTIMATED",
  "gps_accuracy_source":"UBX_NAV_POSLLH.hAcc","gps_accuracy_is_bound":false,
  "gps_fix_valid":true,"gps_satellites":8,"gps_hdop":0.9,"gps_course_deg":90.0,
  "imu_accel_mps2":{"x":0,"y":0,"z":9.8067},"imu_gyro_rps":{"x":0,"y":0,"z":0.01},
  "heading_source":"unknown","heading_quality":"UNAVAILABLE_NO_MAGNETOMETER",
  "gps_timestamp":"2026-11-04T12:00:00Z","imu_timestamp":"2026-11-04T12:00:00Z",
  "sensor_timestamp":"2026-11-04T12:00:00Z",
  "sensor_status":{"esp32":"CONNECTED","wifi":"CONNECTED","safety":"READY","gps":"FIX_VALID","imu":"CONNECTED"},
  "data_source":"PHYSICAL","status":"IDLE"
}
```

La secuencia es monótona por NVS. Cada petición fallida se reintenta con límites y no se acumula cola de datos que ya podrían estar antiguos. El backend realiza su validación de edad, fuente, dispositivo y secuencia y contesta errores HTTP sin que el firmware declare una misión completada.

## Pruebas y diagnóstico

Las pruebas Unity nativas en `test/test_gps_parser/` cubren RMC/GGA, conversión de unidades, checksum NMEA/UBX, fix inválido y `hAcc` solo cuando tiempo y `iTOW` coinciden. El smoke test host `tests/host_parser_test.cpp` se compila con `g++ -std=c++17 -IFirmware/include -IFirmware/lib/hector_firmware/include Firmware/lib/hector_firmware/src/gps_parser.cpp Firmware/tests/host_parser_test.cpp -o hector_parser_tests.exe` y se ejecuta con `./hector_parser_tests.exe`. Son pruebas sin hardware físico. También hay contrato Pydantic/API en `Backend/tests/test_esp32_contract.py` y cobertura de endpoint en `Backend/tests/test_api.py`.

1. `pio test -e native` para parser y checksums sin placa.
2. `pio run -e esp32dev` para compilar; `pio device monitor -b 115200` para diagnóstico serie.
3. Enviar un payload de prueba controlado al backend y comprobar que `GET /api/v1/robots/CAR_01/latest` muestra `device_status=CONECTADO` y `data_source=PHYSICAL`.
4. Para NMEA real, use una grabación con parser de Python V1.1 o reproduzca las frases NMEA por un UART USB compatible. No declare reproducción grabada como dispositivo físico.
5. Revise contador de errores de checksum, `gps=NO_FIX/STALE`, `imu_error`, hora SNTP y código HTTP. Un `401` indica token incorrecto; un `422` indica contrato, timestamp o datos inválidos.

El test nativo del parser no valida radio Wi-Fi, calibración física, precisión del GPS, temporización eléctrica, niveles lógicos ni el montaje. Eso queda pendiente de probar con la variante real de placa, módulos, antena y alimentación.

## Pendiente de hardware

Faltan validar la revisión exacta de ESP32 Dev Module, módulo/antena NEO-6M, breakout MPU-6050, niveles eléctricos y alimentación; integración física de E-stop; controladora, motores, tracción y odometría. No se compilan comandos de motor ni se descarga/ejecuta una misión. `MissionEnvelopeV1` reserva un contrato local versionado; todavía no hay endpoint de descarga ni protocolo remoto de comandos. ML queda en Python y nunca se aplica a motores.



## Descarga Wi-Fi de destinos (contrato v1)

El firmware conserva su POST de telemetría y consulta cada ~1 s `GET /api/v1/robots/{robot_id}/commands/next`, enviando `X-Device-Token`. `204` significa que no hay comando. `200` trae `text/plain` con la línea exacta `G:<latitud>,<longitud>\n` y headers `X-Protocol-Version`, `X-Mission-Id`, `X-Command-Sequence` y `X-Command-Expires-At`. El ESP32 comprueba formato/rangos, hora NTP y expiración, y registra secuencia/mission ID en NVS. Después confirma la recepción por `POST /api/v1/robots/{robot_id}/commands/{mission_id}/ack`, incluyendo secuencia, estado y payload. Un ACK perdido permite reenvío idempotente; una secuencia anterior se rechaza. Una respuesta HTTP 200 al crear/consultar una misión no confirma que el ESP32 la recibió. La misión continúa `PENDING` hasta el ACK y solo pasa a `ACTIVE` por una observación posterior de movimiento.

La descarga y ACK son de datos por Wi-Fi, no comandos de actuadores. Las desconexiones pausan polling; el administrador Wi-Fi vuelve a intentar con espera progresiva. El contrato v1 no interpreta destinos como permiso para moverse.

## Bomba y Bluetooth (interfaz sin salida física)

El parser del contrato reconoce solo bytes `ON` u `OFF`, sensibles a mayúsculas y sin terminador adicional. `PumpDecision` inicia con solicitud `OFF`, sin autorización y sin estado físico confirmado. Autorizar `ON` necesita GPS válido/fresco, avance confirmado, vehículo no girando sobre el eje ni detenido, comunicación sana, E-stop libre y feedback físico disponible. Ningún GPIO/relé está declarado ni se energiza; pasar el predicado solo es autorización lógica para una futura etapa. El frontend llama al simulador backend, que informa `SIMULATED`, recepción simulada, autorización denegada, estado confirmado desconocido y salida física deshabilitada.

Web Bluetooth es GATT sobre BLE. No proporciona RFCOMM/SPP clásico desde JavaScript web; Chrome remite esos periféricos a Web Serial si exponen una interfaz serial. No está decidido que el ESP32 concreto ni el navegador elegido tengan el modo/servicio compatible; no se implementa todavía una conexión Bluetooth. La versión de módulo ESP32 y servicios disponibles requieren confirmación exacta.

### Tests del protocolo

`test/test_protocol_safety/test_main.cpp` contiene pruebas Unity nativas de destino, caducidad/idempotencia, palabras exactas y enclavamientos. `tests/host_mission_pump_test.cpp` permite compilar esas reglas portables con g++:

```powershell
& 'C:\msys64\mingw64\bin\g++.exe' -std=c++17 -Iinclude tests/host_mission_pump_test.cpp -o tests/host_mission_pump_test.exe
.\tests\host_mission_pump_test.exe
```

`pio run -e esp32dev` y `pio test -e native` siguen siendo los comandos de build firmware cuando PlatformIO esté instalado. La prueba host no sustituye la compilación Arduino ni una prueba real de Wi-Fi, NVS, GPS o I²C.
