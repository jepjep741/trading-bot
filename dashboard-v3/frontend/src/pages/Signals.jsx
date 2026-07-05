import { useMemo, useState } from "react";
import { fmt, shortTs, useApi, useLiveFeed } from "../api.js";
import { Card, EmptyState } from "../components/ui.jsx";

const ACTION_CLS = {
  buy: "bg-accent-dim text-accent",
  sell: "bg-danger-dim text-danger",
  hold: "bg-surface2 text-ink2",
};

function ActionChip({ action }) {
  return (
    <span className={`inline-block rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase ${ACTION_CLS[action] || ""}`}>
      {action}
    </span>
  );
}

function SignalRow({ s }) {
  const claude = s.source === "claude";
  return (
    <div className="border-t border-line py-3 first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
        <span className="text-muted text-[12px] tabular">{shortTs(s.ts)}</span>
        <span className="font-medium">{s.symbol}</span>
        <ActionChip action={s.action} />
        <span className="tabular text-ink2">conf {fmt(s.confidence, 2)}</span>
        <span className="text-[11px] rounded bg-surface2 px-1.5 py-0.5 text-ink2">{s.regime}</span>
        <span className={`text-[11px] rounded px-1.5 py-0.5 ${claude ? "bg-accent-dim text-accent" : "bg-surface2 text-ink2"}`}>
          {s.tier}/{s.source}
        </span>
      </div>
      {s.reasoning && (
        <p className="mt-1.5 text-[12px] leading-relaxed text-ink2 max-w-3xl">
          {s.reasoning.replace(/^\[claude\]\s*/, claude ? "Claude: " : "")}
        </p>
      )}
    </div>
  );
}

export default function Signals() {
  const [live, setLive] = useState([]);
  const connected = useLiveFeed((msg) => {
    if (msg.type === "signal") setLive((prev) => [msg.data, ...prev].slice(0, 50));
  });

  const [fSym, setFSym] = useState("");
  const [fSrc, setFSrc] = useState("");
  const [fFrom, setFFrom] = useState("");
  const [fTo, setFTo] = useState("");

  const { data: signals } = useApi("/api/signals?limit=60", 60000);
  const tradeUrl = useMemo(() => {
    const p = new URLSearchParams();
    if (fSym) p.set("symbol", fSym);
    if (fSrc) p.set("source", fSrc);
    if (fFrom) p.set("date_from", fFrom);
    if (fTo) p.set("date_to", fTo);
    return `/api/trades?${p.toString()}`;
  }, [fSym, fSrc, fFrom, fTo]);
  const { data: trades } = useApi(tradeUrl, 60000);
  const { data: srcData } = useApi("/api/sources", 0);

  const feed = useMemo(() => {
    const seen = new Set();
    return [...live, ...(signals || [])].filter((s) =>
      seen.has(s.id) ? false : (seen.add(s.id), true));
  }, [live, signals]);

  const symbols = useMemo(
    () => [...new Set((trades || []).map((t) => t.symbol)
      .concat((signals || []).map((s) => s.symbol)))].sort(),
    [trades, signals]);

  const input = "bg-surface2 border border-line rounded-lg px-2.5 py-1.5 text-[12px] text-ink outline-none focus:border-accent/60";

  return (
    <div className="space-y-5">
      <Card
        title={
          <span className="flex items-center gap-2">
            Live signal feed
            <span className={`h-2 w-2 rounded-full ${connected ? "bg-good animate-pulse" : "bg-danger"}`}
                  title={connected ? "websocket connected" : "reconnecting…"} />
          </span>
        }
        hint="every decision with its source, confidence, Claude reasoning and regime — streamed over WebSocket"
      >
        {feed.length === 0 ? (
          <EmptyState title="No signals yet"
                      detail="Signals appear here in real time as scan cycles run (every 2 h, scanner every 30 min)." />
        ) : (
          <div className="max-h-[420px] overflow-y-auto pr-1">
            {feed.slice(0, 40).map((s) => <SignalRow key={s.id} s={s} />)}
          </div>
        )}
      </Card>

      <Card title="Trade journal" hint="closed positions with R multiple, holding time and execution path">
        <div className="flex flex-wrap gap-2 mb-4">
          <select className={input} value={fSym} onChange={(e) => setFSym(e.target.value)}>
            <option value="">all symbols</option>
            {symbols.map((s) => <option key={s}>{s}</option>)}
          </select>
          <select className={input} value={fSrc} onChange={(e) => setFSrc(e.target.value)}>
            <option value="">all sources</option>
            {(srcData?.sources || []).map((s) => <option key={s.source}>{s.source}</option>)}
          </select>
          <input type="date" className={input} value={fFrom} onChange={(e) => setFFrom(e.target.value)} />
          <input type="date" className={input} value={fTo} onChange={(e) => setFTo(e.target.value)} />
          <a href={`${tradeUrl}&format=csv`}
             className="ml-auto rounded-lg border border-line px-3 py-1.5 text-[12px] text-ink2 hover:text-ink hover:border-accent/60">
            Export CSV
          </a>
        </div>
        {!trades || trades.length === 0 ? (
          <EmptyState title="No closed trades match"
                      detail="The journal fills as positions close — every exit lands here with its R multiple." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px] whitespace-nowrap">
              <thead>
                <tr className="text-left text-muted text-[11px] uppercase tracking-wider">
                  <th className="py-2 pr-4">Closed</th><th className="pr-4">Symbol</th>
                  <th className="pr-4">Source</th>
                  <th className="pr-4 text-right">Entry</th><th className="pr-4 text-right">Exit</th>
                  <th className="pr-4 text-right">P&L</th><th className="pr-4 text-right">R</th>
                  <th className="pr-4 text-right">Held (h)</th>
                  <th className="pr-4">Exit reason</th><th>Path</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id} className="border-t border-line">
                    <td className="py-2.5 pr-4 text-ink2 text-[12px]">{shortTs(t.closed_at)}</td>
                    <td className="pr-4 font-medium">{t.symbol}</td>
                    <td className="pr-4 text-ink2">{t.source}</td>
                    <td className="pr-4 text-right tabular">{fmt(t.entry, 4)}</td>
                    <td className="pr-4 text-right tabular">{fmt(t.exit, 4)}</td>
                    <td className={`pr-4 text-right tabular ${t.pnl >= 0 ? "text-good" : "text-danger"}`}>
                      {t.pnl >= 0 ? "+" : ""}{fmt(t.pnl)}
                    </td>
                    <td className={`pr-4 text-right tabular font-medium ${t.r_multiple == null ? "text-muted" : t.r_multiple >= 0 ? "text-good" : "text-danger"}`}>
                      {t.r_multiple == null ? "—" : `${t.r_multiple >= 0 ? "+" : ""}${fmt(t.r_multiple, 2)}R`}
                    </td>
                    <td className="pr-4 text-right tabular">{fmt(t.holding_hours, 1)}</td>
                    <td className="pr-4 text-ink2 text-[12px]">{t.exit_reason}</td>
                    <td className="text-ink2 text-[12px]">{t.mode || "paper"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
