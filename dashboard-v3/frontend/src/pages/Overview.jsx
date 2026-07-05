import { useState } from "react";
import {
  Area, AreaChart, CartesianGrid, Line, Legend,
  ResponsiveContainer, Tooltip, XAxis, YAxis, ComposedChart,
} from "recharts";
import { fmt, fmtPct, shortTs, useApi, useLiveFeed } from "../api.js";
import { Card, EmptyState, Meter, StatTile, StatusBanner } from "../components/ui.jsx";

export default function Overview() {
  const { data, reload } = useApi("/api/overview", 60000);
  const [liveStatus, setLiveStatus] = useState(null);
  useLiveFeed((msg) => {
    if (msg.type === "status") setLiveStatus(msg.data);
    if (msg.type === "trade") reload();
  });

  if (!data) return <EmptyState title="Loading…" />;
  const status = liveStatus || data.status;
  const t = data.today;
  const curve = (data.curve || []).map((p) => ({
    ...p, label: shortTs(p.ts).slice(5, 16),
  }));
  const skipped = Object.entries(t.skipped || {});

  return (
    <div className="space-y-5">
      <StatusBanner status={status} />

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatTile
          label={`Today's P&L (${data.quote})`}
          value={t.pnl == null ? "—" : `${t.pnl >= 0 ? "+" : ""}${fmt(t.pnl)}`}
          sub={t.pnl_pct == null ? "no snapshot yet today" : fmtPct(t.pnl_pct)}
          tone={t.pnl == null ? undefined : t.pnl >= 0 ? "good" : "bad"}
        />
        <StatTile label="Trades today" value={t.trades} sub={`${t.signals} signals evaluated`} />
        <StatTile
          label="Signals skipped"
          value={skipped.reduce((a, [, n]) => a + n, 0)}
          sub={skipped.map(([k, n]) => `${n} ${k}`).join(" · ") || "none today"}
        />
        <div className="card px-4 py-3.5">
          <div className="text-[12px] text-ink2">Daily loss budget left</div>
          <div className="text-[22px] font-semibold mt-0.5 tabular">
            {fmt(t.remaining_loss_budget_pct, 2)}%
          </div>
          <div className="mt-2">
            <Meter value={t.remaining_loss_budget_pct}
                   max={t.remaining_loss_budget_pct - (t.pnl_pct ?? 0) || 5} />
          </div>
        </div>
        <StatTile
          label="Consecutive losses"
          value={t.consecutive_losses}
          sub={`${data.open_positions.length} open position${data.open_positions.length === 1 ? "" : "s"}`}
          tone={t.consecutive_losses >= 3 ? "bad" : undefined}
        />
      </div>

      <Card title="Equity vs buy-and-hold BTC"
            hint="paper account value against simply holding Bitcoin from the first snapshot">
        {curve.length < 2 ? (
          <EmptyState
            title="Collecting data"
            detail={`${curve.length} equity snapshot${curve.length === 1 ? "" : "s"} so far — one is stored on every scan cycle (every 2 h). The chart appears after the second snapshot.`}
          />
        ) : (
          <div className="h-64">
            <ResponsiveContainer>
              <ComposedChart data={curve} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
                <CartesianGrid stroke="rgba(148,163,200,0.08)" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: "#5d6880", fontSize: 11 }}
                       tickLine={false} axisLine={{ stroke: "rgba(148,163,200,0.15)" }}
                       minTickGap={60} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: "#5d6880", fontSize: 11 }}
                       tickLine={false} axisLine={false} width={70}
                       tickFormatter={(v) => v.toLocaleString()} />
                <Tooltip
                  contentStyle={{ background: "#1a2130", border: "1px solid rgba(148,163,200,0.2)",
                                  borderRadius: 10, fontSize: 12 }}
                  labelStyle={{ color: "#9aa5bc" }}
                  formatter={(v, name) => [fmt(v), name]}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area type="monotone" dataKey="equity" name="Bot equity"
                      stroke="#4f8ef7" strokeWidth={2} fill="#4f8ef7" fillOpacity={0.08}
                      dot={false} activeDot={{ r: 4 }} />
                <Line type="monotone" dataKey="benchmark" name="Buy & hold BTC"
                      stroke="#9aa5bc" strokeWidth={1.5} strokeDasharray="5 4"
                      dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <Card title="Open positions">
        {data.open_positions.length === 0 ? (
          <EmptyState title="No open positions"
                      detail="Entries require a fresh SMA crossover above the tier's confidence threshold — flat periods are normal." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-muted text-[11px] uppercase tracking-wider">
                  <th className="py-2 pr-4">Symbol</th><th className="pr-4">Tier</th>
                  <th className="pr-4 text-right">Qty</th><th className="pr-4 text-right">Entry</th>
                  <th className="pr-4 text-right">TP</th><th className="pr-4 text-right">SL</th>
                  <th className="pr-4">Opened</th><th>Mode</th>
                </tr>
              </thead>
              <tbody>
                {data.open_positions.map((p) => (
                  <tr key={p.id} className="border-t border-line">
                    <td className="py-2.5 pr-4 font-medium">{p.symbol}</td>
                    <td className="pr-4 text-ink2">{p.tier}</td>
                    <td className="pr-4 text-right tabular">{p.qty}</td>
                    <td className="pr-4 text-right tabular">{fmt(p.entry_price, 4)}</td>
                    <td className="pr-4 text-right tabular text-good">{fmt(p.take_profit, 4)}</td>
                    <td className="pr-4 text-right tabular text-danger">{fmt(p.stop_loss, 4)}</td>
                    <td className="pr-4 text-ink2">{shortTs(p.opened_at)}</td>
                    <td className="text-ink2">{p.mode}</td>
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
