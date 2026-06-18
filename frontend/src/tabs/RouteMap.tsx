import { useEffect, useRef } from "react";
import { MapContainer, TileLayer, Polyline, Marker, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { Waypoint } from "../api";

// Fix leaflet default marker icon asset breakage with webpack/vite bundling
// by using a divIcon (no asset dependency)
function makeIcon(index: number, total: number): L.DivIcon {
  const isFirst = index === 0;
  const isLast = index === total - 1;
  const bg = isFirst ? "#22c55e" : isLast ? "#ef4444" : "#00d4ff";
  const label = isFirst ? "S" : isLast ? "E" : String(index + 1);
  return L.divIcon({
    className: "",
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<div style="
      width:22px;height:22px;
      border-radius:50%;
      background:${bg};
      border:2px solid rgba(0,0,0,0.5);
      display:flex;align-items:center;justify-content:center;
      color:#040d1a;font-size:9px;font-weight:bold;
      font-family:'Courier New',monospace;
      box-shadow:0 0 8px ${bg};
      cursor:pointer;
    ">${label}</div>`,
  });
}

/* Map click handler — appends a waypoint */
function ClickHandler({
  onAppend,
}: {
  onAppend: (lat: number, lon: number) => void;
}) {
  useMapEvents({
    click(e) {
      onAppend(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

interface Props {
  waypoints: Waypoint[];
  onChange: (wps: Waypoint[]) => void;
}

export default function RouteMap({ waypoints, onChange }: Props) {
  const positions = waypoints.map((w) => [w.lat, w.lon] as [number, number]);

  // Center on first waypoint or fallback
  const center: [number, number] =
    waypoints.length > 0 ? [waypoints[0].lat, waypoints[0].lon] : [0, 0];

  const markerRefs = useRef<(L.Marker | null)[]>([]);

  // Keep marker refs array in sync
  useEffect(() => {
    markerRefs.current = markerRefs.current.slice(0, waypoints.length);
  }, [waypoints.length]);

  const handleDragEnd = (index: number) => {
    const marker = markerRefs.current[index];
    if (!marker) return;
    const { lat, lng } = marker.getLatLng();
    const updated = waypoints.map((w, i) =>
      i === index ? { ...w, lat, lon: lng } : w
    );
    onChange(updated);
  };

  const handleRemove = (index: number) => {
    onChange(waypoints.filter((_, i) => i !== index));
  };

  const handleAppend = (lat: number, lon: number) => {
    onChange([
      ...waypoints,
      { name: `WP${waypoints.length + 1}`, lat, lon },
    ]);
  };

  // Insert a waypoint into a leg at the clicked point: clicking the segment
  // between waypoint `i` and `i+1` splices a new waypoint in at index `i+1`.
  const handleInsert = (afterIndex: number, lat: number, lon: number) => {
    const updated = [...waypoints];
    updated.splice(afterIndex, 0, { name: `WP${waypoints.length + 1}`, lat, lon });
    onChange(updated);
  };

  return (
    <MapContainer
      center={center}
      zoom={waypoints.length > 0 ? 8 : 2}
      style={{ width: "100%", height: "100%", minHeight: 380 }}
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
        // Plain OpenStreetMap raster tiles
      />

      {/* Route polyline (visual) */}
      {positions.length > 1 && (
        <Polyline
          positions={positions}
          pathOptions={{
            color: "#00d4ff",
            weight: 2,
            opacity: 0.85,
            dashArray: "6 4",
            interactive: false, // clicks go to the per-leg hit targets below
          }}
        />
      )}

      {/* Per-leg transparent hit targets: click a leg to insert a waypoint at
          that point (the thin dashed line above is too narrow to click). */}
      {waypoints.slice(0, -1).map((_, i) => (
        <Polyline
          key={`leg-${i}-${waypoints[i].lat}-${waypoints[i + 1].lat}`}
          positions={[
            [waypoints[i].lat, waypoints[i].lon],
            [waypoints[i + 1].lat, waypoints[i + 1].lon],
          ]}
          pathOptions={{ color: "#00d4ff", weight: 16, opacity: 0 }}
          eventHandlers={{
            click: (e) => {
              // Leaflet path clicks otherwise also bubble to the map (which
              // would append a waypoint); stop it so only the mid-leg insert runs.
              L.DomEvent.stopPropagation(e);
              handleInsert(i + 1, e.latlng.lat, e.latlng.lng);
            },
          }}
        />
      ))}

      {/* Waypoint markers */}
      {waypoints.map((wp, i) => (
        <Marker
          key={`${i}-${wp.lat}-${wp.lon}`}
          position={[wp.lat, wp.lon]}
          icon={makeIcon(i, waypoints.length)}
          draggable
          ref={(el) => {
            markerRefs.current[i] = el;
          }}
          eventHandlers={{
            dragend: () => handleDragEnd(i),
            click: () => handleRemove(i),
          }}
        />
      ))}

      <ClickHandler onAppend={handleAppend} />
    </MapContainer>
  );
}
