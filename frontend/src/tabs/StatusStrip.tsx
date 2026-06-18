import { useEffect, useRef, useState } from "react";
import { api, Status } from "../api";

function fmtCoord(v: number, isLat: boolean): string {
  const abs = Math.abs(v);
  const deg = Math.floor(abs);
  const min = ((abs - deg) * 60).toFixed(3);
  const dir = isLat ? (v >= 0 ? "N" : "S") : v >= 0 ? "E" : "W";
  return `${deg}°${min}'${dir}`;
}

function ConnectionDot({ status }: { status: Status | null }) {
  let color = "#ef4444"; // red = not running / error
  let title = "offline";

  if (status) {
    if (status.connected) {
      color = "#22c55e";
      title = "connected";
    } else if (status.running && !status.last_error) {
      color = "#f59e0b";
      title = "running — not connected";
    } else if (status.last_error) {
      color = "#ef4444";
      title = "error";
    }
  }

  return (
    <span
      className="dot-pulse inline-block rounded-full flex-shrink-0"
      style={{
        width: 8,
        height: 8,
        background: color,
        color: color,
        boxShadow: `0 0 6px ${color}`,
      }}
      title={title}
    />
  );
}

export default function StatusStrip() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState(false);
  const intervalRef = useRef<number | null>(null);

  useEffect(() => {
    const poll = () => {
      api
        .getStatus()
        .then((s) => {
          setStatus(s);
          setError(false);
        })
        .catch(() => {
          setError(true);
        });
    };
    poll();
    intervalRef.current = window.setInterval(poll, 1500);
    return () => {
      if (intervalRef.current !== null) clearInterval(intervalRef.current);
    };
  }, []);

  const pos = status?.position;

  return (
    <div
      className="flex items-center gap-4 px-3 py-1.5 text-xs overflow-x-auto"
      style={{
        background: "#060f1e",
        borderBottom: "1px solid rgba(0,212,255,0.15)",
        minHeight: 32,
        fontFamily: "'Courier New', monospace",
      }}
    >
      {/* Connection dot */}
      <ConnectionDot status={error ? null : status} />

      {/* Divider */}
      <span style={{ color: "rgba(0,212,255,0.2)", userSelect: "none" }}>│</span>

      {/* SignalK target */}
      <span className="flex items-center gap-1.5 flex-shrink-0">
        <span style={{ color: "#6b8aaa", textTransform: "uppercase", letterSpacing: "0.05em", fontSize: 10 }}>
          SK
        </span>
        <span style={{ color: status ? "#00d4ff" : "#3a5070" }}>
          {status?.signalk ?? "—"}
        </span>
      </span>

      <span style={{ color: "rgba(0,212,255,0.2)", userSelect: "none" }}>│</span>

      {/* Sink */}
      <span className="flex items-center gap-1.5 flex-shrink-0">
        <span style={{ color: "#6b8aaa", textTransform: "uppercase", letterSpacing: "0.05em", fontSize: 10 }}>
          SINK
        </span>
        <span style={{ color: status ? "#00ff9d" : "#3a5070" }}>
          {status?.sink ?? "—"}
        </span>
      </span>

      <span style={{ color: "rgba(0,212,255,0.2)", userSelect: "none" }}>│</span>

      {/* Position */}
      <span className="flex items-center gap-1.5 flex-shrink-0">
        <span style={{ color: "#6b8aaa", textTransform: "uppercase", letterSpacing: "0.05em", fontSize: 10 }}>
          POS
        </span>
        {pos ? (
          <span style={{ color: "#00ff9d" }}>
            {fmtCoord(pos.lat, true)}&nbsp;{fmtCoord(pos.lon, false)}
          </span>
        ) : (
          <span style={{ color: "#3a5070" }}>—</span>
        )}
      </span>

      <span style={{ color: "rgba(0,212,255,0.2)", userSelect: "none" }}>│</span>

      {/* Tick */}
      <span className="flex items-center gap-1.5 flex-shrink-0">
        <span style={{ color: "#6b8aaa", textTransform: "uppercase", letterSpacing: "0.05em", fontSize: 10 }}>
          TICK
        </span>
        <span style={{ color: "#00ff9d" }}>
          {status?.tick ?? "—"}
        </span>
      </span>

      {/* Error — right side */}
      {status?.last_error && (
        <>
          <span style={{ color: "rgba(0,212,255,0.2)", userSelect: "none" }}>│</span>
          <span
            className="flex-shrink-0 truncate max-w-xs"
            style={{ color: "#ef4444", fontSize: 10 }}
            title={status.last_error}
          >
            ⚠ {status.last_error}
          </span>
        </>
      )}
    </div>
  );
}
