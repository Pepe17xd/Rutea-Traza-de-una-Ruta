import { useEffect, useRef } from 'react'
import maplibregl, { type Map as MapLibreMap, type StyleSpecification } from 'maplibre-gl'
import type { Mission, Point, Telemetry } from '../types'

type Props = { current: Telemetry | null; destination: Point | null; mission: Mission | null; trace: Telemetry[]; onPick: (point: Point) => void }
const style: string | StyleSpecification = import.meta.env.VITE_MAP_STYLE_URL || { version: 8, sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap contributors' } }, layers: [{ id: 'osm', type: 'raster', source: 'osm' }] }

export default function MapView({ current, destination, mission, trace, onPick }: Props) {
  const element = useRef<HTMLDivElement>(null); const map = useRef<MapLibreMap | null>(null); const currentMarker = useRef<maplibregl.Marker | null>(null); const destMarker = useRef<maplibregl.Marker | null>(null)
  useEffect(() => {
    if (!element.current) return
    const instance = new maplibregl.Map({ container: element.current, style, center: [-77.04, -12.05], zoom: 13, attributionControl: {} })
    map.current = instance; instance.addControl(new maplibregl.NavigationControl(), 'top-right')
    instance.on('load', () => {
      instance.addSource('ideal', { type: 'geojson', data: { type: 'Feature', geometry: { type: 'LineString', coordinates: [] }, properties: {} } })
      instance.addSource('actual', { type: 'geojson', data: { type: 'Feature', geometry: { type: 'LineString', coordinates: [] }, properties: {} } })
      instance.addLayer({ id: 'ideal-line', type: 'line', source: 'ideal', paint: { 'line-color': '#a5bd57', 'line-width': 4, 'line-opacity': 0.95, 'line-dasharray': [1.5, 1] } })
      instance.addLayer({ id: 'actual-line', type: 'line', source: 'actual', paint: { 'line-color': '#d18b59', 'line-width': 3, 'line-opacity': 0.95 } })
    })
    instance.on('click', e => onPick({ lat: e.lngLat.lat, lon: e.lngLat.lng }))
    return () => { currentMarker.current?.remove(); destMarker.current?.remove(); instance.remove(); map.current = null }
  }, [onPick])
  useEffect(() => {
    const instance = map.current; if (!instance) return
    const update = () => {
      const ideal = instance.getSource('ideal') as maplibregl.GeoJSONSource | undefined
      const actual = instance.getSource('actual') as maplibregl.GeoJSONSource | undefined
      if (ideal) ideal.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: (mission?.waypoints || []).map(p => [p.lon,p.lat]) }, properties: {} })
      if (actual) actual.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: trace.filter(p=>p.lat!=null&&p.lon!=null&&p.gps_fix_valid!==false).map(p => [p.lon!,p.lat!]) }, properties: {} })
      if (current && current.lat != null && current.lon != null && current.gps_fix_valid !== false) {
        if (!currentMarker.current) currentMarker.current = new maplibregl.Marker({ color: '#8eaa91' }).setLngLat([current.lon,current.lat]).addTo(instance)
        else currentMarker.current.setLngLat([current.lon,current.lat])
      } else { currentMarker.current?.remove(); currentMarker.current = null }
      if (destination) {
        if (!destMarker.current) destMarker.current = new maplibregl.Marker({ color: '#a5bd57' }).setLngLat([destination.lon,destination.lat]).addTo(instance)
        else destMarker.current.setLngLat([destination.lon,destination.lat])
      } else { destMarker.current?.remove(); destMarker.current = null }
    }
    if (instance.isStyleLoaded()) update(); else instance.once('load', update)
    if (current && current.lat != null && current.lon != null && current.gps_fix_valid !== false) instance.easeTo({ center: [current.lon,current.lat], duration: 450 })
  }, [current, destination, mission, trace])
  return <div className="map-wrap"><div ref={element} className="map-canvas"/><div className="map-legend"><span><i className="dot robot"/> Posición recibida</span><span><i className="line ideal"/> Ruta ideal</span><span><i className="line actual"/> Recorrido recibido</span></div></div>
}
