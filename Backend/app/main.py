from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import math
import json
import secrets
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.db.sqlite import SQLiteRepository
from app.db.dynamodb import DynamoRepository
from app.models.schemas import (Mission, MissionCreate, MissionPage, MissionStatus, Telemetry,
                                TelemetryIn, TracePage, StopResult, DeviceStatus,
                                DestinationAck, PumpCommandRequest)
from app.navigation.coordinates import LocalFrame, compass_to_math
from app.navigation.trajectory import Point, distance, generate_waypoints, tracking_errors
from app.api.events import hub
from app.api.auth import COOKIE_NAME, origin_allowed, router as auth_router, require_device, require_operator, valid_session
from app.pump.contract import simulated_pump_exchange


FRONTEND_DIST = Path(__file__).resolve().parent / "frontend_dist"
settings = get_settings()
repo = DynamoRepository(settings.aws_region, settings.missions_table, settings.telemetry_table, telemetry_retention_days=settings.telemetry_retention_days) if settings.storage.lower() == "dynamodb" else SQLiteRepository(settings.sqlite_path)

@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.require_auth:
        raise RuntimeError("HECTOR_REQUIRE_AUTH no se puede desactivar")
    if not settings.device_token:
        raise RuntimeError("HECTOR_REQUIRE_AUTH está activo: configura HECTOR_DEVICE_TOKEN")
    if settings.require_auth and (not settings.operator_password_hash.startswith("$argon2id$") or len(settings.session_signing_key) < 32):
        raise RuntimeError("HECTOR_REQUIRE_AUTH está activo: configura HECTOR_OPERATOR_PASSWORD_HASH Argon2id y HECTOR_SESSION_SIGNING_KEY")
    yield

