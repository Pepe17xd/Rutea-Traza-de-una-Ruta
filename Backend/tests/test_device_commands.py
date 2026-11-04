from datetime import datetime, timedelta, timezone
from app import main
from app.core.config import get_settings
from app.db.sqlite import SQLiteRepository
import pytest


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"repo",SQLiteRepository(str(tmp_path/"device-commands.db")))
    from fastapi.testclient import TestClient
    with TestClient(main.app) as test_client:
        yield test_client


def packet(seq=1):
    return {"robot_id":"CAR_TEST","device_id":"gps-bridge-1","mission_id":None,"sequence":seq,
            "timestamp":datetime.now(timezone.utc).isoformat(),"lat":-12.0464,"lon":-77.0428,
            "heading_deg":90,"speed_mps":0,"gps_accuracy_m":0.8,"status":"IDLE"}


def create_pending(client, robot="CAR_TEST"):
    sample=packet(); sample["robot_id"]=robot
    assert client.post('/api/v1/telemetry',json=sample).status_code==200
    response=client.post('/api/v1/missions',json={"robot_id":robot,"destination":{"lat":-12.0462,"lon":-77.0425}})
    assert response.status_code==200, response.text
    return response.json()


def test_destination_delivery_exact_wire_format_ack_and_duplicate(client):
    mission=create_pending(client); mid=mission["mission_id"]
    delivery=client.get('/api/v1/robots/CAR_TEST/commands/next')
    assert delivery.status_code==200
    assert delivery.text=="G:-12.04620000,-77.04250000\n"
    assert delivery.headers["x-protocol-version"]=="1"
    assert delivery.headers["x-mission-id"]==mid
    sequence=int(delivery.headers["x-command-sequence"])
    assert sequence==mission["command_sequence"]
    assert int(delivery.headers["x-command-expires-at"])>int(datetime.now(timezone.utc).timestamp())
    ack={"sequence":sequence,"status":"RECEIVED","payload":delivery.text}
    accepted=client.post(f'/api/v1/robots/CAR_TEST/commands/{mid}/ack',json=ack)
    assert accepted.status_code==200 and accepted.json()["delivery_status"]=="RECEIVED"
    duplicate=client.post(f'/api/v1/robots/CAR_TEST/commands/{mid}/ack',json=ack)
    assert duplicate.status_code==200 and duplicate.json()["duplicate_ack"] is True
    assert client.get('/api/v1/robots/CAR_TEST/commands/next').status_code==204
    assert client.get(f'/api/v1/missions/{mid}').json()["status"]=="PENDING"


def test_destination_sequence_payload_and_expiry_rejections(client):
    mission=create_pending(client); mid=mission["mission_id"]
    delivery=client.get('/api/v1/robots/CAR_TEST/commands/next')
    bad={"sequence":int(delivery.headers["x-command-sequence"]),"status":"RECEIVED","payload":"G:1,2\n"}
    assert client.post(f'/api/v1/robots/CAR_TEST/commands/{mid}/ack',json=bad).status_code==422
    bad["payload"]=delivery.text; bad["sequence"]=999
    assert client.post(f'/api/v1/robots/CAR_TEST/commands/{mid}/ack',json=bad).status_code==409
    stored=main.repo.get_mission(mid)
    stored["command_expires_at"]=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    main.repo.update_mission(stored)
    assert client.get('/api/v1/robots/CAR_TEST/commands/next').status_code==204
    assert client.get(f'/api/v1/missions/{mid}').json()["status"]=="FAILED"
    assert main.repo.get_mission(mid)["command_delivery_status"]=="EXPIRED"


def test_device_auth_for_destination_poll_and_operator_pump_contract(client,monkeypatch):
    settings=get_settings()
    monkeypatch.setattr(settings,"device_token","device-key")
    monkeypatch.setattr(settings,"operator_token","operator-key")
    assert client.get('/api/v1/robots/CAR_TEST/commands/next').status_code==401
    assert client.get('/api/v1/robots/CAR_TEST/commands/next',headers={"X-Device-Token":"device-key"}).status_code==204
    assert client.post('/api/v1/robots/CAR_TEST/pump/commands',json={"command":"ON"}).status_code==401
    result=client.post('/api/v1/robots/CAR_TEST/pump/commands',json={"command":"ON"},headers={"Authorization":"Bearer operator-key"})
    assert result.status_code==200
    assert result.json()=={"robot_id":"CAR_TEST","command":"ON","wire_payload":"ON","transport":"SIMULATED","receipt":"SIMULATED_RECEIPT","authorization":"NOT_AUTHORIZED_NO_PHYSICAL_INTERLOCKS","confirmed_state":None,"physical_output_enabled":False}
    assert client.post('/api/v1/robots/CAR_TEST/pump/commands',json={"command":"on"},headers={"Authorization":"Bearer operator-key"}).status_code==422
