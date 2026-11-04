#pragma once

// Copy secrets.example.h to secrets.h and edit locally. Empty defaults compile safely.
#if __has_include("secrets.h")
#include "secrets.h"
#else
#define HECTOR_WIFI_SSID ""
#define HECTOR_WIFI_PASSWORD ""
#define HECTOR_DEVICE_TOKEN ""
#define HECTOR_API_BASE_URL ""
#define HECTOR_TLS_CA_CERT ""
#endif
#ifndef HECTOR_WIFI_SSID
#define HECTOR_WIFI_SSID ""
#endif
#ifndef HECTOR_WIFI_PASSWORD
#define HECTOR_WIFI_PASSWORD ""
#endif
#ifndef HECTOR_DEVICE_TOKEN
#define HECTOR_DEVICE_TOKEN ""
#endif
#ifndef HECTOR_API_BASE_URL
#define HECTOR_API_BASE_URL ""
#endif
#ifndef HECTOR_TLS_CA_CERT
#define HECTOR_TLS_CA_CERT ""
#endif

#ifndef HECTOR_ROBOT_ID
#define HECTOR_ROBOT_ID "CAR_01"
#endif
#ifndef HECTOR_DEVICE_ID
#define HECTOR_DEVICE_ID "esp32-hector-01"
#endif
#ifndef HECTOR_GPS_BAUD
#define HECTOR_GPS_BAUD 9600
#endif
#ifndef HECTOR_GPS_RX_PIN
#define HECTOR_GPS_RX_PIN 16
#endif
#ifndef HECTOR_GPS_TX_PIN
#define HECTOR_GPS_TX_PIN 17
#endif
#ifndef HECTOR_IMU_SDA_PIN
#define HECTOR_IMU_SDA_PIN 21
#endif
#ifndef HECTOR_IMU_SCL_PIN
#define HECTOR_IMU_SCL_PIN 22
#endif
#ifndef HECTOR_IMU_ADDRESS
#define HECTOR_IMU_ADDRESS 0x68
#endif
#ifndef HECTOR_ENABLE_UBX_OUTPUTS
#define HECTOR_ENABLE_UBX_OUTPUTS 0
#endif
#ifndef HECTOR_GPS_MAX_AGE_MS
#define HECTOR_GPS_MAX_AGE_MS 3500
#endif
#ifndef HECTOR_GPS_MIN_SATELLITES
#define HECTOR_GPS_MIN_SATELLITES 4
#endif
#ifndef HECTOR_GPS_MAX_HDOP
#define HECTOR_GPS_MAX_HDOP 5.0f
#endif
#ifndef HECTOR_IMU_MAX_AGE_MS
#define HECTOR_IMU_MAX_AGE_MS 500
#endif
#ifndef HECTOR_HEARTBEAT_MS
#define HECTOR_HEARTBEAT_MS 1000
#endif
#ifndef HECTOR_COMMAND_POLL_MS
#define HECTOR_COMMAND_POLL_MS 10000
#endif
