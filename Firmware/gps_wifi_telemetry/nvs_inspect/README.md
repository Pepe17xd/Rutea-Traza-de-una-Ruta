# Inspección NVS de solo lectura

Este entorno usa ESP-IDF directamente (no Arduino) e inicializa la consola UART sin invocar `initArduino()`. Esto evita la inicialización Arduino que, en este framework, borra NVS automáticamente ante ciertos errores. Luego llama `nvs_flash_init()` sin ninguna ruta de erase y abre `rutea-gps` con `nvs_open(..., NVS_READONLY, ...)`; lee `seq_next` como u64 y `oneshot_done` como u8. No inicia Wi-Fi, HTTP ni llama funciones NVS de escritura/borrado/formateo. Si la namespace falta informa `NVS_EMPTY`; claves ausentes y tipos incorrectos se distinguen. Los errores muestran nombre y código ESP-IDF y detienen la lectura sin reparación.

Compilar sin placa: `pio run -e nvs_inspect` desde esta carpeta.

Para leer la NVS física hay que cargar temporalmente este inspector y abrir el monitor serie a 115200. La carga reemplaza el firmware activo; conserva el diagnóstico GPS y firmware principal en sus proyectos fuente. No uses erase flash ni limpies la namespace. Tras registrar ambos valores, restaura el firmware ONE_SHOT con sus flags y configuración originales. Esto requiere autorización de carga y no es parte de la compilación.
