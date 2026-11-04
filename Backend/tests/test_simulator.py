from app.simulator.differential_drive import run_episode

def test_simulator_is_reproducible_and_marked_synthetic():
    one=run_episode(seed=12,noise_m=0)
    two=run_episode(seed=12,noise_m=0)
    assert one["source"]=="SYNTHETIC_SIMULATION"
    assert one["trace"]==two["trace"]
    assert one["sample_count"]>0 and one["rmse_lateral_m"]>=0
