# Diagnóstico aislado NEO-6M

Proyecto PlatformIO independiente; no usa Wi-Fi, red, sensores I2C ni el firmware principal. No carga nada al compilar. Los pines y el baud son supuestos, no cableado verificado.

Antes de conectar o cargar: confirme la variante de ESP32 y el pinout del módulo GPS, alimentación VCC y GND común, y que TX del GPS tenga nivel lógico compatible con el RX del ESP32. Confirme GPS TX → GPIO16. GPIO17 es TX del ESP32 y solo se conecta a GPS RX si los niveles son compatibles; este diagnóstico no transmite al GPS. Verifique tensiones según las hojas técnicas de los módulos concretos. Desenergice antes de cambiar conexiones.

Desde esta carpeta:

```powershell
pio run -e gps_diagnostic
```

Solo tras verificar el hardware y autorizar la sustitución del programa instalado:

```powershell
pio run -e gps_diagnostic -t upload --upload-port COM5
pio device monitor --port COM5 --baud 115200
```

El monitor puede reiniciar la placa. Salga con Ctrl+C. Una frase NMEA con checksum válido recibida en los últimos 5 segundos indica comunicación; posición válida requiere además datos de posición recientes. Sin posición válida no necesariamente significa que falten satélites: puede haber recepción insuficiente o fix aún no disponible. Bytes sin frases válidas sugieren revisar baud, formato, niveles y cableado. Pruebe el GPS con antena y visión despejada del cielo.

## Restauración

La carga del diagnóstico sobrescribe el programa instalado; no realiza copia de seguridad. Para restaurar el firmware principal compilado desde el código actual, previa revisión de su configuración y autorización para sus comunicaciones de red:

```powershell
cd ..
pio run -e esp32dev -t upload --upload-port COM5
```

Esto instala la versión compilada desde el proyecto principal, no garantiza recuperar el binario previamente instalado ni su configuración exacta. No borra deliberadamente NVS, pero la compatibilidad y el estado persistente deben verificarse antes de restaurar.
