import { fmt, shortTs, useApi } from "../api.js";
import { CIBar, Card, EmptyState } from "../components/ui.jsx";

const pct = (v, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);

function Sparkline({ points }) {
  if (!points || points.length < 2)
    return <span className="text-[11px] text-muted">not enough closes</span>;
  const w = 140, h = 36;
  const ys = points.map((p) => p.pnl);
  const lo = Math.min(...ys, 0), hi = Math.max(...ys, 0);
  const X = (i) => (i / (ys.length - 1)) * (w - 4) + 2;
  const Y = (v) => h - 3 - ((v - lo) / (hi - lo || 1)) * (h - 6);
  const d = ys.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const last = ys[ys.length - 1];
  return (
    <svg width={w} height={h} className="block">
      {lo < 0 && hi > 0 && (
        <line x1="2" x2={w - 2} y1={Y(0)} y2={Y(0)} stroke="rgba(148,163,200,0.25)" strokeDasharray="3 3" />
      )}
      <path d={d} fill="none" stroke={last >= 0 ? "#2fbf71" : "#e05252"} strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={X(ys.length - 1)} cy={Y(last)} r="2.6" fill={last >= 0 ? "#2fbf71" : "#e05252"} />
    </svg>
  );
}

function corrColor(v) {
  if (v == null) return "transparent";
  const alpha = Math.min(Math.abs(v), 1) * 0.8;
  return v >= 0 ? `rgba(79,142,247,${alpha})` : `rgba(224,82,82,${alpha})`;
}

export default function Sources() {
  const { data } = useApi("/api/sources", 60000);
  const { data: corr } = useApi("/api/sources/correlation", 60000);
  const { data: curves } = useApi("/api/sources/equity", 60000);

  if (!data) return <EmptyState title="Loading…" />;
  const sources = data.sources || [];

  return (
    <div className="space-y-5">
      <Card
        title="Source statistics"
        hint={`win rates are shrunk toward 50% with a ${data.prior_n}-trade prior — a source only earns its raw rate with volume; bar shows the ~90% credible interval`}
      >
        {sources.length === 0 ? (
          <EmptyState title="No sources yet"
                      detail="Statistics appear after the first closed trades. Each source is a tier × decision-origin pair (technical or Claude)." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px] whitespace-nowrap">
              <thead>
                <tr className="text-left text-muted text-[11px] uppercase tracking-wider">
                  <th className="py-2 pr-4">Source</th>
                  <th className="pr-4 text-right">Trades</th>
                  <th className="pr-4 text-right">Raw WR</th>
                  <th className="pr-4 text-right">Shrunk WR</th>
                  <th className="pr-4">Credible interval</th>
                  <th className="pr-4 text-right">Profit factor</th>
                  <th className="pr-4 text-right">Total P&L</th>
                  <th className="pr-4 text-right">Max DD</th>
                  <th className="pr-4 text-right">Recency WR</th>
                  <th>Last activity</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => {
                  const wr = s.win_rate;
                  const collecting = s.needed_for_estimate > 0;
                  return (
                    <tr key={s.source} className="border-t border-line">
                      <td className="py-2.5 pr-4 font-medium">{s.source}</td>
                      <td className="pr-4 text-right tabular">
                        {s.trades}
                        {collecting && (
                          <span className="ml-1.5 text-[10px] text-warn">
                            +{s.needed_for_estimate} needed
                          </span>
                        )}
                      </td>
                      <td className="pr-4 text-right tabular text-ink2">{pct(wr.raw)}</td>
                      <td className={`pr-4 text-right tabular font-semibold ${collecting ? "text-muted" : ""}`}>
                        {pct(wr.shrunk)}
                        {wr.raw != null && Math.abs(wr.raw - wr.shrunk) > 0.05 && (
                          <span className="ml-1 text-[10px] text-warn" title="heavily shrunk — low sample">↧</span>
                        )}
                      </td>
                      <td className="pr-4"><CIBar low={wr.ci_low} high={wr.ci_high} point={wr.shrunk} /></td>
                      <td className="pr-4 text-right tabular">
                        {s.profit_factor_infinite ? "∞ (no losses yet)" : fmt(s.profit_factor)}
                      </td>
                      <td className={`pr-4 text-right tabular ${s.total_pnl >= 0 ? "text-good" : "text-danger"}`}>
                        {s.total_pnl >= 0 ? "+" : ""}{fmt(s.total_pnl)}
                      </td>
                      <td className="pr-4 text-right tabular">{fmt(s.max_drawdown)}</td>
                      <td className="pr-4 text-right tabular">{pct(s.recency_win_rate)}</td>
                      <td className="text-ink2 text-[12px]">{shortTs(s.last_activity) || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="Correlation between sources"
              hint="Pearson correlation of daily realized P&L — dotted cells lack overlapping trading days">
          {!corr || corr.sources.length < 2 ? (
            <EmptyState title="Needs at least two active sources"
                        detail="The heatmap appears once two sources have closed trades on three or more shared days." />
          ) : (
            <div className="overflow-x-auto">
              <table className="text-[11px]">
                <thead>
                  <tr>
                    <th></th>
                    {corr.sources.map((s) => (
                      <th key={s} className="px-1 pb-2 font-normal text-muted">
                        {s.split("/")[1]}<br />
                        <span className="text-[9px]">{s.split("/")[0]}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {corr.sources.map((a, i) => (
                    <tr key={a}>
                      <td className="pr-2 py-0.5 text-muted whitespace-nowrap">{a}</td>
                      {corr.sources.map((b, j) => (
                        <td key={b} className="p-0.5">
                          <div
                            className="h-9 w-9 rounded flex items-center justify-center text-[10px] tabular border border-line"
                            style={{ background: corrColor(corr.matrix[i][j]) }}
                            title={`${a} × ${b}`}
                          >
                            {corr.matrix[i][j] == null ? "·" : corr.matrix[i][j].toFixed(2)}
                          </div>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Per-source equity" hint="cumulative realized P&L per source, small multiples">
          {!curves || Object.keys(curves).length === 0 ? (
            <EmptyState title="No closed trades yet"
                        detail="Each source gets its own running P&L curve after its first closed position." />
          ) : (
            <div className="grid sm:grid-cols-2 gap-4">
              {Object.entries(curves).map(([source, points]) => (
                <div key={source} className="rounded-lg border border-line bg-surface2/40 p-3">
                  <div className="flex items-baseline justify-between mb-1">
                    <span className="text-[12px] font-medium">{source}</span>
                    <span className={`text-[12px] tabular ${points[points.length - 1].pnl >= 0 ? "text-good" : "text-danger"}`}>
                      {points[points.length - 1].pnl >= 0 ? "+" : ""}{fmt(points[points.length - 1].pnl)}
                    </span>
                  </div>
                  <Sparkline points={points} />
                  <div className="text-[10px] text-muted mt-1">{points.length} closed trade{points.length === 1 ? "" : "s"}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
