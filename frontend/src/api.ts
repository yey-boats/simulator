// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
export type Config = {
  signalk_host: string;
  signalk_port: number;
  signalk_username: string;
  signalk_password_set: boolean;
  aisstream_api_key_set: boolean;
  sink: string;
  weather_source: string;
  failover: boolean;
  data_dir: string;
};

export type Waypoint = { name: string; lat: number; lon: number };

export type Status = {
  running: boolean;
  connected: boolean;
  sink: string;
  weather_source: string;
  signalk: string;
  position: { lat: number; lon: number } | null;
  tick: number;
  last_error: string | null;
};

const token = () => localStorage.getItem("sim_token") || "";

const headers = () => {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token()) h["X-Sim-Token"] = token();
  return h;
};

async function req(method: string, path: string, body?: unknown) {
  const r = await fetch(path, {
    method,
    headers: headers(),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw await r.json().catch(() => ({ error: r.statusText }));
  return r.json();
}

export const api = {
  getConfig: (): Promise<Config> => req("GET", "/api/config"),
  putConfig: (
    c: Partial<Config> & { signalk_password?: string; aisstream_api_key?: string }
  ) => req("PUT", "/api/config", c) as Promise<Config>,
  getRoute: (): Promise<{ waypoints: Waypoint[]; current_index: number }> =>
    req("GET", "/api/route"),
  putRoute: (waypoints: Waypoint[]) => req("PUT", "/api/route", { waypoints }),
  getStatus: (): Promise<Status> => req("GET", "/api/status"),
  importRoute: async (file: File): Promise<{ waypoints: Waypoint[] }> => {
    const fd = new FormData();
    fd.append("file", file);
    const h: Record<string, string> = {};
    if (token()) h["X-Sim-Token"] = token();
    const r = await fetch("/api/route/import", { method: "POST", body: fd, headers: h });
    if (!r.ok) throw await r.json().catch(() => ({ error: r.statusText }));
    return r.json();
  },
};
