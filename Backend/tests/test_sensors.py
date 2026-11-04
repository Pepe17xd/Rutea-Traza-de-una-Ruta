from datetime import datetime, timezone, timedelta
from pathlib import Path
import math
import pytest

from app.sensors.nmea import NmeaParser, NmeaRecordingSource, NmeaError, Neo6mAdapter, Neo6mConfig, validate_checksum
from app.sensors.mpu6050 import Mpu6050Adapter, Mpu6050Config, ImuError
from app.sensors.estimator import StateEstimator, EstimatorConfig
from app.sensors.mpu6050 import ImuReading
from app.models.schemas import TelemetryIn
from app.sensors.contracts import estimate_to_telemetry
from app.sensors.gateway import GatewayConfig, SensorGateway

FIXTURES = Path(__file__).parent / 'fixtures'


def checksum(payload: str) -> str:
    value = 0
    for byte in payload.encode('ascii'):
        value ^= byte
    return f'${payload}*{value:02X}'


def test_nmea_rmc_gga_fix_metadata_and_no_metric_accuracy():
    parser = NmeaParser(source='RECORDED', monotonic=lambda: 10.0)
    lines = (FIXTURES / 'neo6m_valid.nmea').read_text(encoding='ascii').splitlines()
    rmc = parser.parse(lines[0]); gga = parser.parse(lines[1])
    assert rmc and rmc.fix_valid and rmc.source == 'RECORDED'
    assert rmc.latitude == pytest.approx(48.1173)
    assert rmc.longitude == pytest.approx(11.5166667)
    assert rmc.speed_mps == pytest.approx(22.4 * 0.5144444444)
    assert rmc.course_deg == pytest.approx(84.4)
    assert rmc.sensor_timestamp == datetime(1994, 3, 23, 12, 35, 19, tzinfo=timezone.utc)
    assert rmc.accuracy_m is None and 'UNAVAILABLE' in rmc.accuracy_status
    assert gga and gga.fix_quality == 1 and gga.satellites == 8 and gga.hdop == pytest.approx(.9)
    assert gga.speed_mps == pytest.approx(rmc.speed_mps) and gga.course_deg == rmc.course_deg


def test_nmea_rejects_bad_checksum_and_invalid_coordinates():
    parser = NmeaParser()
    valid = checksum('GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W')
    assert parser.parse(valid[:-2] + '00') is None
    assert parser.bad_checksums == 1
    invalid = checksum('GPRMC,123519,A,9960.000,N,01131.000,E,022.4,084.4,230394,003.1,W')
    assert parser.parse(invalid) is None
    assert parser.invalid_sentences == 1


def test_nmea_no_fix_lost_satellites_and_staleness():
    clock = [20.0]
    parser = NmeaParser(monotonic=lambda: clock[0])
    lines = (FIXTURES / 'neo6m_no_fix.nmea').read_text(encoding='ascii').splitlines()
    no_fix = parser.parse(lines[0]); void = parser.parse(lines[1])
    assert no_fix and not no_fix.fix_valid and no_fix.satellites == 0 and no_fix.hdop == pytest.approx(99.9)
    assert no_fix.latitude is None and no_fix.longitude is None
    assert void and not void.fix_valid and void.speed_mps is None and void.course_deg is None
    assert no_fix.is_stale(23.6, 3.5)


def test_recording_source_is_labeled_recorded(tmp_path):
    path = tmp_path / 'capture.nmea'
    path.write_text((FIXTURES / 'neo6m_valid.nmea').read_text(encoding='ascii'), encoding='ascii')
    with NmeaRecordingSource(path) as source:
        fix = source.read()
    assert fix is not None and fix.source == 'RECORDED'


class FakeSerial:
    def __init__(self, lines=()): self.lines=list(lines); self.closed=False
    def readline(self): return self.lines.pop(0) if self.lines else b''
    def close(self): self.closed=True


