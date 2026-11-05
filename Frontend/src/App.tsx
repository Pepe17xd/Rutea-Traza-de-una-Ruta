import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Bot, Check, ChevronRight, CircleDot, Clock3, Compass, Crosshair, Droplet, Gauge, History, LogOut, Eye, EyeOff, MapPin, Route, Send, ShieldAlert, Square, Waypoints, WifiOff } from 'lucide-react'
import { ApiError, api, missionPollIntervalMs, realtimeTransport } from './api'
import { useRobotSocket } from './hooks/useRobotSocket'
import MapView from './components/MapView'
import type { Latest, Mission, MissionResults, Point, PumpExchange, Telemetry } from './types'

const robotId = import.meta.env.VITE_ROBOT_ID || 'CAR_01'
type View = 'panel' | 'history' | 'ml'
const num = (v: number | null | undefined, d = 2) => v == null || !Number.isFinite(v) ? '—' : v.toFixed(d)
const ageText = (seconds: number | null) => seconds == null ? 'Sin datos' : seconds < 60 ? `hace ${Math.round(seconds)} s` : `hace ${Math.floor(seconds / 60)} min`
const statusText = (value: unknown) => value == null || value === '' ? 'No disponible' : typeof value === 'string' ? value : String(value)
const dateText = (value: string) => new Date(value).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })
const fmtMission = (status?: string) => ({ PENDING: 'Asignada', ACTIVE: 'Reportando', COMPLETED: 'Completada', CANCELLED: 'Cancelada', FAILED: 'Fallida' }[status || ''] || 'Sin misión')
const haversine = (a: Point, b: Point) => { const r = Math.PI / 180; const dLat = (b.lat-a.lat)*r; const dLon=(b.lon-a.lon)*r; const h=Math.sin(dLat/2)**2+Math.cos(a.lat*r)*Math.cos(b.lat*r)*Math.sin(dLon/2)**2; return 6371000*2*Math.atan2(Math.sqrt(h),Math.sqrt(1-h)) }

async function readTrace(id:string) { const all:Telemetry[]=[]; let cursor:string|null=null; do { const page=await api.trace(id,cursor); all.push(...page.items); cursor=page.next_cursor } while(cursor); return all }

function Metric({ label, value, unit, icon: Icon, sub }: { label: string; value: string; unit?: string; icon: typeof Gauge; sub?: string }) {
  return <div className="metric-card"><div className="metric-top"><span>{label}</span><Icon size={16}/></div><div className="metric-value">{value}<small>{unit}</small></div>{sub && <div className="metric-sub">{sub}</div>}</div>
}

