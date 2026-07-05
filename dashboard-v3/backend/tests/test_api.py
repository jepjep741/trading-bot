"""API + stats + admin test suite."""


def test_overview_shape(client):
    d = client.get("/api/overview").json()
    assert d["status"]["state"] in ("RUNNING", "HALTED", "KILL_SWITCH", "BOT_OFFLINE")
    assert d["status"]["mode"] == "paper"
    assert d["today"]["consecutive_losses"] >= 0
    assert isinstance(d["curve"], list) and len(d["curve"]) > 0
    assert "equity" in d["curve"][0]


def test_sources_stats_and_shrinkage(client):
    d = client.get("/api/sources").json()
    sources = {s["source"]: s for s in d["sources"]}
    assert "stable-core/technical" in sources
    tech = sources["stable-core/technical"]
    assert tech["trades"] == 2
    wr = tech["win_rate"]
    # 2 wins of 2 raw = 100%, but shrinkage must pull it hard toward 50%
    assert wr["raw"] == 1.0
    assert 0.5 < wr["shrunk"] < 0.65
    assert wr["ci_low"] < wr["shrunk"] < wr["ci_high"]
    assert tech["needed_for_estimate"] > 0   # far below the minimum trades


def test_sources_correlation_and_equity(client):
    corr = client.get("/api/sources/correlation").json()
    assert corr["sources"]
    n = len(corr["sources"])
    assert len(corr["matrix"]) == n and len(corr["matrix"][0]) == n
    curves = client.get("/api/sources/equity").json()
    assert "stable-core/technical" in curves


def test_signals_and_trades_filters(client):
    sig = client.get("/api/signals?symbol=BTC/USDT").json()
    assert all(s["symbol"] == "BTC/USDT" for s in sig)
    tr = client.get("/api/trades?source=stable-core/claude").json()
    assert all(t["source"] == "stable-core/claude" for t in tr)
    assert all("r_multiple" in t and "holding_hours" in t for t in tr)
    csv_resp = client.get("/api/trades?format=csv")
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "r_multiple" in csv_resp.text.splitlines()[0]


def test_reports(client):
    reps = client.get("/api/reports").json()
    assert reps and reps[0]["date"] >= reps[-1]["date"]   # newest first
    assert "verdict" in reps[0] and reps[0]["verdict"]


def test_admin_requires_auth(client):
    client.post("/api/admin/logout")
    assert client.post("/api/admin/pause", json={"paused": True}).status_code == 401
    assert client.get("/api/admin/config").status_code == 401


def test_admin_wrong_password_and_rate_limit(client):
    for i in range(5):
        r = client.post("/api/admin/login", json={"password": "nope"})
        assert r.status_code == 401
    r = client.post("/api/admin/login", json={"password": "nope"})
    assert r.status_code == 429   # rate limited after 5 attempts
    # reset the limiter for the rest of the suite
    from app import auth
    auth._attempts.clear()


def test_admin_pause_kill_flatten_audit(admin_client):
    assert admin_client.post("/api/admin/pause", json={"paused": True}).json()["paused"]
    assert admin_client.post("/api/admin/kill", json={"active": True}).json()["kill_switch"]
    status = admin_client.get("/api/overview").json()["status"]
    assert status["state"] == "KILL_SWITCH"
    admin_client.post("/api/admin/kill", json={"active": False})
    admin_client.post("/api/admin/pause", json={"paused": False})
    assert admin_client.post("/api/admin/flatten").json()["queued"]
    actions = [a["action"] for a in admin_client.get("/api/admin/audit").json()]
    for expected in ("pause", "kill_switch_on", "kill_switch_cleared", "flatten_all"):
        assert expected in actions


def test_admin_config_caps(admin_client):
    cfg = admin_client.get("/api/admin/config").json()
    cap = cfg["effective"]["tiers"][0]["position_pct_cap"]
    # try to exceed every cap — the merge must clamp
    admin_client.put("/api/admin/config", json={"overrides": {
        "tiers": {"stable-core": {"position_pct": cap * 10,
                                  "confidence_threshold": 0.01}},
        "max_daily_loss_pct": 99, "max_open_positions": 99}})
    eff = admin_client.get("/api/admin/config").json()["effective"]
    t0 = eff["tiers"][0]
    assert t0["position_pct"] == cap                       # cannot raise risk
    assert t0["confidence_threshold"] == t0["confidence_threshold_floor"]
    assert eff["max_daily_loss_pct"] == eff["max_daily_loss_pct_cap"]
    assert eff["max_open_positions"] == eff["max_open_positions_cap"]
    # lowering risk is allowed
    admin_client.put("/api/admin/config", json={"overrides": {
        "tiers": {"stable-core": {"position_pct": 1.0}}}})
    eff = admin_client.get("/api/admin/config").json()["effective"]
    assert eff["tiers"][0]["position_pct"] == 1.0
    admin_client.put("/api/admin/config", json={"overrides": {}})


def test_admin_reset_needs_exact_phrase(admin_client):
    assert admin_client.post("/api/admin/reset",
                             json={"confirmation": "reset"}).status_code == 400


def test_live_mode_is_not_reachable_from_api(admin_client):
    cfg = admin_client.get("/api/admin/config").json()
    assert "mode" in cfg["immutable"]
    # there is no endpoint that accepts a mode change — prove the config PUT
    # cannot smuggle one in
    admin_client.put("/api/admin/config", json={"overrides": {"mode": "live",
                                                              "testnet": False}})
    cfg2 = admin_client.get("/api/admin/config").json()
    assert cfg2["immutable"]["mode"] == cfg["immutable"]["mode"]
