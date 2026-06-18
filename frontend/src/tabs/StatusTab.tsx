// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import { useEffect, useRef, useState } from "react";
import { api, Status } from "../api";

function ReadoutRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div
      className="flex items-baseline gap-3 py-1.5"
      style={{ borderBottom: "1px solid rgba(0,212,255,0.06)" }}
    >
      <span
        style={{
          width: 140,
          color: "#4a6a8a",
          fontSize: 10,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          flexShrink: 0,
          fontFamily: "'Courier New', monospace",
        }}
      >
        {label}
      </span>
      <span
        style={{
          color: color ?? "#00ff9d",
          fontSize: 13,
          fontFamily: "'Courier New', monospace",
          wordBreak: "break-all",
        }}
      >
        {value}
      </span>
    </div>
  );
}

function StatusDot({ on, color }: { on: boolean; color: string }) {
  return (
    <span
      className={on ? "dot-pulse" : ""}
      style={{
        display: "inline-block",
        width: 10,
        height: 10,
        borderRadius: "50%",
        background: on ? color : "#1a2a3a",
        color: on ? color : "#1a2a3a",
        boxShadow: on ? `0 0 6px ${color}` : "none",
        marginRight: 8,
      }}
    />
  );
}

export default function StatusTab() {
  const [status, setStatus] = useState<Status | null>(null);
  const [fetchErr, setFetchErr] = useState<string | null>(null);
  const intervalRef = useRef<number | null>(null);

  useEffect(() => {
    const poll = () => {
      api
        .getStatus()
        .then((s) => {
          setStatus(s);
          setFetchErr(null);
        })
        .catch((e) => setFetchErr(String(e?.error ?? e)));
    };
    poll();
    intervalRef.current = window.setInterval(poll, 1500);
    return () => {
      if (intervalRef.current !== null) clearInterval(intervalRef.current);
    };
  }, []);

  const pos = status?.position;

  return (
    <div className="p-5" style={{ maxWidth: 700 }}>
      {/* Panel label */}
      <div
        className="mb-4 pb-2"
        style={{
          borderBottom: "1px solid rgba(0,212,255,0.15)",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <span
          style={{
            color: "#00d4ff",
            fontSize: 10,
            letterSpacing: "0.2em",
            textTransform: "uppercase",
            fontFamily: "'Courier New', monospace",
          }}
        >
          SYSTEM STATUS
        </span>
        <span
          style={{
            flex: 1,
            height: 1,
            background: "rgba(0,212,255,0.12)",
          }}
        />
        <span
          style={{
            color: "#3a5070",
            fontSize: 9,
            fontFamily: "'Courier New', monospace",
          }}
        >
          LIVE · 1.5s
        </span>
      </div>

      {fetchErr && (
        <div
          className="mb-4 px-3 py-2 text-xs"
          style={{
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.3)",
            color: "#ef4444",
            fontFamily: "'Courier New', monospace",
          }}
        >
          ⚠ {fetchErr}
        </div>
      )}

      <div
        className="px-4 py-3"
        style={{
          background: "#0a1628",
          border: "1px solid rgba(0,212,255,0.1)",
        }}
      >
        {/* Running */}
        <div
          className="flex items-center py-1.5"
          style={{ borderBottom: "1px solid rgba(0,212,255,0.06)" }}
        >
          <span
            style={{
              width: 140,
              color: "#4a6a8a",
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              flexShrink: 0,
              fontFamily: "'Courier New', monospace",
            }}
          >
            PIPELINE
          </span>
          <StatusDot on={status?.running ?? false} color="#22c55e" />
          <span
            style={{
              color: status?.running ? "#22c55e" : "#4a6a8a",
              fontSize: 13,
              fontFamily: "'Courier New', monospace",
            }}
          >
            {status == null ? "—" : status.running ? "RUNNING" : "STOPPED"}
          </span>
        </div>

        {/* Connected */}
        <div
          className="flex items-center py-1.5"
          style={{ borderBottom: "1px solid rgba(0,212,255,0.06)" }}
        >
          <span
            style={{
              width: 140,
              color: "#4a6a8a",
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              flexShrink: 0,
              fontFamily: "'Courier New', monospace",
            }}
          >
            SIGNALK LINK
          </span>
          <StatusDot on={status?.connected ?? false} color="#00d4ff" />
          <span
            style={{
              color: status?.connected ? "#00d4ff" : "#4a6a8a",
              fontSize: 13,
              fontFamily: "'Courier New', monospace",
            }}
          >
            {status == null
              ? "—"
              : status.connected
              ? "CONNECTED"
              : "DISCONNECTED"}
          </span>
        </div>

        <ReadoutRow label="TARGET" value={status?.signalk ?? "—"} color="#00d4ff" />
        <ReadoutRow label="SINK" value={status?.sink ?? "—"} color="#00ff9d" />
        <ReadoutRow label="WEATHER" value={status?.weather_source ?? "—"} />
        <ReadoutRow
          label="POSITION"
          value={
            pos
              ? `${pos.lat.toFixed(5)}°N  ${pos.lon.toFixed(5)}°E`
              : "—"
          }
          color="#00ff9d"
        />
        <ReadoutRow
          label="TICK"
          value={status?.tick != null ? String(status.tick) : "—"}
          color="#00d4ff"
        />

        {/* Last error */}
        <div className="flex items-baseline gap-3 pt-1.5">
          <span
            style={{
              width: 140,
              color: "#4a6a8a",
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              flexShrink: 0,
              fontFamily: "'Courier New', monospace",
            }}
          >
            LAST ERROR
          </span>
          <span
            style={{
              color: status?.last_error ? "#ef4444" : "#2a4a2a",
              fontSize: 12,
              fontFamily: "'Courier New', monospace",
              wordBreak: "break-all",
            }}
          >
            {status?.last_error ?? "NONE"}
          </span>
        </div>
      </div>
    </div>
  );
}
