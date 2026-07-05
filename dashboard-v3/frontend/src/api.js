import { useEffect, useRef, useState } from "react";

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export function useApi(path, refreshMs = 0) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api(path).then((d) => alive && (setData(d), setError(null)))
               .catch((e) => alive && setError(e));
    load();
    const id = refreshMs ? setInterval(load, refreshMs) : null;
    return () => { alive = false; if (id) clearInterval(id); };
  }, [path, refreshMs]);
  return { data, error, reload: () => api(path).then(setData) };
}

/** WebSocket with exponential-backoff reconnect. onMessage({type, data}) */
export function useLiveFeed(onMessage) {
  const [connected, setConnected] = useState(false);
  const cbRef = useRef(onMessage);
  cbRef.current = onMessage;
  useEffect(() => {
    let ws, closed = false, delay = 1000, pingId;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => {
        setConnected(true);
        delay = 1000;
        pingId = setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000);
      };
      ws.onmessage = (ev) => {
        try { cbRef.current(JSON.parse(ev.data)); } catch { /* ignore */ }
      };
      ws.onclose = () => {
        setConnected(false);
        clearInterval(pingId);
        if (!closed) {
          setTimeout(connect, delay);
          delay = Math.min(delay * 2, 15000);
        }
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => { closed = true; clearInterval(pingId); ws && ws.close(); };
  }, []);
  return connected;
}

export const fmt = (v, d = 2) =>
  v == null ? "—" : v.toLocaleString("en-US",
    { minimumFractionDigits: d, maximumFractionDigits: d });
export const fmtPct = (v, d = 2) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${fmt(v, d)}%`;
export const shortTs = (ts) => (ts || "").replace("T", " ").replace(/\+.*$/, "");
