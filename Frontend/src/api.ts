import type { Health, Latest, Mission, MissionResults, PumpExchange, Telemetry } from './types'

// The deployed SPA is always same-origin with API Gateway. A local absolute
// VITE_API_BASE may be used in dev, but must never be embedded in production.
const base = import.meta.env.PROD ? '/api/v1' : (import.meta.env.VITE_API_BASE || '/api/v1')
let csrfToken = ''
export const realtimeTransport: 'websocket' | 'polling' = import.meta.env.VITE_REALTIME_TRANSPORT === 'polling' ? 'polling' : 'websocket'
export const pollIntervalMs = Math.max(5000, Number(import.meta.env.VITE_POLL_INTERVAL_MS) || 15000)
export const missionPollIntervalMs = Math.max(5000, Number(import.meta.env.VITE_MISSION_POLL_INTERVAL_MS) || 15000)
export class ApiError extends Error { constructor(public status: number, message: string) { super(message) } }
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || 'GET').toUpperCase()
  const response = await fetch(`${base}${path}`, { ...init, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...(method !== 'GET' && method !== 'HEAD' ? { 'X-CSRF-Token': csrfToken } : {}), ...init?.headers } })
  if (response.status === 401 && path !== '/auth/login') csrfToken = ''
  if (!response.ok) { let message = `Error ${response.status}`; try { message = (await response.json()).detail || message } catch { /* keep status */ } throw new ApiError(response.status, message) }
  return response.json() as Promise<T>
}
export const api = {
  session: async () => { const value = await request<{ authenticated: boolean; csrf_token?: string }>('/auth/session'); csrfToken = value.csrf_token || ''; return value },
  login: async (password: string) => { const value = await request<{ authenticated: boolean; csrf_token: string }>('/auth/login', { method: 'POST', body: JSON.stringify({ password }) }); csrfToken = value.csrf_token; return value },
  logout: async () => { const value = await request<{ authenticated: boolean }>('/auth/logout', { method: 'POST' }); csrfToken = ''; return value },
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
  socketUrl: (robot: string) => { const url = new URL(`${base}/ws/robots/${encodeURIComponent(robot)}`, window.location.origin); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'; return url.toString() },
}
