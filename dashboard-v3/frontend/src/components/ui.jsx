import { fmt } from "../api.js";

export function Card({ title, hint, children, className = "" }) {
  return (
    <section className={`card p-5 md:p-6 ${className}`}>
      {title && (
        <header className="mb-4">
          <h2 className="text-[14px] font-semibold">{title}</h2>
          {hint && <p className="text-[12px] text-muted mt-0.5">{hint}</p>}
        </header>
      )}
      {children}
    </section>
  );
}

export function StatTile({ label, value, sub, tone }) {
  const toneCls =
    tone === "good" ? "text-good" : tone === "bad" ? "text-danger" : "";
  return (
    <div className="card px-4 py-3.5">
      <div className="text-[12px] text-ink2">{label}</div>
      <div className={`text-[22px] font-semibold mt-0.5 tabular ${toneCls}`}>{value}</div>
      {sub && <div className="text-[11px] text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

export function EmptyState({ title, detail }) {
  return (
    <div className="py-10 text-center">
      <div className="text-[13px] text-ink2">{title}</div>
      {detail && <div className="text-[12px] text-muted mt-1 max-w-md mx-auto">{detail}</div>}
    </div>
  );
}

export function StatusBanner({ status }) {
  if (!status) return null;
  const spec = {
    RUNNING: { cls: "border-good/40 bg-good/10", dot: "bg-good", text: "RUNNING" },
    HALTED: { cls: "border-warn/40 bg-warn/10", dot: "bg-warn", text: "HALTED" },
    KILL_SWITCH: { cls: "border-danger bg-danger/15", dot: "bg-danger", text: "KILL SWITCH ACTIVE" },
    BOT_OFFLINE: { cls: "border-danger/40 bg-danger/10", dot: "bg-danger", text: "BOT OFFLINE" },
  }[status.state] || {};
  const mode = status.mode === "paper"
    ? { cls: "bg-good/15 text-good border-good/30", text: "PAPER" }
    : status.mode === "live-testnet"
    ? { cls: "bg-warn/15 text-warn border-warn/30", text: "LIVE · TESTNET" }
    : { cls: "bg-danger/25 text-danger border-danger font-bold", text: "⚠ LIVE — REAL FUNDS" };
  return (
    <div className={`flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 ${spec.cls}`}>
      <span className={`h-2.5 w-2.5 rounded-full ${spec.dot} ${status.state === "RUNNING" ? "animate-pulse" : ""}`} />
      <span className="text-[14px] font-semibold tracking-wide">{spec.text}</span>
      {status.reason && <span className="text-[13px] text-ink2">— {status.reason}</span>}
      <span className={`ml-auto rounded-md border px-2.5 py-1 text-[11px] font-semibold tracking-wider ${mode.cls}`}>
        {mode.text}
      </span>
    </div>
  );
}

export function Meter({ value, max, goodWhenHigh = true }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const color = (goodWhenHigh ? pct > 50 : pct < 50) ? "bg-good" : pct > 25 ? "bg-warn" : "bg-danger";
  return (
    <div className="h-1.5 w-full rounded-full bg-surface2 overflow-hidden">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function CIBar({ low, high, point }) {
  return (
    <div className="relative h-1.5 w-24 rounded-full bg-surface2">
      <div
        className="absolute h-full rounded-full bg-accent/40"
        style={{ left: `${low * 100}%`, width: `${Math.max((high - low) * 100, 2)}%` }}
      />
      <div
        className="absolute top-1/2 -translate-y-1/2 h-2.5 w-0.5 bg-ink rounded"
        style={{ left: `${point * 100}%` }}
      />
    </div>
  );
}
