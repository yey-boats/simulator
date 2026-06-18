// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
import { useEffect, useRef, useState } from "react";
import { api, Config } from "../api";

/* ── Design tokens ── */
const SINKS = ["signalk", "stdout", "nmea0183", "nmea2000"] as const;
const WEATHER = ["openmeteo", "signalk"] as const;

/* ── Toast ── */
function Toast({ msg, onDone }: { msg: string; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 3000);
    return () => clearTimeout(t);
  }, [onDone]);
  return (
    <div
      className="toast-anim fixed top-0 inset-x-0 z-50 flex justify-center"
      style={{ pointerEvents: "none" }}
    >
      <div
        className="mt-2 px-5 py-2 text-xs"
        style={{
          background: "#0a1e14",
          border: "1px solid #22c55e",
          color: "#22c55e",
          fontFamily: "'Courier New', monospace",
          letterSpacing: "0.08em",
          boxShadow: "0 4px 24px rgba(0,255,100,0.15)",
        }}
      >
        {msg}
      </div>
    </div>
  );
}

/* ── Panel section ── */
function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="mb-5"
      style={{
        background: "#0a1628",
        border: "1px solid rgba(0,212,255,0.1)",
      }}
    >
      <div
        className="px-4 py-2"
        style={{
          borderBottom: "1px solid rgba(0,212,255,0.1)",
          color: "#4a7a9a",
          fontSize: 9,
          letterSpacing: "0.2em",
          textTransform: "uppercase",
          fontFamily: "'Courier New', monospace",
          background: "#060f1e",
        }}
      >
        {title}
      </div>
      <div className="px-4 py-3 flex flex-col gap-3">{children}</div>
    </div>
  );
}

