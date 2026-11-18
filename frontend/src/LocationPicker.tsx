import { CircleMarker, MapContainer, TileLayer, useMapEvents } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'

export type Point = [number, number]

const UFA: Point = [54.7388, 55.9721]

function Clicks({ onPick }: { onPick: (p: Point) => void }) {
  useMapEvents({ click: (e) => onPick([e.latlng.lat, e.latlng.lng]) })
  return null
}

interface Props {
  value: Point | null
  onChange: (p: Point | null) => void
}

/** Выбор места обращения кликом по карте Уфы. */
export default function LocationPicker({ value, onChange }: Props) {
  return (
    <div className="picker">
      <MapContainer center={value ?? UFA} zoom={11} scrollWheelZoom={false} style={{ height: 280, width: '100%' }}>
        <TileLayer
          attribution='&copy; участники <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Clicks onPick={onChange} />
        {value && <CircleMarker center={value} radius={9} pathOptions={{ color: '#b3261e', fillOpacity: 0.7 }} />}
      </MapContainer>
      <div className="picker-row">
        <span className="muted">
          {value
            ? `Точка выбрана: ${value[0].toFixed(5)}, ${value[1].toFixed(5)}`
            : 'Нажмите на карту, чтобы отметить место'}
        </span>
        {value && (
          <button type="button" onClick={() => onChange(null)}>
            Убрать точку
          </button>
        )}
      </div>
    </div>
  )
}