def test_uart_adapter_reconnects_after_open_failure():
    clock=[0.0]; good=FakeSerial()
    attempts=[0]
    def factory(*args, **kwargs):
        attempts[0]+=1
        if attempts[0]==1: raise OSError('port absent')
        return good
    adapter=Neo6mAdapter(Neo6mConfig('COM_TEST',reconnect_delay_s=0),serial_factory=factory,monotonic=lambda:clock[0])
    assert adapter.read() is None and adapter.status=='DISCONNECTED'
    assert adapter.read() is None and adapter.status=='CONNECTED_NO_FIX'
    assert adapter.reconnect_count==1
    adapter.close(); assert good.closed


def pack_words(words):
    out=[]
    for word in words:
        val=word & 0xffff; out.extend((val >> 8, val & 255))
    return out


class FakeBus:
    def __init__(self, words=None, identity=0x68): self.words=words or [0,0,16384,0,131,0,0]; self.identity=identity; self.closed=False
    def read_byte_data(self, address, register): return self.identity
    def write_byte_data(self, address, register, value): pass
    def read_i2c_block_data(self, address, register, length): return pack_words(self.words)
    def close(self): self.closed=True


def test_mpu_normal_read_and_gyro_bias_calibration():
    bus=FakeBus(); adapter=Mpu6050Adapter(bus=bus,sleeper=lambda _:None)
    sample=adapter.read()
    assert sample.valid and sample.connected
    assert sample.accel_mps2[2] == pytest.approx(9.80665)
    assert sample.gyro_rps[0] == pytest.approx(math.pi/180)
    calibration=adapter.calibrate_gyro(samples=4,interval_s=0)
    assert calibration.sample_count==4 and calibration.bias_rps[0]==pytest.approx(math.pi/180)
    assert adapter.read().gyro_rps[0] == pytest.approx(0,abs=1e-8)


def test_mpu_rejects_zero_and_out_of_range_and_recovers_disconnect():
    zero=Mpu6050Adapter(bus=FakeBus([0]*7))
    assert not zero.read().valid and zero.status=='INVALID_READING'
    saturated=Mpu6050Adapter(bus=FakeBus([0,0,0x7fff,0,0,0,0]))
    assert not saturated.read().valid
    clock=[0.0]; bus=FakeBus(); adapter=Mpu6050Adapter(bus_factory=lambda _:bus,monotonic=lambda:clock[0])
    assert adapter.read().valid
    bus.read_i2c_block_data=lambda *args: (_ for _ in ()).throw(OSError('removed'))
    failed=adapter.read(); assert not failed.valid and not failed.connected
    adapter._bus_factory=lambda _: FakeBus()
    clock[0]=3.0
    assert adapter.read().valid and adapter.connected


def test_estimator_uses_course_when_moving_and_integrates_relative_imu():
    mono=[1.0]
    parser=NmeaParser(source='PHYSICAL',monotonic=lambda:mono[0])
    rmc=parser.parse(checksum('GPRMC,123519,A,4807.038,N,01131.000,E,003.0,090.0,230394,003.1,W'))
    assert rmc
    estimator=StateEstimator(monotonic=lambda:mono[0])
    assert estimator.ingest_gps(rmc)
    estimate=estimator.estimate()
    assert estimate.heading_source=='gps_course' and estimate.gps_accuracy_m is None
    first=datetime(2026,1,1,tzinfo=timezone.utc)
    def imu(stamp, rate=0.2):
        return ImuReading((0.,0.,9.8),(0.,0.,rate),stamp,mono[0],True,True,'CONNECTED')
    assert estimator.ingest_imu(imu(first))
    mono[0]+=0.1
    assert estimator.ingest_imu(imu(first+timedelta(seconds=.1)))
    result=estimator.estimate()
    assert result.imu_gyro_rps[2]==pytest.approx(.2)
    assert result.heading_source=='gps_course+gyro'
    assert result.heading_quality=='COMPLEMENTARY_MODEL_ESTIMATE'
    normalized=estimate_to_telemetry(result,robot_id='CAR_01',device_id='gateway',sequence=1)
    assert normalized.gps_accuracy_m is None and normalized.gps_accuracy_status=='UNAVAILABLE'
    assert normalized.heading_deg is not None and normalized.heading_source=='gps_course+gyro'


