# RUTEA ONE_SHOT rearm utility

This isolated ESP-IDF/PlatformIO project uses the same ESP32 default partition
map as `gps_wifi_test` (`nvs` at `0x9000`, size `0x5000`). It avoids Arduino
startup, Wi-Fi, HTTP, telemetry, TLS, and application-created worker tasks.

The utility stops without changing NVS unless both preconditions match exactly:
`rutea-gps/seq_next` is `uint64_t 2` and `rutea-gps/oneshot_done` is `uint8_t 1`.
It then writes only `oneshot_done=0`, commits, reads both keys back, and stops.
There is no NVS erase, format, namespace clear, or sequence write. Any NVS init,
open, type, read, or precondition error stops without attempting the rearm.

Build only (does not run the utility or access the ESP32):

```powershell
$env:PLATFORMIO_CORE_DIR = (Resolve-Path 'Firmware/.platformio-core').Path
pio run -d Firmware/gps_wifi_telemetry/oneshot_rearm -e rearm
```

The rearm itself requires a later explicit upload to COM5. After the serial
monitor reports `REARM_SUCCESS`, upload the normal firmware with the separate
`gps_wifi_oneshot` PlatformIO environment. The normal diagnostic environment
`gps_wifi_test` remains telemetry-off by default.
