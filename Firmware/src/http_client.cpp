#include "hector/http_client.h"
#include "hector/config.h"
#include "hector/mission_protocol.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

namespace hector {
static bool beginHttp(HTTPClient &http, WiFiClientSecure &secureClient, const String &url) {
  http.setConnectTimeout(2500); http.setTimeout(2500); http.setReuse(false);
  if(url.startsWith("https://")) {
    if(strlen(HECTOR_TLS_CA_CERT)==0) return false;
    secureClient.setCACert(HECTOR_TLS_CA_CERT);
    return http.begin(secureClient,url);
  }
  if(url.startsWith("http://")) return http.begin(url);
  return false;
}

static PostResult onePost(const String &json) {
  PostResult result;
  if(!WiFi.isConnected()) { result.message="WIFI_DISCONNECTED"; return result; }
  if(strlen(HECTOR_API_BASE_URL)==0 || strlen(HECTOR_DEVICE_TOKEN)==0) { result.message="API_URL_OR_DEVICE_TOKEN_MISSING"; return result; }
  String base=HECTOR_API_BASE_URL; while(base.endsWith("/")) base.remove(base.length()-1);
  const String url=base+"/api/v1/telemetry";
  HTTPClient http;
  WiFiClientSecure secureClient;
  if(!beginHttp(http,secureClient,url)) { result.message=url.startsWith("https://")?"TLS_CA_CERT_REQUIRED_OR_HTTP_BEGIN_FAILED":"API_URL_MUST_USE_HTTP_OR_HTTPS"; return result; }
  http.addHeader("Content-Type","application/json"); http.addHeader("X-Device-Token",HECTOR_DEVICE_TOKEN);
  const int code=http.POST((uint8_t*)json.c_str(),json.length());
  result.http_status=code; result.accepted=code>=200&&code<300;
  result.message=result.accepted?"ACCEPTED":("HTTP_"+String(code)); http.end(); return result;
}
PostResult postTelemetry(const String &json) {
  PostResult result;
  for(int attempt=0;attempt<2;attempt++) {
    result=onePost(json); if(result.accepted || (result.http_status>=400 && result.http_status<500)) break;
    if(attempt==0) delay(250);
  }
  return result;
}

DestinationPollResult pollNextDestination() {
  DestinationPollResult result;
  if(!WiFi.isConnected()) { result.error="WIFI_DISCONNECTED"; return result; }
  if(strlen(HECTOR_API_BASE_URL)==0 || strlen(HECTOR_DEVICE_TOKEN)==0) { result.error="API_URL_OR_DEVICE_TOKEN_MISSING"; return result; }
  String base=HECTOR_API_BASE_URL; while(base.endsWith("/")) base.remove(base.length()-1);
  const String url=base+"/api/v1/robots/"+HECTOR_ROBOT_ID+"/commands/next";
  HTTPClient http; WiFiClientSecure secureClient;
  if(!beginHttp(http,secureClient,url)) { result.error="HTTP_BEGIN_FAILED_OR_TLS_CA_MISSING"; return result; }
  const char *headers[]={"X-Protocol-Version","X-Mission-Id","X-Command-Sequence","X-Command-Expires-At"};
  http.collectHeaders(headers,4); http.addHeader("X-Device-Token",HECTOR_DEVICE_TOKEN);
  const int code=http.GET(); result.http_status=code;
  if(code==204) { http.end(); return result; }
  if(code!=200) { result.error="HTTP_"+String(code); http.end(); return result; }
  const String version=http.header("X-Protocol-Version");
  result.mission_id=http.header("X-Mission-Id");
  result.sequence=strtoull(http.header("X-Command-Sequence").c_str(),nullptr,10);
  result.expires_at_epoch_s=strtoull(http.header("X-Command-Expires-At").c_str(),nullptr,10);
  result.payload=http.getString();
  if(version!="1" || result.mission_id.length()==0 || result.sequence==0 || result.expires_at_epoch_s==0
      || !parseDestinationLine(result.payload.c_str(),result.payload.length(),result.destination)) {
    result.error="INVALID_DESTINATION_ENVELOPE"; http.end(); return result;
  }
  result.available=true; http.end(); return result;
}

PostResult acknowledgeDestination(const String &missionId, uint64_t sequence, const String &payload, const String &status) {
  PostResult result;
  if(!WiFi.isConnected()) { result.message="WIFI_DISCONNECTED"; return result; }
  if(strlen(HECTOR_API_BASE_URL)==0 || strlen(HECTOR_DEVICE_TOKEN)==0) { result.message="API_URL_OR_DEVICE_TOKEN_MISSING"; return result; }
  if(status!="RECEIVED" && status!="REJECTED_EXPIRED" && status!="REJECTED_DUPLICATE" && status!="REJECTED_INVALID") { result.message="INVALID_ACK_STATUS"; return result; }
  String base=HECTOR_API_BASE_URL; while(base.endsWith("/")) base.remove(base.length()-1);
  const String url=base+"/api/v1/robots/"+HECTOR_ROBOT_ID+"/commands/"+missionId+"/ack";
  String escaped=payload;
  escaped.replace("\\", "\\\\"); escaped.replace("\"", "\\\"");
  escaped.replace("\n", "\\n"); escaped.replace("\r", "\\r");
  char sequenceText[24]; snprintf(sequenceText,sizeof(sequenceText),"%llu",(unsigned long long)sequence);
  const String json="{\"sequence\":"+String(sequenceText)+",\"status\":\""+status+"\",\"payload\":\""+escaped+"\"}";
  HTTPClient http; WiFiClientSecure secureClient;
  if(!beginHttp(http,secureClient,url)) { result.message="HTTP_BEGIN_FAILED_OR_TLS_CA_MISSING"; return result; }
  http.addHeader("Content-Type","application/json"); http.addHeader("X-Device-Token",HECTOR_DEVICE_TOKEN);
  const int code=http.POST((uint8_t*)json.c_str(),json.length());
  result.http_status=code; result.accepted=code>=200&&code<300; result.message=result.accepted?"DESTINATION_ACK_ACCEPTED":"HTTP_"+String(code); http.end();
  return result;
}
}