def test_estimator_rejects_old_and_out_of_order_and_separates_sources():
    mono=[1.0]
    estimator=StateEstimator(EstimatorConfig(gps_max_age_s=1),monotonic=lambda:mono[0])
    old=ImuReading((0,0,9.8),(0,0,0),datetime.now(timezone.utc),-10,True,True,'CONNECTED')
    assert not estimator.ingest_imu(old) and estimator.estimate().sensor_status['imu']=='STALE'
    clock_fix=NmeaParser(source='RECORDED',monotonic=lambda:mono[0]).parse(checksum('GPRMC,123519,A,4807.038,N,01131.000,E,003.0,090.0,230394,003.1,W'))
    assert clock_fix
    physical=ImuReading((0,0,9.8),(0,0,0),datetime.now(timezone.utc),mono[0],True,True,'CONNECTED')
    assert estimator.ingest_imu(physical)
    assert not estimator.ingest_gps(clock_fix)
    mono[0]=4.0
    assert estimator.estimate().sensor_status['imu']=='STALE'


def test_normalized_telemetry_allows_no_fix_but_rejects_partial_or_nonfinite_data():
    stamp=datetime.now(timezone.utc)
    value=TelemetryIn(robot_id='CAR_01',device_id='gateway',sequence=1,timestamp=stamp,
                      gps_fix_valid=False,gps_accuracy_m=None,data_source='PHYSICAL',
                      imu_accel_mps2={'x':0,'y':0,'z':9.8},imu_gyro_rps={'x':0,'y':0,'z':0},
                      imu_timestamp=stamp,sensor_timestamp=stamp)
    assert value.lat is None and value.gps_fix_valid is False and value.gps_accuracy_m is None
    with pytest.raises(ValueError):
        TelemetryIn(robot_id='CAR_01',device_id='gateway',sequence=2,timestamp=stamp,lat=1.0)
    with pytest.raises(ValueError):
        TelemetryIn(robot_id='CAR_01',device_id='gateway',sequence=3,timestamp=stamp,
                    imu_gyro_rps={'x':float('nan'),'y':0,'z':0})


def test_imu_can_update_faster_than_gps_and_rejects_out_of_order():
    mono=[1.0]; estimator=StateEstimator(monotonic=lambda:mono[0])
    gps=NmeaParser(source='PHYSICAL',monotonic=lambda:mono[0]).parse(
        checksum('GPRMC,123519,A,4807.038,N,01131.000,E,003.0,090.0,230394,003.1,W'))
    assert gps and estimator.ingest_gps(gps)
    base=datetime(2026,1,1,tzinfo=timezone.utc)
    def sample(dt):
        return ImuReading((0,0,9.8),(0,0,.1),base+timedelta(seconds=dt),mono[0],True,True,'CONNECTED')
    assert estimator.ingest_imu(sample(0))
    mono[0]+=.1; assert estimator.ingest_imu(sample(.1))
    mono[0]+=.1; assert estimator.ingest_imu(sample(.2))
    assert estimator.estimate().gps_fix_valid
    assert not estimator.ingest_imu(sample(.15))
    assert estimator.estimate().sensor_status['imu']=='OUT_OF_ORDER'


def test_gps_fix_becomes_stale_then_recovers_with_new_measurement():
    clock=[0.0]
    first=checksum('GPRMC,123519,A,4807.038,N,01131.000,E,003.0,090.0,230394,003.1,W').encode()+b'\r\n'
    second=checksum('GPRMC,123520,A,4807.039,N,01131.001,E,003.1,091.0,230394,003.1,W').encode()+b'\r\n'
    serial=FakeSerial([first])
    adapter=Neo6mAdapter(Neo6mConfig('UART',max_age_s=2),serial_factory=lambda *a,**k:serial,monotonic=lambda:clock[0])
    fresh=adapter.read(); assert fresh and fresh.fix_valid and not fresh.stale
    clock[0]=3.0
    assert adapter.read() and adapter.status=='STALE'
    serial.lines.append(second); clock[0]=3.1
    recovered=adapter.read(); assert recovered and not recovered.stale and adapter.status=='FIX_VALID'
    assert recovered.latitude != fresh.latitude


