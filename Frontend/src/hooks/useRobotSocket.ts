import { useEffect, useRef, useState } from 'react'
import { api, pollIntervalMs, realtimeTransport } from '../api'
import type { ApiEvent, Latest, Telemetry } from '../types'

export function useRobotSocket(robot: string, missionId: string | null, initialSequence = -1, onLatest?: (value: Latest) => void) {
  const [connected, setConnected] = useState(false)
  const [lastSeen, setLastSeen] = useState<number | null>(null)
  const [trace, setTrace] = useState<Telemetry[]>([])
  const [latestTelemetry, setLatestTelemetry] = useState<Telemetry | null>(null)
  const missionRef=useRef(missionId)
  const sequenceRef=useRef(initialSequence)
  useEffect(()=>{sequenceRef.current=Math.max(sequenceRef.current,initialSequence)},[initialSequence])
  useEffect(()=>{missionRef.current=missionId;setTrace([])},[missionId])
  useEffect(() => {
    let stopped = false; let socket: WebSocket | null = null; let retry = 800; let timer: number | undefined
    if (realtimeTransport === 'polling') {
      let backoff = pollIntervalMs
      const poll = async () => {
        if (stopped) return
        if (document.visibilityState !== 'visible') {
          timer = window.setTimeout(poll, pollIntervalMs)
          return
        }
        try {
          const latest = await api.latest(robot)
          if (stopped) return
          onLatest?.(latest)
          setConnected(true)
          const next = latest.telemetry
          if (next) {
            const packetTime = Date.parse(next.timestamp)
            const ageMs = Date.now() - packetTime
            if (Number.isFinite(packetTime) && ageMs <= 20_000 && ageMs >= -5_000 && next.sequence > sequenceRef.current) {
              sequenceRef.current = next.sequence
              setLatestTelemetry(next)
              setLastSeen(Date.now())
              if (missionRef.current && next.mission_id === missionRef.current) {
                setTrace(previous => [...previous, next].slice(-1200))
              }
            }
          } else {
            setLatestTelemetry(null)
          }
          backoff = pollIntervalMs
          timer = window.setTimeout(poll, pollIntervalMs)
        } catch {
          setConnected(false)
          timer = window.setTimeout(poll, backoff)
          backoff = Math.min(60000, backoff * 2)
        }
      }
      const onVisibility = () => {
        if (document.visibilityState === 'visible') {
          window.clearTimeout(timer)
          void poll()
        }
      }
      document.addEventListener('visibilitychange', onVisibility)
      void poll()
      return () => {
        stopped = true
        window.clearTimeout(timer)
        document.removeEventListener('visibilitychange', onVisibility)
        setConnected(false)
      }
    }
    const connect = () => {
      if (stopped) return
      socket = new WebSocket(api.socketUrl(robot))
      socket.onopen = () => { setConnected(true); retry = 800 }
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as ApiEvent
          if (event.type === 'TELEMETRY' && event.telemetry) {
            const next = event.telemetry
            const packetTime = Date.parse(next.timestamp)
            const ageMs = Date.now() - packetTime
            if (!Number.isFinite(packetTime) || ageMs > 20_000 || ageMs < -5_000 || next.sequence <= sequenceRef.current) return
            sequenceRef.current = next.sequence
            setLatestTelemetry(next)
            setLastSeen(Date.now())
            if (missionRef.current && next.mission_id === missionRef.current) {
              setTrace(previous => {
                const last = previous.at(-1)
                return last && next.sequence <= last.sequence ? previous : [...previous, next].slice(-1200)
              })
            }
          }
        } catch { /* invalid socket frame is ignored */ }
      }
      socket.onclose = () => { setConnected(false); if (!stopped) { timer = window.setTimeout(connect, retry); retry = Math.min(15000, retry * 1.8) } }
      socket.onerror = () => socket?.close()
    }
    connect()
    return () => { stopped = true; window.clearTimeout(timer); socket?.close(); setConnected(false) }
  }, [robot, onLatest])
  return { connected, lastSeen, trace, setTrace, latestTelemetry }
}