app = FastAPI(title="RUTEA API", version="1.0.0", description="Coordinación de misiones y recepción de telemetría normalizada. La API no controla motores.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["GET","POST"], allow_headers=["Content-Type","X-Device-Token","X-CSRF-Token"])
app.include_router(auth_router)

def now(): return datetime.now(timezone.utc)
def plain(model):
    data = model.model_dump(mode="json") if hasattr(model, "model_dump") else model
    return data
def latest_age(data):
    if not data: return None
    return max(0.0, (now()-datetime.fromisoformat(data["timestamp"])).total_seconds())

@app.get("/api/v1/health", tags=["system"])
def health():
    return {"status":"ok", "storage":settings.storage, "time":now(), "control_plane":"coordination_only"}

@app.post("/api/v1/missions", response_model=Mission, tags=["missions"], dependencies=[Depends(require_operator)])
async def create_mission(body: MissionCreate):
    latest = repo.latest_telemetry(body.robot_id)
    age = latest_age(latest)
    if latest is None or age is None or age > settings.telemetry_max_age_s:
        raise HTTPException(409, "No hay telemetría reciente válida; robot SIN DISPOSITIVO")
    if latest.get("data_source") in ("RECORDED", "SYNTHETIC"):
        raise HTTPException(409, "Datos registrados o sint?ticos no habilitan misiones f?sicas")
    if latest.get("gps_fix_valid") is False or latest.get("lat") is None or latest.get("lon") is None:
        raise HTTPException(409, "El GPS no tiene un fix v?lido")
    accuracy = latest.get("gps_accuracy_m")
    if latest.get("gps_accuracy_is_bound") is False:
        raise HTTPException(409, "La precisión horizontal es una estimación de la fuente, no un límite de error garantizado; no habilita una misión física")
    if accuracy is None:
        raise HTTPException(409, "La incertidumbre de posici?n no est? disponible; no se puede validar la tolerancia")
    if accuracy > settings.telemetry_max_accuracy_m:
        raise HTTPException(409, "La precisión reportada supera el límite configurado")
    if body.goal_tolerance_m < accuracy:
        raise HTTPException(409, "Goal tolerance is below reported GPS uncertainty")
    if repo.get_active_mission(body.robot_id):
        raise HTTPException(409, "Robot already has a pending or active mission")
    last_command_sequence = repo.latest_command_sequence(body.robot_id)
    origin = {"lat":latest["lat"], "lon":latest["lon"]}
    frame = LocalFrame(float(origin["lat"]), float(origin["lon"]))
    a, b = frame.to_local(float(origin["lat"]), float(origin["lon"])), frame.to_local(body.destination.lat, body.destination.lon)
    length = distance(a, b)
    if length < 0.05: raise HTTPException(422, "El destino coincide con el origen")
    waypoints = [dict(lat=lat, lon=lon) for lat, lon in (frame.to_gps(p) for p in generate_waypoints(a,b,1.0))]
    time = now()
    mission = Mission(mission_id=str(uuid4()), robot_id=body.robot_id, created_at=time, updated_at=time,
        status=MissionStatus.PENDING, origin=origin, destination=body.destination, waypoints=waypoints,
        distance_m=length, goal_tolerance_m=body.goal_tolerance_m or settings.goal_tolerance_default_m,
        max_speed_mps=body.max_speed_mps, controller_version="pd-1.0", model_version=None)
    data = plain(mission); data["arrival_count"] = 0
    data["command_sequence"] = max(int(time.timestamp() * 1000), last_command_sequence + 1)
    data["command_expires_at"] = (time + timedelta(seconds=settings.destination_ttl_s)).isoformat()
    data["command_delivery_status"] = "QUEUED"
    data["local_frame"] = {"origin_lat":origin["lat"],"origin_lon":origin["lon"],"crs":frame.crs,"axes":"x=este,y=norte"}
    try: repo.create_mission(data)
    except ValueError as ex: raise HTTPException(409,str(ex)) from ex
    await hub.publish(body.robot_id, {"type":"MISSION_ASSIGNED", "mission":plain(mission)})
    return Mission.model_validate(data)


@app.get("/api/v1/robots/{robot_id}/commands/next", tags=["device commands"], dependencies=[Depends(require_device)])
async def next_robot_command(robot_id: str):
    """Poll for a mission destination; HTTP 200 queues a delivery, not motion."""
    active = repo.get_active_mission(robot_id)
    pending = [active] if active and active.get("status") == "PENDING" else []
    for mission in pending:
        if not mission.get("command_sequence") or not mission.get("command_expires_at"):
            latest_sequence=repo.latest_command_sequence(robot_id)
            created=datetime.fromisoformat(mission["created_at"])
            mission["command_sequence"]=max(int(now().timestamp()*1000),latest_sequence+1)
            mission["command_expires_at"]=(created+timedelta(seconds=settings.destination_ttl_s)).isoformat()
            mission["command_delivery_status"]="QUEUED"
            repo.update_mission(mission)
        if mission.get("command_delivery_status") == "RECEIVED":
            continue
        expires = datetime.fromisoformat(mission["command_expires_at"])
        if now() >= expires:
            mission["status"] = "FAILED"
            mission["command_delivery_status"] = "EXPIRED"
            mission["metrics"] = {"failure_reason":"destination_delivery_expired"}
            mission["updated_at"] = now().isoformat()
            repo.update_mission(mission)
            await hub.publish(robot_id, {"type":"MISSION_STATUS", "mission_id":mission["mission_id"], "status":"FAILED"})
            continue
        destination = mission["destination"]
        line = f"G:{float(destination['lat']):.8f},{float(destination['lon']):.8f}\n"
        return PlainTextResponse(line, headers={
            "X-Protocol-Version": "1",
            "X-Mission-Id": mission["mission_id"],
            "X-Command-Sequence": str(mission["command_sequence"]),
            "X-Command-Expires-At": str(int(expires.timestamp())),
            "Cache-Control": "no-store",
        })
    return Response(status_code=204, headers={"Cache-Control":"no-store"})


@app.post("/api/v1/robots/{robot_id}/commands/{mission_id}/ack", tags=["device commands"], dependencies=[Depends(require_device)])
async def acknowledge_robot_command(robot_id: str, mission_id: str, body: DestinationAck):
    mission = repo.get_mission(mission_id)
    if not mission or mission.get("robot_id") != robot_id:
        raise HTTPException(404, "Comando de misiÃ³n no encontrado")
    if body.sequence != mission.get("command_sequence"):
        raise HTTPException(409, "Secuencia obsoleta o no correspondiente a la misiÃ³n")
    destination = mission["destination"]
    expected = f"G:{float(destination['lat']):.8f},{float(destination['lon']):.8f}\n"
    if body.payload != expected:
        raise HTTPException(422, "El destino confirmado no coincide con el payload asignado")
    if mission.get("command_delivery_status") == "RECEIVED":
        return {"accepted":True, "duplicate_ack":True, "mission_id":mission_id, "delivery_status":"RECEIVED"}
    if mission.get("status") != "PENDING":
        raise HTTPException(409, "La misiÃ³n ya no admite confirmaciÃ³n de entrega")
    if now() >= datetime.fromisoformat(mission["command_expires_at"]):
        mission["status"] = "FAILED"
        mission["command_delivery_status"] = "EXPIRED"
        mission["metrics"] = {"failure_reason":"destination_delivery_expired"}
        mission["updated_at"] = now().isoformat()
        repo.update_mission(mission)
        raise HTTPException(409, "La confirmaciÃ³n llegÃ³ despuÃ©s de caducar el comando")
    if body.status != "RECEIVED":
        mission["status"] = "FAILED"
        mission["command_delivery_status"] = body.status
        mission["metrics"] = {"failure_reason":body.status.lower()}
        mission["updated_at"] = now().isoformat()
        repo.update_mission(mission)
        await hub.publish(robot_id, {"type":"MISSION_STATUS", "mission_id":mission_id, "status":"FAILED"})
        return {"accepted":False, "mission_id":mission_id, "delivery_status":mission["command_delivery_status"]}
    mission["command_delivery_status"] = "RECEIVED"
    mission["command_acknowledged_at"] = now().isoformat()
    mission["updated_at"] = now().isoformat()
    repo.update_mission(mission)
    await hub.publish(robot_id, {"type":"COMMAND_RECEIVED", "mission_id":mission_id, "sequence":body.sequence})
    return {"accepted":True, "duplicate_ack":False, "mission_id":mission_id, "delivery_status":"RECEIVED", "mission_status":mission["status"]}


@app.post("/api/v1/robots/{robot_id}/pump/commands", tags=["pump safety"], dependencies=[Depends(require_operator)])
def pump_command_simulated(robot_id: str, body: PumpCommandRequest):
    """Contract preview only; this implementation has no Bluetooth or actuator side effect."""
    return simulated_pump_exchange(robot_id, body.command)

@app.get("/api/v1/missions", response_model=MissionPage, tags=["missions"], dependencies=[Depends(require_operator)])
def list_missions(robot_id: str | None = None, limit: int = Query(25, ge=1, le=100), cursor: str | None = None):
    validate_cursor(cursor)
    items, nxt = repo.list_missions(robot_id, limit, cursor)
    return {"items":[Mission.model_validate(x) for x in items], "next_cursor":nxt}

@app.get("/api/v1/missions/{mission_id}", response_model=Mission, tags=["missions"], dependencies=[Depends(require_operator)])
def get_mission(mission_id: str): return fetch_mission(mission_id)

def fetch_mission(mission_id):
    data = repo.get_mission(mission_id)
    if not data: raise HTTPException(404, "Misión no encontrada")
    allowed = Mission.model_fields.keys()
    return Mission.model_validate({k:v for k,v in data.items() if k in allowed})

@app.post("/api/v1/missions/{mission_id}/cancel", response_model=StopResult, tags=["missions"], dependencies=[Depends(require_operator)])
async def cancel_mission(mission_id: str):
    mission = repo.get_mission(mission_id)
    if not mission: raise HTTPException(404, "Misión no encontrada")
    if mission["status"] in ("COMPLETED", "CANCELLED", "FAILED"): raise HTTPException(409, f"No se puede cancelar una misión {mission['status']}")
    mission["status"] = "CANCELLED"; mission["updated_at"] = now().isoformat(); mission["stop_requested_at"] = now().isoformat(); mission["stop_confirmed"] = False
    mission["command_delivery_status"] = "REVOKED"
    repo.update_mission(mission)
    await hub.publish(mission["robot_id"], {"type":"STOP_REQUESTED", "mission_id":mission_id, "stop_confirmed":False})
    return StopResult(mission_id=mission_id, status=MissionStatus.CANCELLED)

@app.get("/api/v1/robots/{robot_id}/latest", tags=["robots"], dependencies=[Depends(require_operator)])
def get_latest(robot_id: str):
    data = repo.latest_telemetry(robot_id); age = latest_age(data)
    valid = data is not None and age is not None and age <= settings.telemetry_max_age_s
    source = data.get("data_source", "UNSPECIFIED") if valid else None
    device_status = ("RECORDED" if source == "RECORDED" else "SIMULATION" if source == "SYNTHETIC"
                     else "CONECTADO" if valid and source == "PHYSICAL"
                     else "NO_VERIFICADO" if valid else "SIN DISPOSITIVO")
    return {"robot_id":robot_id, "device_status":device_status, "telemetry":Telemetry.model_validate(data) if valid else None, "age_s":age}

@app.post("/api/v1/telemetry", tags=["telemetry"], dependencies=[Depends(require_device)])
async def ingest_telemetry(body: TelemetryIn):
    timestamp = body.timestamp
    age = (now()-timestamp).total_seconds()
    if age > settings.telemetry_max_age_s: raise HTTPException(422, "Telemetría antigua")
    if age < -5: raise HTTPException(422, "Timestamp futuro fuera de tolerancia")
    for label, stamp in (("sensor", body.sensor_timestamp), ("GPS", body.gps_timestamp), ("IMU", body.imu_timestamp)):
        if stamp is None: continue
        sensor_age = (now() - stamp).total_seconds()
        if sensor_age > settings.telemetry_max_age_s:
            raise HTTPException(422, f"Timestamp de {label} antiguo")
        if sensor_age < -5:
            raise HTTPException(422, f"Timestamp de {label} futuro fuera de tolerancia")
    if body.gps_accuracy_m is not None and body.gps_accuracy_m > settings.telemetry_max_accuracy_m: raise HTTPException(422, "Precisión GPS insuficiente")
    if body.data_source in ("RECORDED", "SYNTHETIC") and body.mission_id:
        raise HTTPException(422, "Recorded or synthetic samples cannot update a physical mission")
    if body.gps_fix_valid is False and (body.lat is not None or body.lon is not None):
        raise HTTPException(422, "Invalid GPS fix cannot be presented as measured coordinates")
    telemetry = Telemetry(**body.model_dump(), heading_rad=compass_to_math(body.heading_deg) if body.heading_deg is not None else None)
    previous = repo.latest_telemetry(body.robot_id)
    if previous and timestamp <= datetime.fromisoformat(previous["timestamp"]):
        raise HTTPException(422, "Timestamp debe avanzar estrictamente")
    if previous and body.sequence <= previous["sequence"]:
        raise HTTPException(409, "Secuencia duplicada o desordenada")
    mission = repo.get_mission(body.mission_id) if body.mission_id else None
    if body.mission_id and (not mission or mission["robot_id"] != body.robot_id): raise HTTPException(422, "mission_id desconocido o perteneciente a otro robot")
    if mission and body.lat is not None and body.lon is not None:
        frame_data = mission.get("local_frame", {"origin_lat":mission["origin"]["lat"], "origin_lon":mission["origin"]["lon"]})
        frame = LocalFrame(float(frame_data["origin_lat"]), float(frame_data["origin_lon"]))
        a, b, p = frame.to_local(float(mission["origin"]["lat"]), float(mission["origin"]["lon"])), frame.to_local(float(mission["destination"]["lat"]), float(mission["destination"]["lon"])), frame.to_local(body.lat, body.lon)
        errs = tracking_errors(a,b,p,telemetry.heading_rad)
        telemetry = telemetry.model_copy(update=errs)
    data = plain(telemetry); data["sample_key"] = f"{timestamp.isoformat()}#{body.sequence:020d}"
    try: accepted = repo.append_telemetry(data)
    except ValueError as ex: raise HTTPException(409, str(ex)) from ex
    if not accepted: raise HTTPException(409, "Secuencia duplicada o desordenada")
    if mission:
        if mission["status"] == "PENDING" and body.status == DeviceStatus.MOVING:
            mission["status"]="ACTIVE"
        if mission["status"] in ("PENDING", "ACTIVE") and body.status == DeviceStatus.ERROR:
            mission["status"]="FAILED"; mission["metrics"]={"failure_reason":"device_reported_error"}
        if mission["status"] == "ACTIVE" and body.status == DeviceStatus.STOPPED:
            mission["status"]="FAILED"; mission["metrics"]={"failure_reason":"device_reported_stopped"}
        if mission["status"] == "ACTIVE" and telemetry.distance_to_goal_m is not None:
            near = (body.gps_fix_valid is not False and body.gps_accuracy_m is not None
                    and body.gps_accuracy_is_bound is not False
                    and body.gps_accuracy_m <= mission["goal_tolerance_m"]
                    and telemetry.distance_to_goal_m <= mission["goal_tolerance_m"]
                    and body.speed_mps is not None and abs(body.speed_mps) <= settings.stop_speed_mps)
            mission["arrival_count"] = mission.get("arrival_count",0)+1 if near else 0
            if mission["arrival_count"] >= settings.arrival_samples:
                mission["status"]="COMPLETED"; mission["metrics"]={"final_distance_m":telemetry.distance_to_goal_m,"arrival_samples":mission["arrival_count"]}
        if mission["status"] == "CANCELLED" and body.status == DeviceStatus.STOPPED:
            mission["stop_confirmed"] = True
        mission["updated_at"] = now().isoformat(); repo.update_mission(mission)
        telemetry = telemetry.model_copy(update={"mission_id":body.mission_id})
    await hub.publish(body.robot_id, {"type":"TELEMETRY", "telemetry":plain(telemetry)})
    if mission: await hub.publish(body.robot_id, {"type":"MISSION_STATUS", "mission_id":mission["mission_id"], "status":mission["status"]})
    if mission and mission.get("stop_confirmed"): await hub.publish(body.robot_id, {"type":"STOP_CONFIRMED", "mission_id":mission["mission_id"], "stop_confirmed":True})
    return {"accepted":True, "telemetry":telemetry, "mission_status":mission["status"] if mission else None}

@app.get("/api/v1/missions/{mission_id}/trace", response_model=TracePage, tags=["telemetry"], dependencies=[Depends(require_operator)])
def get_trace(mission_id: str, limit: int=Query(100,ge=1,le=500), cursor: str|None=None):
    fetch_mission(mission_id)
    validate_cursor(cursor)
    items,nxt=repo.list_trace(mission_id,limit,cursor)
    return {"items":[Telemetry.model_validate(x) for x in items],"next_cursor":nxt}

@app.get("/api/v1/missions/{mission_id}/results", tags=["missions"], dependencies=[Depends(require_operator)])
def get_results(mission_id: str):
    m=fetch_mission(mission_id); trace=[]; cursor=None
    while True:
        batch,cursor=repo.list_trace(mission_id,500,cursor); trace.extend(batch)
        if cursor is None: break
    errors=[abs(t["cross_track_error_m"]) for t in trace if t.get("cross_track_error_m") is not None]
    rmse=math.sqrt(sum(x*x for x in errors)/len(errors)) if errors else None
    duration=(datetime.fromisoformat(trace[-1]["timestamp"])-datetime.fromisoformat(trace[0]["timestamp"])).total_seconds() if len(trace)>1 else None
    return {"mission_id":mission_id,"available":bool(trace),"sample_count":len(trace),"rmse_lateral_m":rmse,"max_lateral_error_m":max(errors) if errors else None,"duration_s":duration,"arrival_rate":1.0 if m.status==MissionStatus.COMPLETED else (0.0 if m.status in (MissionStatus.CANCELLED,MissionStatus.FAILED) else None),"comparison":None}

@app.get("/api/v1/model/status", tags=["ml"], dependencies=[Depends(require_operator)])
def model_status():
    from app.ml.inference import model_info
    return model_info(settings.model_path, settings.ml_enabled)

@app.get("/api/v1/model/evaluation", tags=["ml"], dependencies=[Depends(require_operator)])
def model_evaluation():
    from app.ml.inference import model_info
    return model_info(settings.model_path, settings.ml_enabled).get("metrics")

@app.websocket("/api/v1/ws/robots/{robot_id}")
async def robot_socket(ws: WebSocket, robot_id: str, token: str | None = None):
    if not origin_allowed(ws, ws.headers.get("origin")):
        await ws.close(code=4403); return
    session_id = ws.cookies.get(COOKIE_NAME)
    operator_ok = valid_session(session_id)
    device_ok = bool(settings.device_token) and secrets.compare_digest(token or "", settings.device_token)
    if not operator_ok and not device_ok:
        await ws.close(code=4401); return
    device_socket = device_ok
    await hub.connect(robot_id, ws)
    try:
        while True:
            try: raw=await ws.receive_json()
            except ValueError:
                await ws.send_json({"type":"ERROR","message":"El mensaje WebSocket debe ser JSON válido"})
                continue
            if device_socket:
                payload=raw.get("telemetry",raw) if isinstance(raw,dict) else raw
                if isinstance(payload,dict) and payload.get("type")=="TELEMETRY": payload=payload.get("telemetry",payload)
                try:
                    body=TelemetryIn.model_validate(payload)
                    if body.robot_id != robot_id: raise ValueError("robot_id no coincide con el canal WebSocket")
                    result=await ingest_telemetry(body)
                    await ws.send_json({"type":"TELEMETRY_ACK","sequence":body.sequence,"accepted":True,"mission_status":result.get("mission_status")})
                except Exception as ex:
                    message=ex.detail if isinstance(ex,HTTPException) else str(ex)
                    await ws.send_json({"type":"ERROR","message":message})
    except WebSocketDisconnect: hub.disconnect(robot_id, ws)

def validate_cursor(cursor):
    if cursor is None: return
    try:
        if settings.storage.lower() == "dynamodb":
            parsed=json.loads(cursor)
            if not isinstance(parsed,dict): raise ValueError()
        elif int(cursor)<0: raise ValueError()
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(400,"Cursor inválido")


@app.get("/", include_in_schema=False)
@app.get("/{requested_path:path}", include_in_schema=False)
def serve_frontend(requested_path: str = ""):
    """Serve the built RUTEA SPA from the same HTTPS HTTP API origin."""
    if requested_path == "api/v1" or requested_path.startswith("api/v1/"):
        raise HTTPException(404, "API endpoint not found")
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(404, "RUTEA frontend build is not packaged")
    root = FRONTEND_DIST.resolve()
    candidate = (root / requested_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(404, "Not found")
    if candidate.is_file():
        cache = "no-cache" if candidate.name == "index.html" else "public, max-age=31536000, immutable"
        return FileResponse(candidate, headers={"Cache-Control": cache})
    if Path(requested_path).suffix:
        raise HTTPException(404, "Static asset not found")
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
