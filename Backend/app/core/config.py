from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="HECTOR_", extra="ignore")
    storage: str = "sqlite"
    sqlite_path: str = "./data/hector.db"
    aws_region: str = Field(default="us-east-1", validation_alias="AWS_REGION")
    missions_table: str = Field(default="HectorMissions", validation_alias="MISSIONS_TABLE")
    telemetry_table: str = Field(default="HectorTelemetry", validation_alias="TELEMETRY_TABLE")
    allowed_origins: str = "http://localhost:5173"
    operator_password_hash: str = ""
    session_signing_key: str = ""
    session_ttl_s: int = Field(default=28800, ge=300, le=86400)
    session_cookie_secure: bool = True
    auth_login_attempts: int = Field(default=5, ge=3, le=20)
    auth_login_window_s: int = Field(default=900, ge=60, le=3600)
    device_token: str = ""
    require_auth: bool = True
    telemetry_max_age_s: float = 15.0
    telemetry_max_accuracy_m: float = 25.0
    telemetry_retention_days: int = Field(default=30, ge=1, le=365)
    goal_tolerance_default_m: float = 1.5
    stop_speed_mps: float = 0.08
    arrival_samples: int = 3
    model_path: str = "./artifacts"
    ml_enabled: bool = False
    api_url: str = "http://127.0.0.1:8000"
    robot_id: str = "CAR_01"
    device_id: str = "sensor-gateway-01"
    gps_port: str = ""
    gps_baud: int = 9600
    gps_nominal_hz: float = 1.0
    i2c_bus: int = 1
    i2c_address: str = "0x68"
    imu_frequency_hz: float = 20.0
    publish_frequency_hz: float = 5.0
    destination_ttl_s: int = Field(default=45, ge=5, le=600)

    @property
    def cors_origins(self) -> list[str]:
        return [v.strip() for v in self.allowed_origins.split(",") if v.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
