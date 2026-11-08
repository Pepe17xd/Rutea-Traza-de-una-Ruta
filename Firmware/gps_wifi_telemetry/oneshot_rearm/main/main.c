#include <inttypes.h>
#include <stdio.h>
#include <stdint.h>

#include "esp_err.h"
#include "nvs.h"
#include "nvs_flash.h"

static void report_error(const char *operation, esp_err_t err) {
    printf("%s: %s (0x%08" PRIX32 ")\n", operation, esp_err_to_name(err), (uint32_t)err);
}

void app_main(void) {
    printf("RUTEA ONE_SHOT maintenance; no Wi-Fi/HTTP/telemetry.\n");

    // Deliberately stop on every init error. Never erase or format NVS here.
    esp_err_t err = nvs_flash_init();
    if (err != ESP_OK) {
        report_error("NVS_INIT_ERROR; no erase/format attempted", err);
        return;
    }

    nvs_handle_t handle;
    err = nvs_open("rutea-gps", NVS_READONLY, &handle);
    if (err != ESP_OK) {
        report_error("NVS_OPEN_READONLY_ERROR; no write attempted", err);
        return;
    }

    uint64_t sequence_before = 0;
    uint8_t oneshot_before = 0;
    err = nvs_get_u64(handle, "seq_next", &sequence_before);
    if (err != ESP_OK) {
        report_error("seq_next_READ_ERROR; no write attempted", err);
        nvs_close(handle);
        return;
    }
    err = nvs_get_u8(handle, "oneshot_done", &oneshot_before);
    if (err != ESP_OK) {
        report_error("oneshot_done_READ_ERROR; no write attempted", err);
        nvs_close(handle);
        return;
    }

    printf("PRECHECK seq_next=%" PRIu64 " oneshot_done=%u\n",
           sequence_before, (unsigned)oneshot_before);
    nvs_close(handle);

    if (sequence_before != 2 || oneshot_before != 1) {
        printf("REARM_ABORTED: expected seq_next=2 and oneshot_done=1; NVS unchanged.\n");
        return;
    }

    // Reopen read/write only after validating both preconditions. Write only
    // the oneshot_done key; seq_next is never passed to a write API.
    err = nvs_open("rutea-gps", NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        report_error("NVS_OPEN_READWRITE_ERROR; no key changed", err);
        return;
    }

    uint64_t sequence_recheck = 0;
    uint8_t oneshot_recheck = 0;
    err = nvs_get_u64(handle, "seq_next", &sequence_recheck);
    if (err == ESP_OK) err = nvs_get_u8(handle, "oneshot_done", &oneshot_recheck);
    if (err != ESP_OK) {
        report_error("PREWRITE_RECHECK_ERROR; no write attempted", err);
        nvs_close(handle);
        return;
    }
    if (sequence_recheck != 2 || oneshot_recheck != 1) {
        printf("REARM_ABORTED: NVS changed since precheck; no write attempted.\n");
        nvs_close(handle);
        return;
    }

    err = nvs_set_u8(handle, "oneshot_done", 0);
    if (err == ESP_OK) err = nvs_commit(handle);
    if (err != ESP_OK) {
        report_error("oneshot_done_WRITE_OR_COMMIT_ERROR", err);
        nvs_close(handle);
        return;
    }

    uint64_t sequence_after = 0;
    uint8_t oneshot_after = 0xff;
    err = nvs_get_u64(handle, "seq_next", &sequence_after);
    if (err == ESP_OK) err = nvs_get_u8(handle, "oneshot_done", &oneshot_after);
    if (err != ESP_OK) {
        report_error("VERIFY_READ_ERROR", err);
        nvs_close(handle);
        return;
    }

    printf("VERIFY seq_next=%" PRIu64 " oneshot_done=%u\n",
           sequence_after, (unsigned)oneshot_after);
    if (sequence_after == 2 && oneshot_after == 0) {
        printf("REARM_SUCCESS: only oneshot_done changed; stopped.\n");
    } else {
        printf("REARM_VERIFY_FAILED: inspect NVS; do not enable telemetry.\n");
    }
    nvs_close(handle);
    return;
}
