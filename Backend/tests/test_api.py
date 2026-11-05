from datetime import datetime, timezone
from fastapi.testclient import TestClient
import pytest
from app.db.sqlite import SQLiteRepository
from app import main
from app.core.config import get_settings

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main,"repo",SQLiteRepository(str(tmp_path/"test.db")))
    monkeypatch.setattr(get_settings(),"sqlite_path",str(tmp_path/"test.db"))
    with TestClient(main.app) as c:
        login=c.post('/api/v1/auth/login',json={"password":"rutea-test-password"})
        assert login.status_code==200,login.text
        c.headers.update({"X-CSRF-Token":login.json()["csrf_token"]})
        yield c

@pytest.fixture
def device_client(client):
    with TestClient(main.app, headers={"X-Device-Token": get_settings().device_token}) as device:
        yield device

def packet(seq=1,lat=-12.0464,lon=-77.0428,mission=None,status="IDLE",ts=None,device="gps-bridge-1"):
    return {"robot_id":"CAR_TEST","device_id":device,"mission_id":mission,"sequence":seq,"timestamp":(ts or datetime.now(timezone.utc)).isoformat(),"lat":lat,"lon":lon,"heading_deg":90,"speed_mps":0,"gps_accuracy_m":0.8,"status":status}

def test_health_and_no_device_mission_rejection(client):
    assert client.get('/api/v1/health').json()['status']=='ok'
    r=client.post('/api/v1/missions',json={"robot_id":"CAR_TEST","destination":{"lat":-12.04,"lon":-77.04}})
    assert r.status_code==409 and 'telemetría' in r.json()['detail']
    assert client.get('/api/v1/robots/CAR_TEST/latest').json()['device_status']=='SIN DISPOSITIVO'

def test_telemetry_mission_trace_cancel_and_history(client, device_client):
    assert device_client.post('/api/v1/telemetry',json=packet()).status_code==200
    create=client.post('/api/v1/missions',json={"robot_id":"CAR_TEST","destination":{"lat":-12.0464,"lon":-77.0425}})
    assert create.status_code==200,create.text
    mission=create.json(); mid=mission['mission_id']
    assert mission['status']=='PENDING' and len(mission['waypoints'])>=2
    assert device_client.post('/api/v1/telemetry',json=packet(2,lon=-77.0427,mission=mid,status='MOVING')).status_code==200
    assert client.get(f'/api/v1/missions/{mid}').json()['status']=='ACTIVE'
    trace=client.get(f'/api/v1/missions/{mid}/trace').json()
    assert len(trace['items'])==1 and trace['items'][0]['cross_track_error_m'] is not None
    assert client.get(f'/api/v1/missions/{mid}/results').json()['available'] is True
    result=client.post(f'/api/v1/missions/{mid}/cancel')
    assert result.status_code==200 and not result.json()['stop_confirmed']
    assert device_client.post('/api/v1/telemetry',json=packet(3,lon=-77.0427,mission=mid,status='STOPPED')).status_code==200
    assert client.get(f'/api/v1/missions/{mid}').json()['stop_confirmed'] is True
    assert client.post(f'/api/v1/missions/{mid}/cancel').status_code==409
    assert client.get('/api/v1/missions?robot_id=CAR_TEST').json()['items'][0]['mission_id']==mid

def test_latest_missions_and_model_status_contracts(client):
    assert client.get('/api/v1/missions?robot_id=CAR_TEST').json()=={"items":[],"next_cursor":None}
    result=client.get('/api/v1/model/status')
    assert result.status_code==200
    assert {"available","version","configured_enabled","enabled_for_physical_control","fallback"} <= result.json().keys()

def test_unspecified_telemetry_is_not_reported_as_physical_device(client, device_client):
    assert device_client.post('/api/v1/telemetry',json=packet()).status_code==200
    latest=client.get('/api/v1/robots/CAR_TEST/latest').json()
    assert latest['device_status']=='NO_VERIFICADO'
    assert latest['telemetry']['data_source']=='UNSPECIFIED'

