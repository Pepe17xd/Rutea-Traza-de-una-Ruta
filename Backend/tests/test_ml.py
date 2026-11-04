from app.ml.dataset import make_episodes
from app.ml.train import train
from app.ml.inference import predict_correction, model_info

def test_episode_generation_reproducible():
    x,y,g=make_episodes(5,ticks=4,seed=9); x2,y2,g2=make_episodes(5,ticks=4,seed=9)
    assert (x==x2).all() and (y==y2).all() and (g==g2).all() and len(set(g))==5

def test_train_artifact_metrics_and_bounded_inference(tmp_path):
    report=train(str(tmp_path),seed=2,episodes=30)
    assert report['split_episode_counts']['test']>0
    assert sum(report['split_episode_counts'].values())==30
    assert report['synthetic_navigation_comparison']['hardware_evidence'] is False
    assert set(report['synthetic_navigation_comparison']['comparison'])=={'base','base_plus_ml'}
    assert model_info(str(tmp_path))['available']
    value,version=predict_correction(dict(cross_track_error_m=1,heading_error_rad=.2,distance_to_goal_m=8,speed_mps=.2,previous_omega_rps=.1,dt_s=.1),str(tmp_path),.15)
    assert abs(value)<=.15 and version=='mlp-v1'
    assert predict_correction({},str(tmp_path))[1].startswith('classical')

