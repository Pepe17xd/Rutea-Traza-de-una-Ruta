"""Host-side NEO-6M/MPU-6050 to HECTOR HTTP telemetry gateway.

This process publishes observations only. It does not receive or issue motor
commands and remains independent of any not-yet-selected controller board.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
import threading
import time

import httpx

from app.sensors.estimator import StateEstimator
from app.sensors.mpu6050 import Mpu6050Adapter, Mpu6050Config
from app.sensors.nmea import GpsFix, Neo6mAdapter, Neo6mConfig
from app.sensors.contracts import estimate_to_telemetry


log=logging.getLogger("hector.sensor_gateway")


@dataclass(frozen=True)
class GatewayConfig:
    robot_id: str
    device_id: str
    api_url: str="http://127.0.0.1:8000"
    device_token: str=""
    imu_frequency_hz: float=20.0
    publish_frequency_hz: float=5.0
    request_timeout_s: float=2.0

    def __post_init__(self):
        if not self.robot_id or not self.device_id or not self.api_url:
            raise ValueError("robot_id, device_id and api_url are required")
        if min(self.imu_frequency_hz,self.publish_frequency_hz,self.request_timeout_s)<=0:
            raise ValueError("Gateway frequencies and request timeout must be positive")


class SensorGateway:
    def __init__(self,config:GatewayConfig,gps:Neo6mAdapter,imu:Mpu6050Adapter,
                 estimator:StateEstimator|None=None,http_client=None):
        self.config=config; self.gps=gps; self.imu=imu
        self.estimator=estimator or StateEstimator()
        self.http_client=http_client
        self._lock=threading.Lock(); self._sequence=0

    def ingest_gps(self,fix:GpsFix)->bool:
        with self._lock:
            accepted=self.estimator.ingest_gps(fix)
            return accepted

    def ingest_imu(self,reading)->bool:
        with self._lock:
            return self.estimator.ingest_imu(reading)

    def snapshot(self):
        with self._lock:
            estimate=self.estimator.estimate()
            self._sequence+=1
            return estimate_to_telemetry(estimate,robot_id=self.config.robot_id,
                device_id=self.config.device_id,sequence=self._sequence,
                timestamp=datetime.now(timezone.utc),status="IDLE")

    def _gps_worker(self,stop:threading.Event):
        last_key=None
        while not stop.is_set():
            try:
                fix=self.gps.read()
                if fix is not None:
                    key=(fix.sensor_timestamp,fix.status,fix.latitude,fix.longitude,fix.satellites,fix.hdop)
                    if key!=last_key:
                        self.ingest_gps(fix); last_key=key
                with self._lock:
                    if self.gps.status!="DISCONNECTED": self.estimator.mark_data_source("PHYSICAL")
                    self.estimator.mark_sensor_status("gps",self.gps.status)
                if fix is None:
                    stop.wait(.02)
            except Exception as exc:
                log.exception("GPS worker failed: %s",exc)
                with self._lock: self.estimator.mark_sensor_status("gps","ERROR")
                stop.wait(.1)

    def _imu_worker(self,stop:threading.Event):
        interval=1.0/self.config.imu_frequency_hz
        while not stop.is_set():
            started=time.monotonic()
            try:
                reading=self.imu.read()
                self.ingest_imu(reading)
                with self._lock:
                    if reading.connected: self.estimator.mark_data_source("PHYSICAL")
                    if not reading.connected: self.estimator.mark_sensor_status("imu",reading.status)
            except Exception as exc:
                log.exception("IMU worker failed: %s",exc)
                with self._lock: self.estimator.mark_sensor_status("imu","ERROR")
            stop.wait(max(0.0,interval-(time.monotonic()-started)))

    def run(self,stop:threading.Event|None=None):
        stop=stop or threading.Event()
        headers={"X-Device-Token":self.config.device_token} if self.config.device_token else {}
        client=self.http_client or httpx.Client(timeout=self.config.request_timeout_s)
        owns_client=self.http_client is None
        workers=[threading.Thread(target=self._gps_worker,args=(stop,),name="hector-gps",daemon=True),
                 threading.Thread(target=self._imu_worker,args=(stop,),name="hector-imu",daemon=True)]
        for worker in workers: worker.start()
        try:
            interval=1.0/self.config.publish_frequency_hz
            while not stop.is_set():
                started=time.monotonic()
                try:
                    packet=self.snapshot()
                    if packet.data_source!="UNSPECIFIED":
                        response=client.post(self.config.api_url.rstrip("/")+"/api/v1/telemetry",
                                             json=packet.model_dump(mode="json"),headers=headers)
                        response.raise_for_status()
                except Exception as exc:
                    log.warning("Telemetry publish failed; sensor collection continues: %s",exc)
                stop.wait(max(0.0,interval-(time.monotonic()-started)))
        finally:
            stop.set(); self.gps.close(); self.imu.close()
            for worker in workers: worker.join(timeout=2.0)
            if owns_client: client.close()


def main():
    logging.basicConfig(level=os.getenv("HECTOR_LOG_LEVEL","INFO"))
    from app.core.config import get_settings
    settings=get_settings()
    port=settings.gps_port
    if not port: raise SystemExit("HECTOR_GPS_PORT is required (for example COM3 or /dev/ttyUSB0)")
    config=GatewayConfig(robot_id=settings.robot_id,device_id=settings.device_id,
        api_url=settings.api_url,device_token=settings.device_token,
        imu_frequency_hz=settings.imu_frequency_hz,publish_frequency_hz=settings.publish_frequency_hz)
    gps=Neo6mAdapter(Neo6mConfig(port=port,baudrate=settings.gps_baud,
        nominal_frequency_hz=settings.gps_nominal_hz))
    imu=Mpu6050Adapter(Mpu6050Config(bus_number=settings.i2c_bus,
        address=int(settings.i2c_address,0)))
    gateway=SensorGateway(config,gps,imu)
    stop=threading.Event()
    try: gateway.run(stop)
    except KeyboardInterrupt: stop.set()


if __name__=="__main__": main()
