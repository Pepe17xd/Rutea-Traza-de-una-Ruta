"""Reproducible synthetic episodes and expert-controller labels."""
import numpy as np

FEATURE_NAMES = ["cross_track_error_m", "heading_error_rad", "distance_to_goal_m", "speed_mps", "previous_omega_rps", "dt_s"]


def make_episodes(episode_count=120, ticks=40, seed=42):
    rng=np.random.default_rng(seed); rows=[]; labels=[]; groups=[]
    for episode in range(episode_count):
        cross=rng.uniform(-5,5); heading=rng.uniform(-np.pi,np.pi); distance=rng.uniform(5,60)
        speed=rng.uniform(0,0.5); prev=0.0
        dt=float(rng.uniform(.08,.2))
        for _ in range(ticks):
            noisy_cross=cross+rng.normal(0,.08); noisy_heading=heading+rng.normal(0,.025)
            feat=[noisy_cross,noisy_heading,distance,speed,prev,dt]
            base=np.clip(1.8*noisy_heading-.65*noisy_cross,-1.2,1.2)
            expert=np.clip(2.2*noisy_heading-.9*noisy_cross,-1.2,1.2)
            rows.append(feat); labels.append(np.clip(expert-base,-.25,.25)); groups.append(episode)
            # deterministic kinematic-like evolution with per-episode seeded disturbances
            prev=base; heading=np.clip(heading+(base*dt)+rng.normal(0,.02),-np.pi,np.pi)
            cross=np.clip(cross+speed*np.sin(heading)*dt+rng.normal(0,.015),-10,10)
            distance=max(0,distance-speed*dt)
            speed=float(rng.uniform(0,.5))
    return np.asarray(rows),np.asarray(labels),np.asarray(groups)