export default function App() {
  const [view, setView] = useState<View>('panel')
  const [latest, setLatest] = useState<Latest | null>(null)
  const [latInput, setLatInput] = useState(''); const [lonInput, setLonInput] = useState('')
  const [mission, setMission] = useState<Mission | null>(null)
  const [missions, setMissions] = useState<Mission[]>([])
  const [selected, setSelected] = useState<Mission | null>(null)
  const [trace, setTrace] = useState<Telemetry[]>([])
  const [model, setModel] = useState<{ available: boolean; version: string | null; configured_enabled: boolean; enabled_for_physical_control: boolean; metrics: Record<string, unknown> | null; fallback: string } | null>(null)
  const [results, setResults] = useState<MissionResults | null>(null)
  const [pumpExchange, setPumpExchange] = useState<PumpExchange | null>(null)
  const [pumpBusy, setPumpBusy] = useState(false)
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [notice, setNotice] = useState('')
  const [authenticated, setAuthenticated] = useState(false)
  const [authLoading, setAuthLoading] = useState(true)
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [authBusy, setAuthBusy] = useState(false)
  const [authError, setAuthError] = useState('')
  const { connected, lastSeen, trace: liveTrace, setTrace: setLiveTrace, latestTelemetry } = useRobotSocket(robotId, mission?.mission_id ?? null, latest?.telemetry?.sequence ?? -1, setLatest, authenticated)
  const current = latestTelemetry && latestTelemetry.sequence > (latest?.telemetry?.sequence ?? -1) ? latestTelemetry : latest?.telemetry ?? latestTelemetry
  const sampleAgeS = current ? (Date.now()-Date.parse(current.timestamp))/1000 : Infinity
  const sampleFresh = Number.isFinite(sampleAgeS) && sampleAgeS >= -5 && sampleAgeS <= 15
  const position = current && sampleFresh && ['PHYSICAL','RECORDED','SYNTHETIC'].includes(current.data_source || '') && current.gps_fix_valid !== false && current.lat != null && current.lon != null ? current : null
  const inputDestination = useMemo<Point | null>(() => {
    if (!latInput.trim() || !lonInput.trim()) return null
    const lat=Number(latInput), lon=Number(lonInput)
    return Number.isFinite(lat)&&Number.isFinite(lon)&&Math.abs(lat)<=90&&Math.abs(lon)<=180?{lat,lon}:null
  },[latInput,lonInput])
  const selectedDestination = inputDestination
  const hasMission = Boolean(mission && ['PENDING','ACTIVE'].includes(mission.status))
  const mapTrace = useMemo(() => { const merged=new Map<number,Telemetry>(); for(const item of [...trace,...liveTrace]) merged.set(item.sequence,item); return [...merged.values()].sort((a,b)=>a.sequence-b.sequence) }, [liveTrace, trace])
  const simComparison = model?.metrics?.synthetic_navigation_comparison as { comparison?: Record<string, Record<string, number | null>>; seed?: number } | undefined
  const onPick = useCallback((point: Point) => { setLatInput(point.lat.toFixed(7)); setLonInput(point.lon.toFixed(7)) }, [])
  const ignorePick = useCallback(() => {}, [])

  const loadLatest = useCallback(async () => { if (!authenticated) return; try { const value = await api.latest(robotId); setLatest(value); setError('') } catch (e) { if (e instanceof ApiError && e.status === 401) { setAuthenticated(false); setMission(null); setMissions([]); setError(''); return }; setError(e instanceof Error ? e.message : 'No se pudo consultar el robot') } }, [authenticated])
  const loadMissions = useCallback(async () => { if (!authenticated) return; try { const all:Mission[]=[]; let cursor:string|null=null; do { const page=await api.missions(robotId,cursor); all.push(...page.items); cursor=page.next_cursor } while(cursor); setMissions(all) } catch { /* displayed in dashboard error state */ } }, [authenticated])
  useEffect(() => {
    let active = true
    void api.session().then(value => { if (active) setAuthenticated(value.authenticated) }).catch(() => { if (active) { setAuthenticated(false); setAuthError('No se pudo verificar la sesión con el servidor.') } }).finally(() => { if (active) setAuthLoading(false) })
    return () => { active = false }
  }, [])
  useEffect(() => {
    if (!authenticated) return
    void loadLatest()
    void loadMissions()
    if (realtimeTransport !== 'websocket') return
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') void loadLatest()
    }, 15000)
    return () => window.clearInterval(interval)
  }, [authenticated, loadLatest, loadMissions])
  useEffect(() => { if (!mission) { setLiveTrace([]); return }; let cancelled=false; void readTrace(mission.mission_id).then(items=>{if(!cancelled)setTrace(items)}).catch(() => {if(!cancelled)setTrace([])}); return ()=>{cancelled=true} }, [mission?.mission_id, setLiveTrace])
  useEffect(() => {
    const needsRefresh=Boolean(mission&&(mission.status==='PENDING'||mission.status==='ACTIVE'||(mission.status==='CANCELLED'&&mission.stop_requested_at&&!mission.stop_confirmed)))
    if(!mission||!needsRefresh)return
    const timer=window.setInterval(()=>{if(document.visibilityState==='visible')void api.mission(mission.mission_id).then(setMission).catch(()=>{})},missionPollIntervalMs)
    return ()=>window.clearInterval(timer)
  },[mission?.mission_id,mission?.status,mission?.stop_confirmed])
  useEffect(() => { if (view === 'ml') void api.model().then(setModel).catch(e => setError(e.message)) }, [view])
  useEffect(() => { if (selected) { void readTrace(selected.mission_id).then(setTrace); void api.results(selected.mission_id).then(setResults).catch(() => setResults(null)) } }, [selected])
  useEffect(() => { if (mission?.mission_id && ['COMPLETED','CANCELLED'].includes(mission.status)) { void loadMissions(); if (selected?.mission_id === mission.mission_id) void api.results(mission.mission_id).then(setResults) } }, [mission, loadMissions, selected])
  const measuredAge = connected && lastSeen != null ? Math.max(0, (Date.now()-lastSeen)/1000) : current ? Math.max(0,(Date.now()-Date.parse(current.timestamp))/1000) : latest?.age_s ?? null
  const liveSourceAllowed = current?.data_source === 'PHYSICAL'
  const signalGood = (latest?.device_status === 'CONECTADO' || (latestTelemetry != null && liveSourceAllowed)) && liveSourceAllowed && (measuredAge ?? Infinity) <= 15
  const missionReady = Boolean(signalGood && current && position && current.gps_accuracy_m != null && current.gps_accuracy_is_bound !== false
    && current.gps_accuracy_m <= 1.5 && current.data_source !== 'RECORDED' && current.data_source !== 'SYNTHETIC')

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setAuthBusy(true); setAuthError('')
    try { await api.login(password); setPassword(''); setAuthenticated(true); setError('') }
    catch (e) { setAuthError(e instanceof Error ? e.message : 'No se pudo iniciar sesión.') }
    finally { setAuthBusy(false) }
  }

  async function signOut() {
    try { await api.logout() } catch { /* the server session may already have expired */ }
    setAuthenticated(false); setLatest(null); setMission(null); setMissions([]); setTrace([]); setSelected(null)
  }

  async function create() {
    setError(''); setNotice('')
    const lat=Number(latInput), lon=Number(lonInput)
    if (!Number.isFinite(lat)||!Number.isFinite(lon)||Math.abs(lat)>90||Math.abs(lon)>180) { setError('Introduce coordenadas válidas.'); return }
    setBusy(true)
    try { const created=await api.createMission(robotId,{lat,lon}); setMission(created); setSelected(null); setNotice('Misión coordinada; esperando confirmación de recepción del destino por ESP32. No implica movimiento físico.'); void loadMissions() }
    catch(e) { setError(e instanceof Error?e.message:'No se pudo crear la misión') } finally { setBusy(false) }
  }
  async function cancel() {
    if (!mission) return
    setBusy(true); setError('')
    try { await api.cancel(mission.mission_id); setMission({ ...mission, status:'CANCELLED', stop_confirmed:false }); setNotice('Solicitud de parada registrada; pendiente de confirmación del controlador local.'); void loadMissions() }
    catch(e) { setError(e instanceof Error?e.message:'No se pudo cancelar la misión') } finally { setBusy(false) }
  }
  async function requestPump(command: 'ON' | 'OFF') {
    setPumpBusy(true)
    try { setPumpExchange(await api.pumpCommand(robotId, command)) }
    catch (e) { setError(e instanceof Error ? e.message : 'No se pudo registrar la solicitud de bomba') }
    finally { setPumpBusy(false) }
  }
  async function openMission(item: Mission) {
    setSelected(item); setMission(item); setLatInput(item.destination.lat.toFixed(7)); setLonInput(item.destination.lon.toFixed(7)); setView('history')
  }

  if (authLoading) return <div className="auth-screen"><div className="auth-card auth-loading"><img src="/rutea.svg" alt=""/><b>RUTEA</b><span>Comprobando sesión segura…</span></div></div>
  if (!authenticated) return <main className="auth-screen"><div className="auth-layout"><section className="auth-visual" aria-hidden="true"><div className="visual-caption"><span>RUTEA / SISTEMAS AUT?NOMOS</span><h2>El camino,<br/><em>con claridad.</em></h2><p>Una perspectiva precisa para cada recorrido.</p></div><svg className="road-scene" viewBox="0 0 600 520" fill="none"><defs><linearGradient id="road" x1="300" y1="120" x2="300" y2="520" gradientUnits="userSpaceOnUse"><stop stopColor="#152d3a"/><stop offset="1" stopColor="#243d49"/></linearGradient><linearGradient id="beam" x1="300" y1="250" x2="300" y2="75" gradientUnits="userSpaceOnUse"><stop stopColor="#39d98a" stopOpacity=".24"/><stop offset="1" stopColor="#39d98a" stopOpacity="0"/></linearGradient></defs><path d="M270 145H330L570 520H30Z" fill="url(#road)"/><path d="M270 145 30 520M330 145 570 520" stroke="#40c9e8" strokeOpacity=".35" strokeWidth="2"/><path className="road-marks" d="M300 150V520" stroke="#cdece2" strokeOpacity=".48" strokeWidth="3" strokeDasharray="12 28"/><path d="M300 300C310 260 260 228 300 170" stroke="#39d98a" strokeWidth="3" strokeLinecap="round" strokeDasharray="5 7"/><path d="M275 290 255 120H345L325 290Z" fill="url(#beam)"/><g className="vehicle"><ellipse cx="300" cy="342" rx="70" ry="18" fill="#06121b" fillOpacity=".7"/><rect x="254" y="275" width="92" height="62" rx="17" fill="#102535" stroke="#6b9ba4" strokeWidth="2"/><path d="M266 291Q300 279 334 291L329 313H271Z" fill="#284d5c" stroke="#70bcc1"/><path d="M263 326H337" stroke="#39d98a" strokeWidth="3" strokeLinecap="round"/><circle className="car-light" cx="265" cy="316" r="4" fill="#b9fff0"/><circle className="car-light" cx="335" cy="316" r="4" fill="#b9fff0"/><path d="M286 276V268H314V276" stroke="#40c9e8" strokeWidth="3" strokeLinecap="round"/></g></svg><div className="visual-footer"><span>01 / NAVEGACI?N</span><span>DISE?ADO PARA AVANZAR <b>?</b></span></div></section><form className="auth-card" onSubmit={signIn}><div className="auth-brand"><img src="/rutea.svg" alt=""/><div><b>RUTEA</b><span>NAVEGACI?N AUT?NOMA</span></div></div><div className="auth-form-copy"><span className="section-kicker">CENTRO DE CONTROL</span><h1>Bienvenido de nuevo</h1><p>Ingresa tu contrase?a para acceder a la plataforma.</p></div><label htmlFor="operator-password">Contrase?a</label><div className="password-field"><input id="operator-password" type={showPassword?'text':'password'} autoComplete="current-password" autoFocus required maxLength={1024} value={password} onChange={event=>setPassword(event.target.value)} placeholder="Escribe tu contrase?a"/><button type="button" className="password-toggle" aria-label={showPassword?'Ocultar contrase?a':'Mostrar contrase?a'} aria-pressed={showPassword} onClick={()=>setShowPassword(!showPassword)}>{showPassword?<EyeOff size={18}/>:<Eye size={18}/>}</button></div><button className="primary-button" type="submit" disabled={authBusy||!password}>{authBusy?'Verificando?':<>Iniciar sesi?n <span aria-hidden="true">?</span></>}</button>{authError&&<div className="operator-auth-error" role="alert">{authError}</div>}<small className="auth-footnote"><ShieldAlert size={13}/> Acceso protegido ? sesi?n temporal</small></form></div></main>

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><img className="brand-logo" src="/rutea.svg" alt=""/></div><div><b>RUTEA</b><span>NAVEGACIÓN AUTÓNOMA</span></div></div>
      <div className="nav-caption">OPERACIÓN</div>
      <button className={`nav-item ${view==='panel'?'active':''}`} onClick={()=>setView('panel')}><Crosshair size={17}/> Panel principal</button>
      <button className={`nav-item ${view==='history'?'active':''}`} onClick={()=>{setSelected(null);setView('history');void loadMissions()}}><History size={17}/> Historial de misiones</button>
      <div className="nav-caption secondary-caption">ANÁLISIS</div>
      <button className={`nav-item ${view==='ml'?'active':''}`} onClick={()=>setView('ml')}><Activity size={17}/> Machine learning</button>
      <div className="sidebar-bottom"><div className="safety-box"><ShieldAlert size={17}/><div><b>Control local seguro</b><span>La nube coordina y observa. La parada física depende del controlador a bordo.</span></div></div><div className="sidebar-foot"><span className="green-pip"/> Entorno local <span className="version">V1.2</span></div></div>
    </aside>

    <main className="main-area">
      <header className="topbar"><div><div className="eyebrow">SISTEMA DE NAVEGACION</div><h1>{view==='panel'?'Panel de operación':view==='history'?'Historial de misiones':'Evaluación de modelo'}</h1></div><div className="top-actions"><div className={`connection ${signalGood?'online':'offline'}`}><span className="connection-dot"/><div><b>{signalGood?'DISPOSITIVO CONECTADO':(current?.data_source==='RECORDED'||latest?.device_status==='RECORDED')?'DATOS REGISTRADOS':(current?.data_source==='SYNTHETIC'||latest?.device_status==='SIMULATION')?'SIMULACION SEPARADA':latest?.device_status==='NO_VERIFICADO'?'FUENTE SIN VERIFICAR':'SIN DISPOSITIVO'}</b><small>{signalGood?`Telemetría ${ageText(measuredAge)}`:latest?.device_status==='NO_VERIFICADO'?'Se recibieron datos sin origen físico declarado':'Sin señal GPS / IMU'}</small></div></div><button type="button" className="operator-avatar" aria-label="Cerrar sesi?n" title="Cerrar sesi?n" onClick={()=>void signOut()}><LogOut size={14}/></button></div></header>

      {error && <div className="alert error"><AlertTriangle size={17}/><span>{error}</span><button onClick={()=>setError('')}>Cerrar</button></div>}
      {notice && <div className="alert success"><Check size={17}/><span>{notice}</span><button onClick={()=>setNotice('')}>Cerrar</button></div>}

      {view==='panel' && <>
        <section className="metric-grid">
          <Metric label="DISTANCIA AL OBJETIVO" value={mission&&current?.mission_id===mission.mission_id?num(current.distance_to_goal_m):selectedDestination&&position?num(haversine({lat:position.lat!,lon:position.lon!},selectedDestination)): "\u2014"} unit="m" icon={MapPin} sub={selectedDestination?"Destino seleccionado":"Sin destino definido"}/>
          <Metric label="VELOCIDAD" value={num(current?.speed_mps,2)} unit="m/s" icon={Gauge} sub={current?current.status:'Esperando telemetría'}/>
          <Metric label="PRECISIÓN GPS" value={num(current?.gps_accuracy_m,1)} unit={current?.gps_accuracy_m==null?"":"m"} icon={Crosshair} sub={current?.gps_accuracy_m==null?"No disponible; HDOP no se convierte a metros":current.gps_accuracy_source==='UBX_NAV_POSLLH.hAcc'?"u-blox hAcc estimada; no es límite garantizado":current.gps_accuracy_status==="ESTIMATED"?"Estimación declarada por la fuente":current.gps_accuracy_status==="MEASURED"?"Medición declarada por la fuente":"Valor declarado; origen no especificado"}/>
          <Metric label="MISIÓN" value={mission?.status==='ACTIVE'&&!signalGood?'Sin señal':fmtMission(mission?.status)} icon={Route} sub={mission?`${mission.distance_m.toFixed(1)} m · ${mission.controller_version}`:'Lista para planificar'}/>
        </section>
        <section className="workspace-grid">
          <div className="panel map-panel"><div className="panel-heading"><div><span className="section-kicker">VISTA GEOGRAFICA</span><h2>Mapa de navegacion</h2></div><div className="map-heading-right"><span className="map-mode"><CircleDot size={13}/> {(current?.data_source==='RECORDED'||latest?.device_status==='RECORDED')?'Registro NMEA (no fisico)':(current?.data_source==='SYNTHETIC'||latest?.device_status==='SIMULATION')?'Simulacion separada':signalGood?'Telemetria recibida':'Sin senal real'}</span></div></div><div className="map-content"><MapView current={position} destination={selectedDestination} mission={mission} trace={mapTrace} onPick={onPick}/>{!position&&<div className="map-empty"><div className="empty-icon"><WifiOff size={22}/></div><b>{current?'GPS sin posicion valida':'SIN DISPOSITIVO'}</b><span>{current?'No se dibuja una coordenada sin fix valido.':'Al recibir telemetria valida, su posicion aparecera aqui.'}</span></div>}</div><div className="map-footer"><span><i className="green-pip"/> Ruta geometrica calculada desde A fija</span><span className="map-coord">{position?`${position.lat!.toFixed(5)}, ${position.lon!.toFixed(5)}`:'Posicion no disponible'}</span></div></div>
          <div className="right-stack">
            <div className="panel mission-panel"><div className="panel-heading"><div><span className="section-kicker">PLANIFICACIÓN</span><h2>Destino de misión</h2></div><Waypoints size={17} className="muted-icon"/></div><p className="helper-text">Haz clic en el mapa o escribe coordenadas WGS84.</p><label className="field-label">LATITUD</label><div className="coord-input"><span>Ï†</span><input value={latInput} onChange={e=>setLatInput(e.target.value)} placeholder="-12.0464000" inputMode="decimal"/></div><label className="field-label">LONGITUD</label><div className="coord-input"><span>Î»</span><input value={lonInput} onChange={e=>setLonInput(e.target.value)} placeholder="-77.0428000" inputMode="decimal"/></div>{selectedDestination&&position&&<div className="distance-note"><ArrowUpRight size={15}/> Distancia estimada <b>{(haversine({lat:position.lat!,lon:position.lon!},selectedDestination)/1000).toFixed(2)} km</b></div>}
              {!hasMission?<button className="primary-button" onClick={create} disabled={busy||!inputDestination||!missionReady}><Send size={15}/>{busy?'Asignando...':'Crear mision'}</button>:<button className="danger-button" onClick={cancel} disabled={busy}><Square size={14} fill="currentColor"/>{busy?'Registrando...':'Cancelar / solicitar parada'}</button>}
              <div className={`mission-state ${hasMission?'state-active':''}`}><span className="state-dot"/><span><b>{mission?.status==='ACTIVE'&&!signalGood?'Sin señal':fmtMission(mission?.status)}</b><small>{mission?.status==='ACTIVE'&&!signalGood?'Telemetría vencida; parada local no confirmada':mission?.stop_requested_at&&mission.stop_confirmed?'Parada confirmada por controlador':mission?.stop_requested_at&&!mission.stop_confirmed?'Parada solicitada · sin confirmar':mission?.status==='ACTIVE'?'Actividad reportada por telemetría':mission?.status==='PENDING'?(mission.command_delivery_status==='RECEIVED'?'Destino recibido; movimiento no confirmado':'Esperando recibo de destino ESP32'):'No hay movimiento físico confirmado'}</small></span></div>
            </div>
            <div className="panel telemetry-panel">
              <div className="panel-heading compact"><div><span className="section-kicker">TELEMETRIA</span><h2>Estado del robot</h2></div><span className={`live-tag ${signalGood?'live':'idle'}`}><i/>{signalGood?'EN LINEA':(current?.data_source==='RECORDED'||latest?.device_status==='RECORDED')?'REGISTRADO':(current?.data_source==='SYNTHETIC'||latest?.device_status==='SIMULATION')?'SIMULACION':'SIN DISPOSITIVO'}</span></div>
              <div className="telemetry-list">
                <TelemetryRow icon={MapPin} label="Latitud / longitud" value={position?`${num(position.lat,6)}, ${num(position.lon,6)}`:'No valida'}/>
                <TelemetryRow icon={Compass} label="Rumbo / fuente" value={current?`${current.heading_deg==null?'Relativo/no absoluto':`${num(current.heading_deg,1)}\u00b0`} \u00b7 ${current.heading_source||'desconocida'}`:'\u2014'}/>
                <TelemetryRow icon={Gauge} label="Velocidad GPS" value={current?.speed_mps!=null?`${num(current.speed_mps,2)} m/s`:'No disponible'}/>
                <TelemetryRow icon={Crosshair} label="GPS / fix" value={!current?'Sin dispositivo':`${statusText(current.sensor_status?.gps)} · ${current.gps_fix_valid===false?'sin fix / posición inválida':current.gps_fix_valid===true?'fix válido':'fix no informado'}`}/>
                <TelemetryRow icon={CircleDot} label="Satélites / HDOP" value={current?`${current.gps_satellites??'—'} / ${current.gps_hdop==null?'—':num(current.gps_hdop,1)} (HDOP relativo, no metros)`:'—'}/>
                <TelemetryRow icon={Crosshair} label="Calidad para READY" value={statusText(current?.sensor_status?.gps_quality)}/>
                <TelemetryRow icon={Activity} label="ESP32" value={statusText(current?.sensor_status?.esp32)} />
                <TelemetryRow icon={WifiOff} label="Wi-Fi" value={statusText(current?.sensor_status?.wifi)} />
                <TelemetryRow icon={ShieldAlert} label="Estado de seguridad" value={statusText(current?.sensor_status?.safety)} />
                <TelemetryRow icon={Activity} label="IMU MPU-6050" value={statusText(current?.sensor_status?.imu)}/>
                <TelemetryRow icon={Gauge} label="Frecuencia de telemetría" value={current?`${statusText(current.sensor_status?.publish_hz)} Hz nominal · ${statusText(current.sensor_status?.publish_period_ms)} ms`: '—'}/>
                <TelemetryRow icon={Crosshair} label="hAcc UBX" value={current?.gps_accuracy_m!=null?`${num(current.gps_accuracy_m,2)} m · ${current.gps_accuracy_source||'origen no informado'} · estimación, no límite`: 'No disponible'}/>
                <TelemetryRow icon={ArrowDownRight} label="Error lateral / angular" value={current?.cross_track_error_m!=null?`${num(current.cross_track_error_m)} m \u00b7 ${current.heading_error_rad!=null?`${num(current.heading_error_rad*180/Math.PI,1)}\u00b0`:'angular no disponible'}`:'No disponible'}/>
                <TelemetryRow icon={Clock3} label="Última medición / edad" value={current?`${current.sensor_timestamp?dateText(current.sensor_timestamp):'Sin muestra de sensor'} · ${ageText(measuredAge)}`:'Sin datos'}/>
                <TelemetryRow icon={AlertTriangle} label="Errores sensores" value={current?`GPS ${statusText(current.sensor_status?.gps_nmea_checksum_errors)}/${statusText(current.sensor_status?.gps_ubx_checksum_errors)} checksum · ${statusText(current.sensor_status?.imu_error||current.sensor_status?.imu)}`:'Sin diagnóstico'}/>
              </div>
              {current&&(current.data_source==='RECORDED'||current.data_source==='SYNTHETIC'||!sampleFresh||current.gps_fix_valid===false||current.sensor_status?.gps_quality==='INSUFFICIENT_OR_UNKNOWN'||current.gps_accuracy_m==null||current.gps_accuracy_is_bound===false||current.heading_quality?.includes('DRIFTING'))&&<div className="safety-note"><AlertTriangle size={15}/>{current.data_source==='RECORDED'?'Datos registrados; no habilitan control físico.':current.data_source==='SYNTHETIC'?'Datos sintéticos separados; no habilitan control físico.':!sampleFresh?'Telemetría antigua; la posición se descarta.':current.gps_fix_valid===false?'GPS sin fix válido; posición descartada.':current.sensor_status?.gps_quality==='INSUFFICIENT_OR_UNKNOWN'?'Calidad GPS insuficiente o desconocida para READY (revisar satélites y HDOP).':current.gps_accuracy_is_bound===false?'hAcc es una estimación del receptor, no un límite garantizado; la misión física está bloqueada.':current.gps_accuracy_m==null?'Precisión métrica no disponible; misiones bloqueadas.':'Rumbo relativo con deriva; no es rumbo absoluto.'}</div>}
              <div className="telemetry-foot"><span>ID {robotId}</span><span>{current?dateText(current.sensor_timestamp||current.timestamp):'Esperando primer paquete'}</span></div>
            </div>
          </div>
        </section>
        <section className="panel pump-panel">
          <div className="pump-heading"><div className="pump-icon"><Droplet size={20}/></div><div><span className="section-kicker">APLICADOR · SOLO CONTRATO DE PRUEBA</span><h2>Bomba de fumigación</h2></div><span className="pump-sim-badge">TRANSPORTE SIMULADO</span></div>
          <div className="pump-content"><div className="pump-controls"><button className="pump-off" onClick={()=>void requestPump('OFF')} disabled={pumpBusy}>OFF <small>solicitar apagado</small></button><button className="pump-on" onClick={()=>void requestPump('ON')} disabled={pumpBusy}>ON <small>solicitud de prueba</small></button></div><div className="pump-status"><b>{pumpExchange?`Última palabra enviada: ${pumpExchange.wire_payload}`:'Estado confirmado: sin lectura física'}</b><span>{pumpExchange?`Recepción: ${pumpExchange.receipt} · Autorización: denegada; faltan enclavamientos locales.`:'Solicitud inicial OFF; el firmware no implementa salida física ni Bluetooth.'}</span><small>Confirmación física: no disponible · Salida física habilitada: no</small></div></div>
          <div className="pump-safety"><ShieldAlert size={15}/> Una solicitud ON no activa la bomba. GPS válido, avance confirmado, ausencia de giro/parada, comunicación, E-stop y feedback físico deben autorizarse localmente.</div>
        </section>
        <section className="panel recent-panel"><div className="panel-heading"><div><span className="section-kicker">ACTIVIDAD</span><h2>Misiones recientes</h2></div><button className="text-button" onClick={()=>{setView('history');void loadMissions()}}>Ver historial <ChevronRight size={15}/></button></div>{missions.length===0?<div className="empty-inline"><History size={18}/> Todavía no hay misiones guardadas.</div>:<div className="recent-list">{missions.slice(0,4).map(m=><button className="recent-row" key={m.mission_id} onClick={()=>void openMission(m)}><span className="mission-badge"><Route size={16}/></span><span className="recent-title"><b>Destino {m.destination.lat.toFixed(4)}, {m.destination.lon.toFixed(4)}</b><small>{dateText(m.created_at)} · {m.distance_m.toFixed(0)} m</small></span><span className={`status-pill ${m.status.toLowerCase()}`}>{fmtMission(m.status)}</span><ChevronRight size={15} className="row-chevron"/></button>)}</div>}</section>
      </>}

      {view==='history' && <section className="history-layout"><div className="panel history-panel"><div className="panel-heading"><div><span className="section-kicker">REGISTRO PERSISTENTE</span><h2>Misiones guardadas</h2></div><button className="icon-button" onClick={()=>void loadMissions()} title="Actualizar"><Activity size={16}/></button></div>{missions.length===0?<div className="empty-state"><History size={25}/><b>Sin misiones registradas</b><span>Las misiones aparecerán aquí cuando se asignen a un robot con telemetría reciente.</span></div>:<div className="history-list">{missions.map(m=><button key={m.mission_id} className={`history-item ${selected?.mission_id===m.mission_id?'selected':''}`} onClick={()=>void openMission(m)}><div className="history-item-top"><span className={`status-pill ${m.status.toLowerCase()}`}>{fmtMission(m.status)}</span><small>{dateText(m.created_at)}</small></div><b>{m.origin.lat.toFixed(4)}, {m.origin.lon.toFixed(4)} <ArrowUpRight size={13}/> {m.destination.lat.toFixed(4)}, {m.destination.lon.toFixed(4)}</b><div className="history-item-bottom"><span><Route size={13}/>{m.distance_m.toFixed(1)} m</span><span><Bot size={13}/>{m.controller_version}</span><ChevronRight size={15}/></div></button>)}</div>}</div><div className="panel detail-panel">{selected?<><div className="panel-heading"><div><span className="section-kicker">DETALLE DE MISIÓN</span><h2>{selected.mission_id.slice(0,12)}</h2></div><span className={`status-pill ${selected.status.toLowerCase()}`}>{fmtMission(selected.status)}</span></div><div className="detail-grid"><div><small>ORIGEN A (FIJO)</small><b>{selected.origin.lat.toFixed(6)}, {selected.origin.lon.toFixed(6)}</b></div><div><small>DESTINO B</small><b>{selected.destination.lat.toFixed(6)}, {selected.destination.lon.toFixed(6)}</b></div><div><small>DISTANCIA PLANIFICADA</small><b>{selected.distance_m.toFixed(2)} m</b></div><div><small>CREACIÓN</small><b>{dateText(selected.created_at)}</b></div></div><div className="trace-chart"><div className="chart-title">Error lateral registrado <span>m</span></div>{trace.length>1?<Sparkline values={trace.map(x=>x.cross_track_error_m).filter((x):x is number=>x!=null)}/>:<div className="chart-empty">No hay suficientes muestras de telemetría vinculadas a esta misión.</div>}<div className="chart-axis"><span>Inicio del registro</span><span>{trace.length} muestras</span></div></div><div className="result-chips"><span>RMSE lateral <b>{results?.rmse_lateral_m!=null?`${Number(results.rmse_lateral_m).toFixed(3)} m`:'—'}</b></span><span>Error máximo <b>{results?.max_lateral_error_m!=null?`${Number(results.max_lateral_error_m).toFixed(3)} m`:'—'}</b></span><span>Duración <b>{results?.duration_s!=null?`${Number(results.duration_s).toFixed(1)} s`:'—'}</b></span></div><div className="panel history-map"><div className="panel-heading"><div><span className="section-kicker">TRAYECTORIA REGISTRADA</span><h2>Ruta ideal y recorrido recibido</h2></div></div><div className="map-content"><MapView current={null} destination={selected.destination} mission={selected} trace={trace} onPick={ignorePick}/></div></div><button className="secondary-button" onClick={()=>setView('panel')}><MapPin size={15}/> Ver misión en mapa</button></>:<div className="empty-state detail-empty"><MapPin size={25}/><b>Selecciona una misión</b><span>Consulta el origen, destino, telemetría registrada y métricas disponibles.</span></div>}</div></section>}

      {view==='ml' && <section className="ml-layout"><div className="panel model-hero"><div className="model-icon"><Activity size={22}/></div><div className="model-summary"><span className="section-kicker">CONTROL ADAPTATIVO · EVALUACIÓN OFFLINE</span><h2>{model?.available?'Modelo entrenado disponible':'Modelo no entrenado'}</h2><p>{model?.available?`Versión ${model.version}. Ajuste angular acotado, con fallback al controlador clásico.`:'Ejecuta el entrenamiento offline para crear un artefacto reproducible y consultar sus métricas.'}</p></div><span className={`live-tag ${model?.available?'live':'idle'}`}><i/>{model?.available?'ARTEFACTO LOCAL':'SIN ARTEFACTO'}</span></div><div className="model-grid"><div className="panel model-card"><div className="panel-heading"><div><span className="section-kicker">MODELO</span><h2>Estado de inferencia</h2></div><Bot size={18} className="muted-icon"/></div><div className="model-rows"><ModelRow name="Versión" value={model?.version||'—'}/><ModelRow name="Entrenamiento" value={model?.available?'Offline · episodios sintéticos':'Pendiente'}/><ModelRow name="Controlador de referencia" value="PD · pd-1.0"/><ModelRow name="Activación física" value="Deshabilitada"/><ModelRow name="Fallback" value="Controlador clásico"/></div><div className="safety-note"><ShieldAlert size={15}/> ML no controla motores físicos. La nube solo coordina y registra.</div></div><div className="panel model-card metrics-card"><div className="panel-heading"><div><span className="section-kicker">COMPARACIÓN</span><h2>Métricas disponibles</h2></div><Activity size={17} className="muted-icon"/></div>{model?.metrics?<><div className="comparison-empty"><b>Evaluación sintética offline</b><span>Las siguientes cifras describen predicción de corrección angular. No son métricas de navegación física ni prueba de mejora frente al controlador base.</span></div><div className="ml-metric-grid"><MiniMetric label="RMSE corrección" value={model.metrics.test_rmse_rps} unit="rad/s"/><MiniMetric label="MAE corrección" value={model.metrics.test_mae_rps} unit="rad/s"/><MiniMetric label="Episodios prueba" value={model.metrics.split_episode_counts && (model.metrics.split_episode_counts as Record<string,number>).test} unit="episodios"/></div><ModelComparison comparison={simComparison}/><div className="metric-bars"><div><span>Datos generados</span><b>{String(model.metrics.episode_count)} episodios completos</b><i style={{width:'100%'}}/></div><div><span>Semilla reproducible</span><b>{String(model.metrics.seed)}</b><i style={{width:'62%'}}/></div></div></>:<div className="empty-state compact-empty"><Activity size={24}/><b>Sin métricas todavía</b><span>Entrena con <code>python -m app.ml.train</code> desde Backend para generar el modelo y métricas medibles.</span></div>}</div></div><div className="panel ml-footnote"><ArrowUpRight size={16}/><span>La validación del artefacto es sintética y offline. Antes de cualquier uso con hardware se requiere evaluación segura en simulación calibrada y autorización explícita desde un controlador local.</span></div></section>}
      <footer className="page-footer"><span>RUTEA V1.2 · Coordinación de misión</span><span><span className="green-pip"/> Telemetría recibida; sin interpolación</span></footer>
    </main>
  </div>
}

