import { useEffect, useState } from "react";
import { api, shortTs, useApi } from "../api.js";
import { Card, EmptyState } from "../components/ui.jsx";

const RESET_PHRASE = "RESET PAPER ACCOUNT";

const btn = "rounded-lg px-3.5 py-2 text-[13px] font-medium border transition-colors disabled:opacity-40";
const btnNeutral = `${btn} border-line text-ink2 hover:text-ink hover:border-accent/60`;
const btnDanger = `${btn} border-danger/50 text-danger hover:bg-danger-dim`;
const input = "bg-surface2 border border-line rounded-lg px-3 py-2 text-[13px] text-ink outline-none focus:border-accent/60 w-full";

function Login({ onDone }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/admin/login", { method: "POST", body: { password: pw } });
      onDone();
    } catch (ex) { setErr(ex.message); }
  };
  return (
    <Card title="Admin login" hint="password comes from the DASHBOARD_ADMIN_PASSWORD environment variable" className="max-w-sm">
      <form onSubmit={submit} className="space-y-3">
        <input type="password" className={input} placeholder="Admin password"
               value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
        {err && <p className="text-[12px] text-danger">{err}</p>}
        <button className={`${btn} border-accent/60 text-accent hover:bg-accent-dim w-full`}>Sign in</button>
      </form>
    </Card>
  );
}

