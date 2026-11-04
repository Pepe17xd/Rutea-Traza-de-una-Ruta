from app.pump.contract import PumpInterlocks, may_authorize_on, simulated_pump_exchange


def test_bluetooth_contract_words_and_simulation_never_claims_actuation():
    for word in ("ON", "OFF"):
        result = simulated_pump_exchange("CAR_TEST", word)
        assert result["wire_payload"] == word
        assert result["transport"] == "SIMULATED"
        assert result["receipt"] == "SIMULATED_RECEIPT"
        assert result["confirmed_state"] is None
        assert result["physical_output_enabled"] is False
    try:
        simulated_pump_exchange("CAR_TEST", "on")
    except ValueError:
        pass
    else:
        raise AssertionError("Bluetooth word must be case-sensitive")


def test_pump_on_requires_all_local_confirmations():
    checks = {
        "gps_valid_and_fresh", "forward_motion_confirmed", "not_turning_in_place",
        "motion_not_stopped", "communication_healthy", "estop_clear", "physical_feedback_available",
    }
    assert not may_authorize_on(PumpInterlocks())
    assert may_authorize_on(PumpInterlocks(**{name: True for name in checks}))
    for missing in checks:
        values = {name: True for name in checks}
        values[missing] = False
        assert not may_authorize_on(PumpInterlocks(**values)), missing