def test_gyro_calibration_refuses_motion_without_applying_bias():
    class MovingBus(FakeBus):
        def __init__(self): super().__init__(); self.reads=0
        def read_i2c_block_data(self,address,register,length):
            self.reads+=1
            gyro_x=100 if self.reads%2 else 300
            return pack_words([0,0,16384,0,gyro_x,0,0])
    adapter=Mpu6050Adapter(Mpu6050Config(calibration_max_std_rps=.001),bus=MovingBus(),sleeper=lambda _:None)
    with pytest.raises(ImuError,match='moved'):
        adapter.calibrate_gyro(samples=5,interval_s=0)
    assert adapter.gyro_bias_rps==(0.0,0.0,0.0)


def test_gateway_combines_same_second_rmc_gga_metadata_into_api_telemetry():
    parser=NmeaParser(source='PHYSICAL',monotonic=lambda:1.0)
    rmc=parser.parse(checksum('GPRMC,123519,A,4807.038,N,01131.000,E,003.0,090.0,230394,003.1,W'))
    gga=parser.parse(checksum('GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,'))
    assert rmc and gga
    gateway=SensorGateway(GatewayConfig('CAR_01','gateway'),Neo6mAdapter(Neo6mConfig('UART'),serial_factory=lambda *a,**k:FakeSerial()),Mpu6050Adapter(bus=FakeBus()),estimator=StateEstimator(monotonic=lambda:1.0))
    assert gateway.ingest_gps(rmc)
    assert gateway.ingest_gps(gga)
    packet=gateway.snapshot()
    assert packet.gps_fix_valid and packet.gps_satellites==8 and packet.gps_hdop==pytest.approx(.9)
    assert packet.data_source=='PHYSICAL' and packet.gps_accuracy_m is None


def test_gateway_publishes_normalized_http_payload_and_device_token():
    stop=__import__('threading').Event()
    class Response:
        def raise_for_status(self): pass
    class Client:
        request=None
        def post(self,url,**kwargs):
            self.request=(url,kwargs); stop.set(); return Response()
    client=Client()
    estimator=StateEstimator(monotonic=lambda:1.0)
    gateway=SensorGateway(GatewayConfig('CAR_01','gateway',api_url='http://backend',device_token='device-secret'),
        Neo6mAdapter(Neo6mConfig('UART'),serial_factory=lambda *a,**k:FakeSerial()),
        Mpu6050Adapter(bus=FakeBus()),estimator=estimator,http_client=client)
    gateway.ingest_imu(ImuReading((0,0,9.8),(0,0,0),datetime.now(timezone.utc),1.0,True,True,'CONNECTED'))
    gateway.run(stop)
    url,request=client.request
    assert url=='http://backend/api/v1/telemetry'
    assert request['headers']=={'X-Device-Token':'device-secret'}
    assert request['json']['robot_id']=='CAR_01' and request['json']['data_source']=='PHYSICAL'
    assert request['json']['sequence']==1



def test_gateway_does_not_publish_when_both_sensors_are_disconnected():
    threading=__import__('threading')
    stop=threading.Event()
    class Client:
        requests=0
        def post(self,*args,**kwargs): self.requests+=1; return type('Response',(),{'raise_for_status':lambda self:None})()
    client=Client()
    gps=Neo6mAdapter(Neo6mConfig('UART',reconnect_delay_s=5),serial_factory=lambda *a,**k:(_ for _ in ()).throw(OSError('no GPS')))
    imu=Mpu6050Adapter(bus_factory=lambda _:(_ for _ in ()).throw(OSError('no IMU')))
    gateway=SensorGateway(GatewayConfig('CAR_01','gateway'),gps,imu,http_client=client)
    timer=threading.Timer(.08,stop.set); timer.start()
    gateway.run(stop); timer.cancel()
    assert client.requests==0 and gps.status=='DISCONNECTED' and imu.status=='DISCONNECTED'
