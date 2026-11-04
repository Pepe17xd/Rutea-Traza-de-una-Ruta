from pathlib import Path
import json

FEATURES = ["cross_track_error_m", "heading_error_rad", "distance_to_goal_m", "speed_mps", "previous_omega_rps", "dt_s"]


def model_info(root: str, enabled: bool = False) -> dict:
    folder=Path(root); artifact=folder/"mlp-v1.joblib"; metrics=folder/"metrics.json"
    report=json.loads(metrics.read_text(encoding="utf-8")) if metrics.exists() else None
    return {"enabled_for_physical_control":False,"configured_enabled":enabled,"available":artifact.exists(),"version":"mlp-v1" if artifact.exists() else None,"features":FEATURES,"metrics":report,"fallback":"classical"}


def predict_correction(features: dict[str, float], root: str, limit_rps: float = 0.25) -> tuple[float, str]:
    """Trusted local joblib artifact only. Always returns bounded correction or zero fallback."""
    try:
        import joblib
        import numpy as np

        vector=np.asarray([[float(features[k]) for k in FEATURES]], dtype=float)
        if not np.isfinite(vector).all(): return 0.0,"classical_invalid_features"
        bounds=np.asarray([25.0,np.pi,1000.0,10.0,2.0,1.0])
        if np.any(np.abs(vector[0])>bounds) or vector[0,2]<0 or vector[0,3]<0 or not 0<vector[0,5]<=1:
            return 0.0,"classical_out_of_range"
        model=joblib.load(Path(root)/"mlp-v1.joblib")
        value=float(model.predict(vector)[0])
        if not np.isfinite(value): return 0.0,"classical_invalid_prediction"
        return max(-limit_rps,min(limit_rps,value)),"mlp-v1"
    except Exception:
        return 0.0,"classical_model_unavailable"
