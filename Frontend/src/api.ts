import type { Health, Latest, Mission, MissionResults, PumpExchange, Telemetry } from './types'

// The deployed SPA is always same-origin with API Gateway. A local absolute
// VITE_API_BASE may be used in dev, but must never be embedded in production.
const base = import.meta.env.PROD ? '/api/v1' : (import.meta.env.VITE_API_BASE || '/api/v1')
const operatorToken = () => typeof sessionStorage === 'undefined' ? '' : sessionStorage.getItem('rutea_operator_token') || ''
export const realtimeTransport: 'websocket' | 'polling' = import.meta.env.VITE_REALTIME_TRANSPORT === 'polling' ? 'polling' : 'websocket'
export const pollIntervalMs = Math.max(5000, Number(import.meta.env.VITE_POLL_INTERVAL_MS) || 15000)
export const missionPollIntervalMs = Math.max(5000, Number(import.meta.env.VITE_MISSION_POLL_INTERVAL_MS) || 15000)
export class ApiError extends Error { constructor(public status: number, message: string) { super(message) } }
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = operatorToken()
  const response = await fetch(`${base}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init?.headers } })
  if (!response.ok) { let message = `Error ${response.status}`; try { message = (await response.json()).detail || message } catch { /* keep status */ } throw new ApiError(response.status, message) }
  return response.json() as Promise<T>
}
export const api = {
  setOperatorToken: (token: string) => { if (typeof sessionStorage !== 'undefined') { if (token) sessionStorage.setItem('rutea_operator_token', token); else sessionStorage.removeItem('rutea_operator_token') } },
  health: () => request<Health>('/health'),
  latest: (robot: string) => request<Latest>(`/robots/${encodeURIComponent(robot)}/latest`),
  missions: (robot: string, cursor?: string | null) => request<{ items: Mission[]; next_cursor: string | null }>(`/missions?robot_id=${encodeURIComponent(robot)}&limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  mission: (id: string) => request<Mission>(`/missions/${encodeURIComponent(id)}`),
  trace: (id: string, cursor?: string | null) => request<{ items: Telemetry[]; next_cursor: string | null }>(`/missions/${encodeURIComponent(id)}/trace?limit=500${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  results: (id: string) => request<MissionResults>(`/missions/${encodeURIComponent(id)}/results`),
  model: () => request<{ available: boolean; version: string | null; configured_enabled: boolean; enabled_for_physical_control: boolean; metrics: Record<string, unknown> | null; fallback: string }>('/model/status'),
  createMission: (robot_id: string, destination: { lat: number; lon: number }) => request<Mission>('/missions', { method: 'POST', body: JSON.stringify({ robot_id, destination, goal_tolerance_m: 1.5, max_speed_mps: 0.5 }) }),
  cancel: (id: string) => request<{ stop_requested: boolean; stop_confirmed: boolean; status: string }>(`/missions/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  pumpCommand: (robot: string, command: 'ON' | 'OFF') => request<PumpExchange>(`/robots/${encodeURIComponent(robot)}/pump/commands`, { method: 'POST', body: JSON.stringify({ command }) }),
  socketUrl: (robot: string) => { const url = new URL(`${base}/ws/robots/${encodeURIComponent(robot)}`, window.location.origin); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'; const token = operatorToken(); if (token) url.searchParams.set('token', token); return url.toString() },
}
