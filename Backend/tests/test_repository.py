from app.db.sqlite import SQLiteRepository

def test_sqlite_sequence_and_device_idempotency(tmp_path):
    repo=SQLiteRepository(str(tmp_path/'r.db'))
    base={"robot_id":"R","device_id":"D","mission_id":None,"sequence":3,"timestamp":"2026-11-04T10:00:00+00:00","sample_key":"a"}
    assert repo.append_telemetry(base) and not repo.append_telemetry(base)
    try: repo.append_telemetry({**base,"sequence":4,"device_id":"other"})
    except ValueError: pass
    else: assert False,"Un robot no debe cambiar de dispositivo vinculado implícitamente"

def test_single_open_mission_is_enforced_atomically(tmp_path):
    repo=SQLiteRepository(str(tmp_path/'missions.db'))
    mission={"mission_id":"m1","robot_id":"R","created_at":"2026-11-04T10:00:00+00:00","status":"PENDING"}
    repo.create_mission(mission)
    try: repo.create_mission({**mission,"mission_id":"m2"})
    except ValueError: pass
    else: assert False,"Solo se permite una misión abierta por robot"
    repo.update_mission({**mission,"status":"CANCELLED"})
    repo.create_mission({**mission,"mission_id":"m2"})

def test_sqlite_active_mission_and_latest_command_sequence_are_direct_lookups(tmp_path):
    repo=SQLiteRepository(str(tmp_path/'robot-state.db'))
    first={"mission_id":"m1","robot_id":"R","created_at":"2026-11-04T10:00:00+00:00","status":"PENDING","command_sequence":100}
    repo.create_mission(first)
    assert repo.get_active_mission("R")["mission_id"] == "m1"
    assert repo.latest_command_sequence("R") == 100
    repo.update_mission({**first,"status":"CANCELLED"})
    assert repo.get_active_mission("R") is None
    second={**first,"mission_id":"m2","created_at":"2026-11-04T10:01:00+00:00","status":"PENDING","command_sequence":200}
    repo.create_mission(second)
    assert repo.latest_command_sequence("R") == 200

def test_sqlite_mission_offset_pagination_uses_numeric_cursor(tmp_path):
    repo=SQLiteRepository(str(tmp_path/'pages.db'))
    for index in range(5):
        repo.create_mission({
            "mission_id": f"m{index}", "robot_id": "R",
            "created_at": f"2026-11-04T10:0{index}:00+00:00",
            "status": "COMPLETED",
        })
    first, cursor=repo.list_missions("R",2,None)
    second, cursor2=repo.list_missions("R",2,cursor)
    third, cursor3=repo.list_missions("R",2,cursor2)
    assert [m["mission_id"] for m in first+second+third]==["m4","m3","m2","m1","m0"]
    assert cursor=="2" and cursor2=="4" and cursor3 is None

