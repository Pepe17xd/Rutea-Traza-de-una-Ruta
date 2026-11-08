#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "driver/uart.h"
#include "esp_err.h"
#include "esp_vfs_dev.h"
#include "nvs.h"
#include "nvs_flash.h"

static void report_error(const char *context, esp_err_t err) {
    printf("%s: %s (0x%08" PRIX32 ")\n", context, esp_err_to_name(err), (uint32_t)err);
}

static void inspect_u64(nvs_handle_t handle, const char *key) {
    uint64_t value = 0;
    const esp_err_t err = nvs_get_u64(handle, key, &value);
    if (err == ESP_OK) printf("%s=%" PRIu64 "\n", key, value);
    else if (err == ESP_ERR_NVS_NOT_FOUND) printf("%s=KEYS_NOT_FOUND\n", key);
    else if (err == ESP_ERR_NVS_TYPE_MISMATCH) report_error("seq_next KEY_TYPE_MISMATCH", err);
    else report_error("seq_next READ_ERROR", err);
}

static void inspect_bool_u8(nvs_handle_t handle, const char *key) {
    uint8_t value = 0;
    const esp_err_t err = nvs_get_u8(handle, key, &value);
    if (err == ESP_OK && value <= 1) printf("%s=%s\n", key, value ? "true" : "false");
    else if (err == ESP_OK) printf("%s=INVALID_BOOL_VALUE (%u)\n", key, value);
    else if (err == ESP_ERR_NVS_NOT_FOUND) printf("%s=KEYS_NOT_FOUND\n", key);
    else if (err == ESP_ERR_NVS_TYPE_MISMATCH) report_error("oneshot_done KEY_TYPE_MISMATCH", err);
    else report_error("oneshot_done READ_ERROR", err);
}

void app_main(void) {
    // Use UART0 directly. Do not start Arduino core (it auto-erases NVS for
    // ESP_ERR_NVS_NO_FREE_PAGES / ESP_ERR_NVS_NEW_VERSION_FOUND).
    uart_driver_install(UART_NUM_0, 1024, 0, 0, NULL, 0);
    esp_vfs_dev_uart_use_driver(UART_NUM_0);
    uart_set_baudrate(UART_NUM_0, 115200);
    printf("RUTEA NVS read-only inspector (ESP-IDF); no Wi-Fi/network.\n");

    esp_err_t err = nvs_flash_init();
    if (err != ESP_OK) {
        report_error("NVS_INIT_ERROR; partition not erased/formatted", err);
        return;
    }

    nvs_handle_t handle;
    err = nvs_open("rutea-gps", NVS_READONLY, &handle);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        printf("NVS_EMPTY: namespace rutea-gps does not exist.\n");
        printf("seq_next=KEYS_NOT_FOUND\noneshot_done=KEYS_NOT_FOUND\n");
        return;
    }
    if (err != ESP_OK) {
        report_error("NVS_NAMESPACE_OPEN_ERROR; read-only", err);
        return;
    }

    inspect_u64(handle, "seq_next");
    inspect_bool_u8(handle, "oneshot_done");
    nvs_close(handle);
}
