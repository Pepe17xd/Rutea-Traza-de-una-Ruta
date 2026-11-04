#include "hector/wifi_manager.h"
#include "hector/config.h"
#include <WiFi.h>
namespace hector {
void WifiManager::begin() { WiFi.mode(WIFI_STA); begun_=true; tick(); }
void WifiManager::tick() {
  if(!begun_) return;
  if(WiFi.status()==WL_CONNECTED) { reconnect_.reset(); return; }
  const uint32_t now=millis(); if(!reconnect_.due(now)) return;
  if(strlen(HECTOR_WIFI_SSID)==0) { reconnect_.schedule(now); return; }
  WiFi.begin(HECTOR_WIFI_SSID,HECTOR_WIFI_PASSWORD);
  reconnect_.schedule(now);
}
bool WifiManager::connected() const { return WiFi.status()==WL_CONNECTED; }
}
