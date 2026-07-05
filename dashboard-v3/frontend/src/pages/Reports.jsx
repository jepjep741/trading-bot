import { fmt, fmtPct, useApi } from "../api.js";
import { Card, EmptyState } from "../components/ui.jsx";

export default function Reports() {
  const { data: reports } = useApi("/api/reports", 120000);

  if (!reports) return <EmptyState title="Loading…" />;
  if (reports.length === 0)
    return (
      <Card title="Daily reports">
        <EmptyState title="No reports yet"
                    detail="A report is generated for every day with equity snapshots — the first one appears after the bot's first full day." />
      </Card>
    );

  return (
    <div className="space-y-5">
      {reports.map((r) => {
        const beat = r.return_pct != null && r.benchmark_return_pct != null
          ? r.return_pct >= r.benchmark_return_pct : null;
        return (
          <Card key={r.date}>
            <div className="flex flex-wrap items-baseline gap-3 mb-3">
              <h2 className="text-[15px] font-semibold">{r.date}</h2>
              {beat != null && (
                <span className={`text-[11px] font-semibold rounded-md px-2 py-0.5 ${
                  beat ? "bg-good/15 text-good" : "bg-danger-dim text-danger"}`}>
                  {beat ? "BEAT BENCHMARK" : "BEHIND BENCHMARK"}
                </span>
              )}
            </div>
            {/* the mandated plain-language line */}
            <p className="text-[13px] leading-relaxed mb-4 max-w-3xl">{r.verdict}</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-x-6 gap-y-3 text-[13px]">
              <div><div className="text-[11px] text-muted">Bot return</div>
                <div className={`tabular font-medium ${r.return_pct >= 0 ? "text-good" : "text-danger"}`}>{fmtPct(r.return_pct)}</div></div>
              <div><div className="text-[11px] text-muted">BTC benchmark</div>
                <div className="tabular">{fmtPct(r.benchmark_return_pct)}</div></div>
              <div><div className="text-[11px] text-muted">Realized P&L</div>
                <div className="tabular">{r.realized_pnl >= 0 ? "+" : ""}{fmt(r.realized_pnl)}</div></div>
              <div><div className="text-[11px] text-muted">Trades</div>
                <div className="tabular">{r.trades}</div></div>
              <div><div className="text-[11px] text-muted">Closed / wins</div>
                <div className="tabular">{r.positions_closed} / {r.wins}</div></div>
              <div><div className="text-[11px] text-muted">Fees paid</div>
                <div className="tabular">{fmt(r.fees, 4)}</div></div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
