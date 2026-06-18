import { useEffect, useRef, useState } from "react";
import { api, Waypoint } from "../api";

// Lazy-import RouteMap to avoid SSR issues with leaflet
import RouteMap from "./RouteMap";

/* ── Toast ── */
function Toast({ msg, isErr, onDone }: { msg: string; isErr?: boolean; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 3500);
    return () => clearTimeout(t);
  }, [onDone]);
  return (
    <div className="toast-anim fixed top-0 inset-x-0 z-50 flex justify-center" style={{ pointerEvents: "none" }}>
      <div
        className="mt-2 px-5 py-2 text-xs"
        style={{
          background: isErr ? "rgba(239,68,68,0.1)" : "#0a1e14",
          border: `1px solid ${isErr ? "#ef4444" : "#22c55e"}`,
          color: isErr ? "#ef4444" : "#22c55e",
          fontFamily: "'Courier New', monospace",
          letterSpacing: "0.08em",
          boxShadow: `0 4px 24px ${isErr ? "rgba(239,68,68,0.15)" : "rgba(0,255,100,0.15)"}`,
        }}
      >
        {msg}
      </div>
    </div>
  );
}

/* ── Segmented control ── */
type Mode = "list" | "upload" | "map";
function ModeControl({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  const modes: { id: Mode; label: string }[] = [
    { id: "list", label: "LIST" },
    { id: "upload", label: "UPLOAD" },
    { id: "map", label: "MAP" },
  ];
  return (
    <div className="flex" style={{ border: "1px solid rgba(0,212,255,0.2)" }}>
      {modes.map(({ id, label }) => (
        <button
          key={id}
          onClick={() => onChange(id)}
          style={{
            padding: "5px 20px",
            fontSize: 10,
            letterSpacing: "0.15em",
            fontFamily: "'Courier New', monospace",
            textTransform: "uppercase",
            background: mode === id ? "rgba(0,212,255,0.15)" : "transparent",
            color: mode === id ? "#00d4ff" : "#4a6a8a",
            border: "none",
            borderRight: "1px solid rgba(0,212,255,0.15)",
            cursor: "pointer",
            outline: "none",
            transition: "all 0.15s",
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/* ── Editable waypoint row ── */
function WaypointRow({
  wp,
  index,
  total,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
}: {
  wp: Waypoint;
  index: number;
  total: number;
  onChange: (wp: Waypoint) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}) {
  return (
    <tr
      style={{
        borderBottom: "1px solid rgba(0,212,255,0.07)",
        background: index % 2 === 0 ? "#070f1f" : "#0a1628",
      }}
    >
      <td style={{ padding: "4px 8px", width: 36, color: "#3a5070", fontSize: 10, fontFamily: "'Courier New', monospace", textAlign: "center" }}>
        {index + 1}
      </td>
      <td style={{ padding: "4px 6px" }}>
        <input
          type="text"
          value={wp.name}
          onChange={(e) => onChange({ ...wp, name: e.target.value })}
          style={{ width: "100%", minWidth: 80 }}
        />
      </td>
      <td style={{ padding: "4px 6px" }}>
        <input
          type="number"
          value={wp.lat}
          step="0.0001"
          onChange={(e) => onChange({ ...wp, lat: parseFloat(e.target.value) || 0 })}
          style={{ width: 110 }}
        />
      </td>
      <td style={{ padding: "4px 6px" }}>
        <input
          type="number"
          value={wp.lon}
          step="0.0001"
          onChange={(e) => onChange({ ...wp, lon: parseFloat(e.target.value) || 0 })}
          style={{ width: 110 }}
        />
      </td>
      <td style={{ padding: "4px 8px", whiteSpace: "nowrap" }}>
        <button
          onClick={onMoveUp}
          disabled={index === 0}
          title="Move up"
          style={{ background: "none", border: "none", color: index === 0 ? "#2a3a4a" : "#00d4ff", cursor: index === 0 ? "default" : "pointer", fontSize: 12, padding: "0 3px" }}
        >
          ↑
        </button>
        <button
          onClick={onMoveDown}
          disabled={index === total - 1}
          title="Move down"
          style={{ background: "none", border: "none", color: index === total - 1 ? "#2a3a4a" : "#00d4ff", cursor: index === total - 1 ? "default" : "pointer", fontSize: 12, padding: "0 3px" }}
        >
          ↓
        </button>
        <button
          onClick={onRemove}
          title="Remove"
          style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", fontSize: 12, padding: "0 3px", opacity: 0.7 }}
        >
          ✕
        </button>
      </td>
    </tr>
  );
}

/* ── Main ── */
export default function RouteTab() {
  const [waypoints, setWaypoints] = useState<Waypoint[]>([]);
  const [mode, setMode] = useState<Mode>("list");
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; err: boolean } | null>(null);

  // Upload state
  const [uploadPreview, setUploadPreview] = useState<Waypoint[] | null>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  // Load route on mount
  useEffect(() => {
    api.getRoute().then((r) => setWaypoints(r.waypoints)).catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.putRoute(waypoints);
      setToast({ msg: "Route saved — sim re-routing…", err: false });
    } catch (e: unknown) {
      const err = e as { errors?: { waypoints?: string }; error?: string };
      setToast({ msg: err?.errors?.waypoints ?? err?.error ?? "Save failed", err: true });
    } finally {
      setSaving(false);
    }
  };

  const addRow = () => {
    setWaypoints((wps) => [
      ...wps,
      { name: `WP${wps.length + 1}`, lat: 0, lon: 0 },
    ]);
  };

  const swapRows = (a: number, b: number) => {
    setWaypoints((wps) => {
      const next = [...wps];
      [next[a], next[b]] = [next[b], next[a]];
      return next;
    });
  };

  const handleFile = async (file: File) => {
    setUploading(true);
    setUploadErr(null);
    setUploadPreview(null);
    try {
      const res = await api.importRoute(file);
      setUploadPreview(res.waypoints);
    } catch (e: unknown) {
      const err = e as { errors?: { file?: string }; error?: string };
      setUploadErr(err?.errors?.file ?? err?.error ?? "Parse failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="flex flex-col" style={{ height: "calc(100vh - 120px)", minHeight: 500 }}>
      {toast && (
        <Toast msg={toast.msg} isErr={toast.err} onDone={() => setToast(null)} />
      )}

      {/* ── Toolbar ── */}
      <div
        className="flex items-center gap-4 px-5 py-3 flex-shrink-0"
        style={{ borderBottom: "1px solid rgba(0,212,255,0.1)", background: "#060f1e" }}
      >
        <ModeControl mode={mode} onChange={setMode} />
        <span style={{ flex: 1 }} />
        <span style={{ color: "#3a5570", fontSize: 10, fontFamily: "'Courier New', monospace" }}>
          {waypoints.length} WP{waypoints.length !== 1 ? "S" : ""}
        </span>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            padding: "6px 22px",
            fontSize: 10,
            letterSpacing: "0.15em",
            textTransform: "uppercase",
            fontFamily: "'Courier New', monospace",
            background: saving ? "rgba(0,212,255,0.05)" : "rgba(0,212,255,0.12)",
            color: saving ? "#4a6a8a" : "#00d4ff",
            border: "1px solid rgba(0,212,255,0.4)",
            cursor: saving ? "not-allowed" : "pointer",
            boxShadow: saving ? "none" : "0 0 10px rgba(0,212,255,0.1)",
            transition: "all 0.15s",
          }}
        >
          {saving ? "SAVING…" : "SAVE ROUTE"}
        </button>
      </div>

      {/* ── Content ── */}
      <div className="flex-1 overflow-auto">
        {/* LIST mode */}
        {mode === "list" && (
          <div className="p-4">
            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "'Courier New', monospace" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(0,212,255,0.15)" }}>
                  {["#", "NAME", "LAT", "LON", ""].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "4px 8px",
                        textAlign: "left",
                        color: "#4a6a8a",
                        fontSize: 9,
                        letterSpacing: "0.15em",
                        textTransform: "uppercase",
                        fontWeight: 400,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {waypoints.map((wp, i) => (
                  <WaypointRow
                    key={i}
                    wp={wp}
                    index={i}
                    total={waypoints.length}
                    onChange={(updated) =>
                      setWaypoints((wps) => wps.map((w, j) => (j === i ? updated : w)))
                    }
                    onRemove={() => setWaypoints((wps) => wps.filter((_, j) => j !== i))}
                    onMoveUp={() => swapRows(i, i - 1)}
                    onMoveDown={() => swapRows(i, i + 1)}
                  />
                ))}
              </tbody>
            </table>
            <button
              onClick={addRow}
              style={{
                marginTop: 12,
                padding: "5px 16px",
                fontSize: 10,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                fontFamily: "'Courier New', monospace",
                background: "transparent",
                color: "#00d4ff",
                border: "1px dashed rgba(0,212,255,0.4)",
                cursor: "pointer",
              }}
            >
              + ADD WAYPOINT
            </button>
          </div>
        )}

        {/* UPLOAD mode */}
        {mode === "upload" && (
          <div className="p-5" style={{ maxWidth: 600 }}>
            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const f = e.dataTransfer.files[0];
                if (f) handleFile(f);
              }}
              onClick={() => fileRef.current?.click()}
              style={{
                border: `2px dashed ${dragOver ? "#00d4ff" : "rgba(0,212,255,0.25)"}`,
                background: dragOver ? "rgba(0,212,255,0.05)" : "#0a1628",
                padding: "40px 24px",
                textAlign: "center",
                cursor: "pointer",
                transition: "all 0.15s",
                marginBottom: 16,
              }}
            >
              <input
                ref={fileRef}
                type="file"
                accept=".geojson,.json,.kmz"
                style={{ display: "none" }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleFile(f);
                }}
              />
              <div style={{ color: "#4a7a9a", fontFamily: "'Courier New', monospace" }}>
                <div style={{ fontSize: 28, marginBottom: 8 }}>⊕</div>
                <div style={{ fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                  {uploading ? "PARSING…" : "DROP GEOJSON / KMZ OR CLICK TO BROWSE"}
                </div>
              </div>
            </div>

            {uploadErr && (
              <div
                className="mb-4 px-3 py-2 text-xs"
                style={{
                  background: "rgba(239,68,68,0.08)",
                  border: "1px solid rgba(239,68,68,0.3)",
                  color: "#ef4444",
                  fontFamily: "'Courier New', monospace",
                }}
              >
                ⚠ {uploadErr}
              </div>
            )}

            {uploadPreview && (
              <div>
                <div
                  className="mb-2"
                  style={{
                    color: "#4a7a9a",
                    fontSize: 9,
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    fontFamily: "'Courier New', monospace",
                  }}
                >
                  PREVIEW — {uploadPreview.length} WAYPOINTS
                </div>
                <div
                  style={{
                    background: "#0a1628",
                    border: "1px solid rgba(0,212,255,0.1)",
                    maxHeight: 220,
                    overflowY: "auto",
                    fontFamily: "'Courier New', monospace",
                    fontSize: 11,
                  }}
                >
                  {uploadPreview.map((w, i) => (
                    <div
                      key={i}
                      style={{
                        padding: "4px 12px",
                        borderBottom: "1px solid rgba(0,212,255,0.06)",
                        color: "#00ff9d",
                        display: "flex",
                        gap: 16,
                      }}
                    >
                      <span style={{ color: "#3a5070", width: 24 }}>{i + 1}</span>
                      <span style={{ flex: 1 }}>{w.name}</span>
                      <span>{w.lat.toFixed(5)}</span>
                      <span>{w.lon.toFixed(5)}</span>
                    </div>
                  ))}
                </div>
                <button
                  onClick={() => {
                    setWaypoints(uploadPreview);
                    setUploadPreview(null);
                    setMode("list");
                  }}
                  style={{
                    marginTop: 12,
                    padding: "7px 24px",
                    fontSize: 10,
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    fontFamily: "'Courier New', monospace",
                    background: "rgba(34,197,94,0.12)",
                    color: "#22c55e",
                    border: "1px solid rgba(34,197,94,0.5)",
                    cursor: "pointer",
                  }}
                >
                  REPLACE ROUTE
                </button>
              </div>
            )}
          </div>
        )}

        {/* MAP mode */}
        {mode === "map" && (
          <div style={{ height: "100%", minHeight: 400 }}>
            <div
              style={{
                padding: "4px 12px",
                background: "#060f1e",
                borderBottom: "1px solid rgba(0,212,255,0.08)",
                color: "#3a5070",
                fontSize: 9,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                fontFamily: "'Courier New', monospace",
              }}
            >
              CLICK MAP TO APPEND · CLICK MARKER TO REMOVE · DRAG TO MOVE
            </div>
            <div style={{ height: "calc(100% - 26px)" }}>
              <RouteMap waypoints={waypoints} onChange={setWaypoints} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