/* ── Field row ── */
function FieldRow({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3">
      <label
        style={{
          width: 160,
          paddingTop: 6,
          color: "#5a7a9a",
          fontSize: 10,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          fontFamily: "'Courier New', monospace",
          flexShrink: 0,
        }}
      >
        {label}
      </label>
      <div className="flex-1 flex flex-col gap-1">
        {children}
        {error && (
          <span
            style={{
              color: "#ef4444",
              fontSize: 10,
              fontFamily: "'Courier New', monospace",
            }}
          >
            ⚠ {error}
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Secret field ── */
function SecretField({
  label,
  fieldKey,
  isSet,
  value,
  onChange,
  error,
}: {
  label: string;
  fieldKey: string;
  isSet: boolean;
  value: string;
  onChange: (v: string) => void;
  error?: string;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <FieldRow label={label} error={error}>
      {!editing ? (
        <div className="flex items-center gap-3">
          <span
            style={{
              color: isSet ? "#22c55e" : "#4a6a8a",
              fontSize: 12,
              fontFamily: "'Courier New', monospace",
            }}
          >
            {isSet ? "● SET" : "○ NOT SET"}
          </span>
          <button
            onClick={() => setEditing(true)}
            style={{
              color: "#00d4ff",
              fontSize: 10,
              fontFamily: "'Courier New', monospace",
              background: "none",
              border: "1px solid rgba(0,212,255,0.3)",
              padding: "2px 10px",
              cursor: "pointer",
              letterSpacing: "0.1em",
            }}
          >
            UPDATE
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <input
            type="password"
            placeholder={`new ${fieldKey}`}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            autoFocus
            style={{ flex: 1, minWidth: 0 }}
          />
          <button
            onClick={() => {
              setEditing(false);
              onChange("");
            }}
            style={{
              color: "#4a6a8a",
              fontSize: 10,
              fontFamily: "'Courier New', monospace",
              background: "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            ✕
          </button>
        </div>
      )}
    </FieldRow>
  );
}

/* ── Main component ── */
export default function ConfigTab() {
  const [config, setConfig] = useState<Config | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // Editable field state — only track what user changes
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [aiskeyVal, setAiskeyVal] = useState("");
  const [sink, setSink] = useState("");
  const [weather, setWeather] = useState("");
  const [failover, setFailover] = useState(false);
  const [dataDir, setDataDir] = useState("");

  // Field errors from 400 response
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const loaded = useRef(false);

  useEffect(() => {
    api
      .getConfig()
      .then((c) => {
        setConfig(c);
        if (!loaded.current) {
          setHost(c.signalk_host);
          setPort(String(c.signalk_port));
          setUsername(c.signalk_username);
          setSink(c.sink);
          setWeather(c.weather_source);
          setFailover(c.failover);
          setDataDir(c.data_dir);
          loaded.current = true;
        }
      })
      .catch((e) => setLoadErr(String(e?.error ?? e)));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setFieldErrors({});
    try {
      const payload: Record<string, unknown> = {};
      if (host !== config?.signalk_host) payload.signalk_host = host;
      const portNum = parseInt(port, 10);
      if (!isNaN(portNum) && portNum !== config?.signalk_port)
        payload.signalk_port = portNum;
      if (username !== config?.signalk_username)
        payload.signalk_username = username;
      if (sink !== config?.sink) payload.sink = sink;
      if (weather !== config?.weather_source) payload.weather_source = weather;
      if (failover !== config?.failover) payload.failover = failover;
      if (dataDir !== config?.data_dir) payload.data_dir = dataDir;
      // secrets — only include if user typed something
      if (password) payload.signalk_password = password;
      if (aiskeyVal) payload.aisstream_api_key = aiskeyVal;

      const updated = await api.putConfig(payload);
      setConfig(updated);
      setToast("Applied — sim restarting…");
      setPassword("");
      setAiskeyVal("");
    } catch (e: unknown) {
      const err = e as { errors?: Record<string, string>; error?: string };
      if (err?.errors) {
        setFieldErrors(err.errors);
      } else {
        setFieldErrors({ _: String(err?.error ?? "Unknown error") });
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-5" style={{ maxWidth: 700 }}>
      {toast && <Toast msg={toast} onDone={() => setToast(null)} />}

      {/* Panel title */}
      <div
        className="mb-5 pb-2 flex items-center gap-3"
        style={{ borderBottom: "1px solid rgba(0,212,255,0.15)" }}
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
          CONNECTION &amp; CONFIG
        </span>
        <span
          style={{ flex: 1, height: 1, background: "rgba(0,212,255,0.12)" }}
        />
      </div>

      {loadErr && (
        <div
          className="mb-4 px-3 py-2 text-xs"
          style={{
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.3)",
            color: "#ef4444",
            fontFamily: "'Courier New', monospace",
          }}
        >
          ⚠ {loadErr}
        </div>
      )}

      {fieldErrors._ && (
        <div
          className="mb-4 px-3 py-2 text-xs"
          style={{
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.3)",
            color: "#ef4444",
            fontFamily: "'Courier New', monospace",
          }}
        >
          ⚠ {fieldErrors._}
        </div>
      )}

      {/* ── SignalK ── */}
      <Section title="SIGNALK SERVER">
        <FieldRow label="HOST" error={fieldErrors.signalk_host}>
          <input
            type="text"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="localhost"
            style={{ width: "100%" }}
          />
        </FieldRow>
        <FieldRow label="PORT" error={fieldErrors.signalk_port}>
          <input
            type="number"
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="3000"
            style={{ width: 120 }}
          />
        </FieldRow>
        <FieldRow label="USERNAME" error={fieldErrors.signalk_username}>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="(none)"
            style={{ width: "100%" }}
          />
        </FieldRow>
        <SecretField
          label="PASSWORD"
          fieldKey="signalk_password"
          isSet={config?.signalk_password_set ?? false}
          value={password}
          onChange={setPassword}
          error={fieldErrors.signalk_password}
        />
      </Section>

      {/* ── AISStream ── */}
      <Section title="AISSTREAM">
        <SecretField
          label="API KEY"
          fieldKey="aisstream_api_key"
          isSet={config?.aisstream_api_key_set ?? false}
          value={aiskeyVal}
          onChange={setAiskeyVal}
          error={fieldErrors.aisstream_api_key}
        />
      </Section>

      {/* ── Simulation ── */}
      <Section title="SIMULATION">
        <FieldRow label="SINK" error={fieldErrors.sink}>
          <select
            value={sink}
            onChange={(e) => setSink(e.target.value)}
            style={{ width: 200 }}
          >
            {SINKS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </FieldRow>
        <FieldRow label="WEATHER SOURCE" error={fieldErrors.weather_source}>
          <select
            value={weather}
            onChange={(e) => setWeather(e.target.value)}
            style={{ width: 200 }}
          >
            {WEATHER.map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </FieldRow>
        <FieldRow label="FAILOVER">
          <button
            type="button"
            onClick={() => setFailover((f) => !f)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
            }}
          >
            <span
              style={{
                display: "inline-block",
                width: 36,
                height: 18,
                background: failover ? "rgba(34,197,94,0.25)" : "rgba(0,212,255,0.08)",
                border: `1px solid ${failover ? "#22c55e" : "rgba(0,212,255,0.3)"}`,
                borderRadius: 2,
                position: "relative",
                transition: "all 0.15s",
              }}
            >
              <span
                style={{
                  position: "absolute",
                  top: 2,
                  left: failover ? 18 : 2,
                  width: 12,
                  height: 12,
                  background: failover ? "#22c55e" : "#4a6a8a",
                  borderRadius: 1,
                  transition: "left 0.15s, background 0.15s",
                }}
              />
            </span>
            <span
              style={{
                color: failover ? "#22c55e" : "#4a6a8a",
                fontSize: 11,
                fontFamily: "'Courier New', monospace",
                letterSpacing: "0.08em",
              }}
            >
              {failover ? "ENABLED" : "DISABLED"}
            </span>
          </button>
        </FieldRow>
        <FieldRow label="DATA DIR" error={fieldErrors.data_dir}>
          <input
            type="text"
            value={dataDir}
            onChange={(e) => setDataDir(e.target.value)}
            placeholder="/path/to/data"
            style={{ width: "100%" }}
          />
        </FieldRow>
      </Section>

      {/* ── Apply button ── */}
      <div className="flex justify-end mt-2">
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            padding: "8px 28px",
            fontSize: 11,
            letterSpacing: "0.15em",
            textTransform: "uppercase",
            fontFamily: "'Courier New', monospace",
            background: saving
              ? "rgba(0,212,255,0.06)"
              : "rgba(0,212,255,0.12)",
            color: saving ? "#4a6a8a" : "#00d4ff",
            border: "1px solid rgba(0,212,255,0.4)",
            cursor: saving ? "not-allowed" : "pointer",
            transition: "all 0.15s",
            boxShadow: saving ? "none" : "0 0 12px rgba(0,212,255,0.12)",
          }}
          onMouseEnter={(e) => {
            if (!saving) {
              (e.currentTarget as HTMLElement).style.background =
                "rgba(0,212,255,0.2)";
              (e.currentTarget as HTMLElement).style.boxShadow =
                "0 0 20px rgba(0,212,255,0.25)";
            }
          }}
          onMouseLeave={(e) => {
            if (!saving) {
              (e.currentTarget as HTMLElement).style.background =
                "rgba(0,212,255,0.12)";
              (e.currentTarget as HTMLElement).style.boxShadow =
                "0 0 12px rgba(0,212,255,0.12)";
            }
          }}
        >
          {saving ? "APPLYING…" : "APPLY"}
        </button>
      </div>
    </div>
  );
}
