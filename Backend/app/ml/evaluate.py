"""Evaluate the trained predictor on held-out complete synthetic episodes."""
import json
from pathlib import Path
import numpy as np
import joblib
from app.ml.dataset import make_episodes


def evaluate(artifact_dir="./artifacts", seed=42, episodes=180):
    X,y,groups=make_episodes(episodes,seed=seed)
    # Reconstruct the same episode-level 70/15/15 split used by train.py.
    from sklearn.model_selection import GroupShuffleSplit
    a,b=next(GroupShuffleSplit(n_splits=1,test_size=.15,random_state=seed).split(X,y,groups))
    test=b
    model=joblib.load(Path(artifact_dir)/"mlp-v1.joblib")
    predicted=np.clip(model.predict(X[test]),-.25,.25)
    return {"test_samples":len(test),"correction_rmse_rps":float(np.mean((predicted-y[test])**2)**.5),"correction_mae_rps":float(np.mean(np.abs(predicted-y[test]))),"episodes_are_grouped":True,"physical_control_enabled":False}

if __name__=="__main__": print(json.dumps(evaluate(),indent=2))
