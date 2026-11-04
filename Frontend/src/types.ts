export type Point = { lat: number; lon: number }
export type MissionStatus = 'PENDING' | 'ACTIVE' | 'COMPLETED' | 'CANCELLED' | 'FAILED'
export type Telemetry = {
  robot_id: string; device_id: string; mission_id?: string | null; sequence: number; timestamp: string
  lat: number | null; lon: number | null; heading_deg: number | null; heading_rad: number | null; speed_mps: number | null
  gps_accuracy_m: number | null; gps_accuracy_status?: 'MEASURED' | 'ESTIMATED' | 'UNAVAILABLE' | 'SOURCE_UNSPECIFIED' | null
  gps_accuracy_source?: string | null; gps_accuracy_is_bound?: boolean | null
  gps_fix_valid?: boolean | null; gps_satellites?: number | null; gps_hdop?: number | null
  gps_course_deg?: number | null; imu_accel_mps2?: {x:number;y:number;z:number} | null; imu_gyro_rps?: {x:number;y:number;z:number} | null
  heading_relative_rad?: number | null; heading_source?: string | null; heading_quality?: string | null; heading_uncertainty_rad?: number | null
  gps_timestamp?: string | null; imu_timestamp?: string | null; sensor_timestamp?: string | null
  sensor_status?: Record<string,unknown> | null; data_source?: 'PHYSICAL' | 'RECORDED' | 'SYNTHETIC' | 'UNSPECIFIED'
  status: 'IDLE' | 'MOVING' | 'ARRIVED' | 'STOPPED' | 'ERROR'
  cross_track_error_m?: number | null; heading_error_rad?: number | null; distance_to_goal_m?: number | null
}
export type Mission = {
  mission_id: string; robot_id: string; created_at: string; updated_at: string; status: MissionStatus
  origin: Point; destination: Point; waypoints: Point[]; distance_m: number; goal_tolerance_m: number
  max_speed_mps: number; controller_version: string; model_version?: string | null
  command_sequence?: number | null; command_expires_at?: string | null; command_delivery_status?: string | null; command_acknowledged_at?: string | null
  stop_requested_at?: string | null; stop_confirmed: boolean; metrics?: Record<string, number> | null
}
export type Latest = { robot_id: string; device_status: 'CONECTADO' | 'NO_VERIFICADO' | 'SIN DISPOSITIVO' | 'RECORDED' | 'SIMULATION'; telemetry: Telemetry | null; age_s: number | null }
export type MissionResults = {
  mission_id: string; available: boolean; sample_count: number; rmse_lateral_m: number | null
  max_lateral_error_m: number | null; duration_s: number | null; arrival_rate: number | null
  comparison: Record<string, unknown> | null
}
export type Health = { status: string; storage: string; time: string; control_plane: string }
export type ApiEvent = { type: string; robot_id?: string; connected?: boolean; telemetry?: Telemetry; mission?: Mission; mission_id?: string; status?: MissionStatus; stop_confirmed?: boolean }
export type PumpExchange = { robot_id: string; command: 'ON' | 'OFF'; wire_payload: 'ON' | 'OFF'; transport: 'SIMULATED'; receipt: 'SIMULATED_RECEIPT'; authorization: 'NOT_AUTHORIZED_NO_PHYSICAL_INTERLOCKS'; confirmed_state: null; physical_output_enabled: false }