function TelemetryRow({ icon: Icon, label, value }: { icon: typeof Gauge; label: string; value: string }) { return <div className="telemetry-row"><Icon size={14}/><span>{label}</span><b>{value}</b></div> }
function ModelRow({name,value}:{name:string;value:string}) { return <div className="model-row"><span>{name}</span><b>{value}</b></div> }
function MiniMetric({label,value,unit}:{label:string;value:unknown;unit:string}) { return <div className="mini-metric"><span>{label}</span><b>{typeof value==='number'?value.toFixed(4):'—'} <small>{unit}</small></b></div> }
function ModelComparison({comparison}:{comparison:{comparison?:Record<string,Record<string,number|null>>;seed?:number}|undefined}) {
  if (!comparison?.comparison) return null
  return <div className="comparison-table-wrap"><table className="comparison-table"><thead><tr><th>Variante</th><th>RMSE lateral</th><th>Error máximo</th><th>Llegada</th><th>Tiempo</th></tr></thead><tbody>{(['base','base_plus_ml'] as const).map(key=>{const row=comparison.comparison?.[key];return <tr key={key}><td>{key==='base'?'Controlador base':'Base + ML'}</td><td>{num(row?.rmse_lateral_m,3)} m</td><td>{num(row?.max_lateral_error_m,3)} m</td><td>{row?.arrival_rate==null?'—':`${(row.arrival_rate*100).toFixed(0)}%`}</td><td>{row?.mean_time_s==null?'—':`${row.mean_time_s.toFixed(1)} s`}</td></tr>})}</tbody></table><div className="comparison-caption">Mismas condiciones iniciales · {comparison.seed ?? '—'} semilla · sin hardware</div></div>
}
function Sparkline({values}:{values:number[]}) { if(values.length<2)return <div className="chart-empty">No hay suficientes muestras para graficar.</div>; const max=Math.max(...values.map(Math.abs),.01); const points=values.map((v,i)=>`${(i/(values.length-1))*100},${50-(v/max)*44}`).join(' '); return <svg className="sparkline" viewBox="0 0 100 100" preserveAspectRatio="none"><line x1="0" y1="50" x2="100" y2="50" className="zero-line"/><polyline points={points}/></svg> }