def test_cors_and_configurable_http_auth(client,monkeypatch):
    settings=get_settings()
    monkeypatch.setattr(settings,"device_token","device-test")
    client.cookies.clear(); client.headers.pop("X-CSRF-Token",None)
    assert client.get('/api/v1/missions').status_code==401
    assert client.post('/api/v1/telemetry',json=packet()).status_code==401
    accepted=client.post('/api/v1/telemetry',json=packet(),headers={"X-Device-Token":"device-test"})
    assert accepted.status_code==200
    cors=client.options('/api/v1/health',headers={
        "Origin":"http://localhost:5173", "Access-Control-Request-Method":"GET",
        "Access-Control-Request-Headers":"x-csrf-token",
    })
    assert cors.status_code==200
    assert cors.headers['access-control-allow-origin']=='http://localhost:5173'

def test_telemetry_validation_duplicate_old_and_wrong_device(client, device_client):
    assert device_client.post('/api/v1/telemetry',json=packet()).status_code==200
    assert device_client.post('/api/v1/telemetry',json=packet()).status_code==409
    assert device_client.post('/api/v1/telemetry',json=packet(2,device='other')).status_code==409
    old=datetime(2020,1,1,tzinfo=timezone.utc)
    assert device_client.post('/api/v1/telemetry',json=packet(3,ts=old)).status_code==422
    recovered=device_client.post('/api/v1/telemetry',json=packet(2))
    assert recovered.status_code==200
    assert client.get('/api/v1/robots/CAR_TEST/latest').json()['telemetry']['sequence']==2

def test_ubx_hacc_estimate_is_not_accepted_as_mission_uncertainty(client, device_client):
    telemetry=packet()
    telemetry.update(gps_accuracy_status='ESTIMATED',gps_accuracy_source='UBX_NAV_POSLLH.hAcc',gps_accuracy_is_bound=False)
    assert device_client.post('/api/v1/telemetry',json=telemetry).status_code==200
    response=client.post('/api/v1/missions',json={"robot_id":"CAR_TEST","destination":{"lat":-12.0464,"lon":-77.0425}})
    assert response.status_code==409
    assert "garantizado" in response.json()["detail"]

def test_websocket_receives_telemetry_event(client):
    with client.websocket_connect('/api/v1/ws/robots/CAR_TEST') as ws:
        assert ws.receive_json()['type']=='CONNECTION'
        response=client.post('/api/v1/telemetry',json=packet(),headers={"X-Device-Token":get_settings().device_token})
        assert response.status_code==200
        event=ws.receive_json()
        assert event['type']=='TELEMETRY' and event['telemetry']['sequence']==1

def test_websocket_device_ingestion(client):
    with client.websocket_connect('/api/v1/ws/robots/CAR_TEST?token=device-test-token-0123456789') as ws:
        assert ws.receive_json()['type']=='CONNECTION'
        ws.send_json(packet())
        event=ws.receive_json()
        assert event['type']=='TELEMETRY' and event['telemetry']['sequence']==1
        ack=ws.receive_json()
        assert ack['type']=='TELEMETRY_ACK' and ack['accepted'] is True

def test_websocket_duplicate_rejection_disconnect_cleanup_and_reconnect(client):
    with client.websocket_connect('/api/v1/ws/robots/CAR_TEST?token=device-test-token-0123456789') as ws:
        assert ws.receive_json()['type']=='CONNECTION'
        ws.send_json(packet(1))
        assert ws.receive_json()['type']=='TELEMETRY'
        assert ws.receive_json()['type']=='TELEMETRY_ACK'
        ws.send_json(packet(1))
        error=ws.receive_json()
        assert error['type']=='ERROR'
        assert len(main.hub.clients['CAR_TEST'])==1
    assert not main.hub.clients['CAR_TEST']
    with client.websocket_connect('/api/v1/ws/robots/CAR_TEST?token=device-test-token-0123456789') as reconnected:
        assert reconnected.receive_json()['type']=='CONNECTION'
        reconnected.send_json(packet(2))
        assert reconnected.receive_json()['type']=='TELEMETRY'
        assert reconnected.receive_json()['type']=='TELEMETRY_ACK'
    assert not main.hub.clients['CAR_TEST']

