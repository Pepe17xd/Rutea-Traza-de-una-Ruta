# Prueba GPS + Wi-Fi + telemetría

Proyecto separado del firmware principal y del diagnóstico GPS. Publicación y comandos remotos quedan deshabilitados en `platformio.ini` (`RUTEA_ENABLE_TELEMETRY=0`); en este estado solo informa GPS y asociación Wi-Fi. No implementa polling de comandos ni salidas de actuadores.

## Credenciales y seguridad

Copie `include/secrets.wifi.example.h` a `include/secrets.wifi.h` y complete localmente la contraseña Wi-Fi. El SSID `MARIA` está preconfigurado. Deje token, URL y CA vacíos mientras solo pruebe Wi-Fi. El archivo `secrets.wifi.h` coincide con la regla Git `**/secrets.*`; confirme con `git check-ignore include/secrets.wifi.h` antes de editarlo.

El firmware usa `X-Device-Token`, `POST /api/v1/telemetry` y CA obligatoria para HTTPS. La plantilla contiene la URL confirmada y Amazon Root CA 1; el token se mantiene local. La base termina en `/api/v1`; el cliente agrega `/telemetry`, evitando duplicar la ruta. No se contacta AWS durante compilación ni con la opción predeterminada.

## Wi-Fi y banda

ESP32 Dev Module usa Wi-Fi 2.4 GHz 802.11 b/g/n; no puede asociarse a una red exclusivamente 5 GHz. El usuario confirmó que MARIA ofrece 2.4 GHz, canal 8 y WPA2-Personal. Una vez cargado, `Wi-Fi: CONNECTED`, IP y RSSI confirman asociación del ESP32. El firmware no muestra SSID ni secretos.

## Construcción y ejecución futura

Compilar sin placa: `pio run -e gps_wifi_test`. La telemetría está desactivada por defecto.

La prueba de secuencia/ONE_SHOT portable se compila y ejecuta desde PowerShell:

```powershell
g++ -std=c++17 -Iinclude tests/test_sequence_oneshot.cpp -o tests/test_sequence_oneshot.exe
.\tests\test_sequence_oneshot.exe
```

ONE_SHOT queda además marcado en NVS antes del POST para que un reinicio tras el intento no lo repita. Las reservas guardan el próximo sequence en NVS antes de poner el evento en la cola. El valor `RUTEA_SEQUENCE_BASE` debe ser el último sequence confirmado por AWS; el dispositivo reserva primero base+1. NVS solo evita reutilización local: antes de probar, pause cualquier otro emisor de `CAR_01`, consulte el último valor en el backend y configure esa base en `secrets.wifi.h`. Un 409 exige parar y reconciliar manualmente.

Tras verificar banda, cableado/niveles GPS y archivo local, cargar explícitamente solo para probar asociación Wi-Fi:

```powershell
pio run -e gps_wifi_test -t upload --upload-port COM5
pio device monitor --port COM5 --baud 115200
```

La carga sustituye el programa activo, aunque mantiene envío deshabilitado.

## Habilitar POST controlado

Para un primer envío controlado, configure `RUTEA_SEQUENCE_BASE` con el último sequence verificado, mantenga único el emisor, y defina localmente `RUTEA_ENABLE_TELEMETRY=1` y `RUTEA_TELEMETRY_ONE_SHOT=1` en `platformio.ini`. ONE_SHOT hace un solo intento, persiste su latch antes de POST y no reintenta por respuesta HTTP ni timeout. Solo después de revisar config y autorizar, compile/cargue. No use ONE_SHOT=0 hasta aprobar posteriormente publicaciones periódicas. No consulta comandos ni implementa actuadores. Revise solo estado y código HTTP, nunca credenciales.

Restauración del firmware principal desde `Firmware/`: `pio run -e esp32dev -t upload --upload-port COM5`. Esto instala la versión que compile el checkout actual, no restaura necesariamente el binario anterior exacto.
