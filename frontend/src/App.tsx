// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import { useState } from "react";
import StatusStrip from "./tabs/StatusStrip";
import ConfigTab from "./tabs/ConfigTab";
import RouteTab from "./tabs/RouteTab";
import StatusTab from "./tabs/StatusTab";

type Tab = "connection" | "route" | "status";

const TABS: { id: Tab; label: string }[] = [
  { id: "connection", label: "CONNECTION" },
  { id: "route", label: "ROUTE" },
  { id: "status", label: "STATUS" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("connection");

  return (
    <div
      className="flex flex-col"
      style={{ minHeight: "100vh", background: "#040d1a" }}
    >
      {/* ── Header bar ── */}
      <header
        style={{
          background: "#060f1e",
          borderBottom: "1px solid rgba(0,212,255,0.2)",
        }}
      >
        {/* Branding row */}
        <div
          className="flex items-center gap-3 px-4 py-2"
          style={{ borderBottom: "1px solid rgba(0,212,255,0.08)" }}
        >
          {/* Anchor icon */}
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            style={{ color: "#00d4ff", flexShrink: 0 }}
          >
            <circle
              cx="12"
              cy="5"
              r="2"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <line
              x1="12"
              y1="7"
              x2="12"
              y2="20"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path
              d="M6 10 C6 17 18 17 18 10"
              stroke="currentColor"
              strokeWidth="1.5"
              fill="none"
            />
            <line
              x1="4"
              y1="14"
              x2="8"
              y2="14"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <line
              x1="16"
              y1="14"
              x2="20"
              y2="14"
              stroke="currentColor"
              strokeWidth="1.5"
            />
          </svg>
          <span
            style={{
              color: "#00d4ff",
              fontSize: 11,
              letterSpacing: "0.2em",
              textTransform: "uppercase",
              fontFamily: "'Courier New', monospace",
            }}
          >
            YEY BOATS SIM
          </span>
          <span
            style={{
              color: "rgba(0,212,255,0.3)",
              fontSize: 10,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              marginLeft: "auto",
              fontFamily: "'Courier New', monospace",
            }}
          >
            ADMIN CONSOLE
          </span>
        </div>

        {/* Status strip */}
        <StatusStrip />

        {/* Tab bar */}
        <div
          className="flex"
          style={{ borderTop: "1px solid rgba(0,212,255,0.08)" }}
        >
          {TABS.map(({ id, label }) => {
            const active = tab === id;
            return (
              <button
                key={id}
                onClick={() => setTab(id)}
                style={{
                  padding: "8px 20px",
                  fontSize: 10,
                  letterSpacing: "0.15em",
                  fontFamily: "'Courier New', monospace",
                  textTransform: "uppercase",
                  background: active ? "rgba(0,212,255,0.06)" : "transparent",
                  color: active ? "#00d4ff" : "#4a6a8a",
                  borderBottom: active
                    ? "2px solid #00d4ff"
                    : "2px solid transparent",
                  borderTop: "none",
                  borderLeft: "none",
                  borderRight: "1px solid rgba(0,212,255,0.08)",
                  cursor: "pointer",
                  transition: "color 0.15s, background 0.15s",
                  boxShadow: active
                    ? "0 2px 12px rgba(0,212,255,0.1)"
                    : "none",
                  outline: "none",
                }}
                onMouseEnter={(e) => {
                  if (!active)
                    (e.currentTarget as HTMLElement).style.color = "#6b9ab8";
                }}
                onMouseLeave={(e) => {
                  if (!active)
                    (e.currentTarget as HTMLElement).style.color = "#4a6a8a";
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </header>

      {/* ── Tab content ── */}
      <main className="flex-1 overflow-auto" style={{ padding: "0" }}>
        {tab === "connection" && <ConfigTab />}
        {tab === "route" && <RouteTab />}
        {tab === "status" && <StatusTab />}
      </main>
    </div>
  );
}