function TierEditor({ tier, onChange }) {
  return (
    <div className="rounded-lg border border-line bg-surface2/40 p-4 space-y-3">
      <div className="text-[13px] font-medium">{tier.name}</div>
      <label className="block text-[12px] text-ink2">
        Position size — % of equity
        <span className="text-muted"> (cap {tier.position_pct_cap}%, can only go down)</span>
        <input type="number" step="0.1" min="0.1" max={tier.position_pct_cap}
               className={`${input} mt-1`} value={tier.position_pct}
               onChange={(e) => onChange({ ...tier, position_pct: parseFloat(e.target.value) || tier.position_pct })} />
      </label>
      <label className="block text-[12px] text-ink2">
        Confidence threshold
        <span className="text-muted"> (floor {tier.confidence_threshold_floor}, can only go up)</span>
        <input type="number" step="0.01" min={tier.confidence_threshold_floor} max="0.99"
               className={`${input} mt-1`} value={tier.confidence_threshold}
               onChange={(e) => onChange({ ...tier, confidence_threshold: parseFloat(e.target.value) || tier.confidence_threshold })} />
      </label>
      <label className="block text-[12px] text-ink2">
        Watchlist <span className="text-muted">(comma-separated, /{"USDT"} pairs)</span>
        <textarea rows="2" className={`${input} mt-1 font-mono text-[12px]`}
                  value={tier.symbols.join(", ")}
                  onChange={(e) => onChange({ ...tier, symbols: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
      </label>
      <div className="text-[11px] text-muted">
        TP +{tier.take_profit_pct}% / SL −{tier.stop_loss_pct}% — fixed, not editable here
      </div>
    </div>
  );
}

export default function Admin() {
  const [authed, setAuthed] = useState(null);
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [resetText, setResetText] = useState("");
  const [cfg, setCfg] = useState(null);
  const { data: overview, reload } = useApi("/api/overview", 30000);
  const { data: audit } = useApi(authed ? "/api/admin/audit" : "/api/admin/session", 30000);

  const checkSession = () =>
    api("/api/admin/session").then((s) => { setAuthed(s.authed); setEnabled(s.enabled); });
  useEffect(() => { checkSession(); }, []);
  useEffect(() => {
    if (authed) api("/api/admin/config").then(setCfg).catch(() => {});
  }, [authed]);

  if (authed === null) return <EmptyState title="Loading…" />;
  if (!enabled)
    return <Card title="Admin disabled">
      <EmptyState title="DASHBOARD_ADMIN_PASSWORD is not set"
                  detail="Set the environment variable on the dashboard process and restart it to enable the admin panel. Read-only pages work without it." />
    </Card>;
  if (!authed) return <Login onDone={checkSession} />;

  const status = overview?.status;
  const act = async (label, path, body) => {
    if (!confirm(label)) return;
    setBusy(true);
    try {
      await api(path, { method: "POST", body });
      setNote(`${label} — done`);
      reload();
    } catch (ex) { setNote(`failed: ${ex.message}`); }
    setBusy(false);
  };

  const saveConfig = async () => {
    if (!confirm("Save configuration overrides? Values beyond the hard caps are clamped by the bot.")) return;
    const overrides = {
      tiers: Object.fromEntries(cfg.effective.tiers.map((t) => [t.name, {
        position_pct: t.position_pct,
        confidence_threshold: t.confidence_threshold,
        symbols: t.symbols,
      }])),
      max_open_positions: cfg.effective.max_open_positions,
      max_daily_loss_pct: cfg.effective.max_daily_loss_pct,
    };
    if (cfg.effective.scanner) {
      overrides.scanner = {
        position_pct: cfg.effective.scanner.position_pct,
        confidence_threshold: cfg.effective.scanner.confidence_threshold,
        symbols: cfg.effective.scanner.symbols,
      };
    }
    setBusy(true);
    try {
      await api("/api/admin/config", { method: "PUT", body: { overrides } });
      setNote("configuration saved (applied from the next cycle)");
      api("/api/admin/config").then(setCfg);
    } catch (ex) { setNote(`failed: ${ex.message}`); }
    setBusy(false);
  };

  return (
    <div className="space-y-5">
      {note && (
        <div className="rounded-lg border border-accent/40 bg-accent-dim px-4 py-2.5 text-[13px]">
          {note}
        </div>
      )}

      <Card title="Trading controls" hint="every action needs confirmation and is written to the audit log; execution happens in the bot process">
        <div className="flex flex-wrap gap-2.5">
          {status?.state === "HALTED" ? (
            <button disabled={busy} className={btnNeutral}
                    onClick={() => act("Resume trading (new entries allowed again)?", "/api/admin/pause", { paused: false })}>
              ▶ Resume trading
            </button>
          ) : (
            <button disabled={busy} className={btnNeutral}
                    onClick={() => act("Pause trading? No new entries; existing TP/SL stay live.", "/api/admin/pause", { paused: true })}>
              ⏸ Pause new entries
            </button>
          )}
          {status?.state === "KILL_SWITCH" ? (
            <button disabled={busy} className={btnDanger}
                    onClick={() => act("Clear the kill switch and let the bot scan again?", "/api/admin/kill", { active: false })}>
              Clear kill switch
            </button>
          ) : (
            <button disabled={busy} className={btnDanger}
                    onClick={() => act("TRIGGER KILL SWITCH? The bot stops scanning and entering entirely; exits stay live.", "/api/admin/kill", { active: true })}>
              ⛔ Kill switch
            </button>
          )}
          <button disabled={busy} className={btnDanger}
                  onClick={() => act("Market-close ALL open positions now?", "/api/admin/flatten", {})}>
            Flatten all positions
          </button>
        </div>
      </Card>

      {cfg && (
        <Card title="Configuration — within hard caps only"
              hint="risk can be lowered freely; raising is clamped at the config-file ceilings. Trading mode, TP/SL and the caps themselves are not editable here.">
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {cfg.effective.tiers.map((t, i) => (
              <TierEditor key={t.name} tier={t}
                          onChange={(nt) => {
                            const tiers = [...cfg.effective.tiers];
                            tiers[i] = nt;
                            setCfg({ ...cfg, effective: { ...cfg.effective, tiers } });
                          }} />
            ))}
            {cfg.effective.scanner && (
              <TierEditor tier={cfg.effective.scanner}
                          onChange={(nt) => setCfg({ ...cfg,
                            effective: { ...cfg.effective, scanner: nt } })} />
            )}
          </div>
          <div className="grid sm:grid-cols-2 gap-4 mt-4 max-w-xl">
            <label className="block text-[12px] text-ink2">
              Max open positions <span className="text-muted">(cap {cfg.effective.max_open_positions_cap})</span>
              <input type="number" min="1" max={cfg.effective.max_open_positions_cap}
                     className={`${input} mt-1`} value={cfg.effective.max_open_positions}
                     onChange={(e) => setCfg({ ...cfg, effective: { ...cfg.effective, max_open_positions: parseInt(e.target.value) || 1 } })} />
            </label>
            <label className="block text-[12px] text-ink2">
              Daily loss circuit breaker % <span className="text-muted">(cap {cfg.effective.max_daily_loss_pct_cap}%)</span>
              <input type="number" step="0.5" min="0.5" max={cfg.effective.max_daily_loss_pct_cap}
                     className={`${input} mt-1`} value={cfg.effective.max_daily_loss_pct}
                     onChange={(e) => setCfg({ ...cfg, effective: { ...cfg.effective, max_daily_loss_pct: parseFloat(e.target.value) || 0.5 } })} />
            </label>
          </div>
          <div className="flex items-center gap-3 mt-5">
            <button disabled={busy} onClick={saveConfig}
                    className={`${btn} border-accent/60 text-accent hover:bg-accent-dim`}>
              Save overrides
            </button>
            <span className="text-[12px] text-muted">
              mode: <b className="text-ink2">{cfg.immutable.mode}{cfg.immutable.mode === "live" && cfg.immutable.testnet ? " (testnet)" : ""}</b> — switching to live is config-file + CLI only, never a button
            </span>
          </div>
        </Card>
      )}

      <Card title="Reset paper account"
            hint="wipes positions, trades, signals and equity history; requires the exact phrase">
        <div className="flex flex-wrap items-center gap-2.5 max-w-xl">
          <input className={`${input} flex-1`} placeholder={`type "${RESET_PHRASE}"`}
                 value={resetText} onChange={(e) => setResetText(e.target.value)} />
          <button disabled={busy || resetText !== RESET_PHRASE} className={btnDanger}
                  onClick={() => act("Really wipe the paper journal and start over?", "/api/admin/reset",
                                     { confirmation: resetText })}>
            Reset
          </button>
        </div>
      </Card>

      <Card title="Audit log" hint="every admin action, newest first">
        {!Array.isArray(audit) || audit.length === 0 ? (
          <EmptyState title="No admin actions logged yet" />
        ) : (
          <div className="max-h-64 overflow-y-auto">
            <table className="w-full text-[12px]">
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id} className="border-t border-line first:border-t-0">
                    <td className="py-1.5 pr-4 text-muted tabular whitespace-nowrap">{shortTs(a.ts)}</td>
                    <td className="pr-4 font-medium">{a.action}</td>
                    <td className="text-ink2 truncate max-w-[300px]">{a.detail}</td>
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
