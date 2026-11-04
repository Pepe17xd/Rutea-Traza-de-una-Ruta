from pathlib import Path
import json
import numpy as np
from sklearn.metrics import mean_squared_error, mean_absolute_error
from sklearn.model_selection import GroupShuffleSplit
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import joblib
from app.ml.dataset import make_episodes
from app.navigation.controller import ControlConfig, classical_controller, ml_assisted_command
from app.navigation.trajectory import Point, tracking_errors


def compare_synthetic_scenarios(model, seed=7042, episodes=30):
    """Paired 2-D kinematic evaluation. This is synthetic evidence, never hardware evidence."""
    rng=np.random.default_rng(seed); rows={"base":[],"base_plus_ml":[]}
    cfg=ControlConfig(max_speed_mps=.45,max_angular_rps=1.2)
    for _ in range(episodes):
        goal=Point(float(rng.uniform(15,35)),float(rng.uniform(-3,3)))
        pos=Point(float(rng.uniform(-2,2)),float(rng.uniform(-4,4)))
        heading=float(rng.uniform(-np.pi,np.pi))
        outcomes={k:{"pos":pos,"heading":heading,"previous":0.0,"errors":[],"effort":0.0,"arrival":None,"settle_count":0} for k in rows}
        for tick in range(300):
            all_arrived=True
            for variant in rows:
                state=outcomes[variant]
                if state["arrival"] is not None: continue
                all_arrived=False
                e=tracking_errors(Point(0,0),goal,state["pos"],state["heading"])
                base=classical_controller(e["heading_error_rad"],e["cross_track_error_m"],e["distance_to_goal_m"],cfg)
                command=base
                if variant=="base_plus_ml":
                    features=np.asarray([[e["cross_track_error_m"],e["heading_error_rad"],e["distance_to_goal_m"],.2,state["previous"],.1]])
                    correction=float(np.clip(model.predict(features)[0],-.25,.25))
                    command=ml_assisted_command(base,correction,.25,cfg.max_angular_rps)
                state["errors"].append(e["cross_track_error_m"])
                state["effort"]+=command.angular_rps**2*.1
                stopped=e["distance_to_goal_m"]<=1.5 and command.linear_mps<=.08
                state["settle_count"]=state["settle_count"]+1 if stopped else 0
                if state["settle_count"]>=3:
                    state["arrival"]=(tick+1)*.1
                    continue
                h=state["heading"]
                p=state["pos"]
                state["pos"]=Point(p.x+command.linear_mps*np.cos(h)*.1,p.y+command.linear_mps*np.sin(h)*.1)
                # The same deterministic disturbance is applied to both variants per episode/tick.
                noise=float(np.random.default_rng(seed+tick+_ * 1000).normal(0,.006))
                state["heading"]=float((h+command.angular_rps*.1+noise+np.pi)%(2*np.pi)-np.pi)
                state["previous"]=command.angular_rps
            if all_arrived: break
        for variant in rows:
            s=outcomes[variant]; errors=np.asarray(s["errors"])
            arrived=s["arrival"] is not None
            rows[variant].append({"rmse_lateral_m":float(np.sqrt(np.mean(errors**2))),"max_lateral_error_m":float(np.max(np.abs(errors))),"arrival":arrived,"time_s":s["arrival"] if arrived else None,"effort":s["effort"]})
    summary={}
    for variant,values in rows.items():
        times=[x["time_s"] for x in values if x["time_s"] is not None]
        summary[variant]={"episodes":episodes,"rmse_lateral_m":float(np.mean([x["rmse_lateral_m"] for x in values])),"max_lateral_error_m":float(np.max([x["max_lateral_error_m"] for x in values])),"arrival_rate":sum(x["arrival"] for x in values)/episodes,"mean_time_s":float(np.mean(times)) if times else None,"mean_control_effort":float(np.mean([x["effort"] for x in values]))}
    return {"basis":"paired synthetic differential-drive scenarios, same initial conditions and disturbances","seed":seed,"comparison":summary,"hardware_evidence":False}


def train(output="./artifacts", seed=42, episodes=180):
    X,y,groups=make_episodes(episodes,seed=seed)
    split1=GroupShuffleSplit(n_splits=1,test_size=.15,random_state=seed)
    trainval,test=next(split1.split(X,y,groups))
    split2=GroupShuffleSplit(n_splits=1,test_size=.1764706,random_state=seed+1)
    train_rel,val_rel=next(split2.split(X[trainval],y[trainval],groups[trainval]))
    train_idx,val_idx=trainval[train_rel],trainval[val_rel]
    model=make_pipeline(StandardScaler(),MLPRegressor(hidden_layer_sizes=(32,16),activation="relu",solver="adam",max_iter=350,early_stopping=True,validation_fraction=.12,n_iter_no_change=20,random_state=seed))
    model.fit(X[train_idx],y[train_idx])
    pred=model.predict(X[test]); val=model.predict(X[val_idx])
    report={"version":"mlp-v1","seed":seed,"episode_count":episodes,"split_episode_counts":{"train":len(set(groups[train_idx])),"validation":len(set(groups[val_idx])),"test":len(set(groups[test]))},"target":"bounded expert angular correction (rad/s)","test_mae_rps":float(mean_absolute_error(y[test],pred)),"test_rmse_rps":float(mean_squared_error(y[test],pred)**.5),"validation_mae_rps":float(mean_absolute_error(y[val_idx],val)),"features":["cross_track_error_m","heading_error_rad","distance_to_goal_m","speed_mps","previous_omega_rps","dt_s"],"synthetic_navigation_comparison":None,"interpretation":"Synthetic offline dataset; predictive metrics do not establish physical or navigation improvement."}
    root=Path(output); root.mkdir(parents=True,exist_ok=True)
    joblib.dump(model,root/"mlp-v1.joblib")
    report["synthetic_navigation_comparison"]=compare_synthetic_scenarios(model,seed+7042)
    (root/"metrics.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report

if __name__=="__main__": print(json.dumps(train(),indent=2))
