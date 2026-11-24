"""JAVA trading terminal: one page that shows the whole desk live (inspired by the "6 agents, one shared system"
terminal in the user's video, which itself runs in SIMULATION).

  python3 terminal.py write    # refresh cache/terminal/state.json (the watcher calls this every minute)
  python3 terminal.py serve    # serve the page on http://localhost:8777 (state.json is re-read every 5 s)

The page shows: live prices, each agent's current vote, the open calls with live pips and R, the execution stream
(posts, TP / SL replies, price replies), the bred hunter bots with their tested numbers, and a PAPER account
($10,000, 1% risk per call) that follows every closed call. Nothing here places a real order.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import live
import recom_track

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "cache", "terminal")
START, RISK = 10000.0, 0.01
QUOTES = {"XAUUSD": "OANDA:XAUUSD", "USOIL": "FX:USOIL", "NVDA": "NASDAQ:NVDA", "DXY": "TVC:DXY",
          "S&P 500": "SP:SPX", "VIX": "TVC:VIX", "US10Y": "TVC:US10Y"}
YSYM = {"GC=F": "XAUUSD", "CL=F": "USOIL", "NVDA": "NVDA"}
STREAM_KEYS = ("recom_now sent", "live_recom", "🔥💥❤️", "⏳ نتابع", "TP¹", "TP²", "TP³", "😮SL", "Market shifted",
               "تغيّر السوق", "refreshed", "تم التنفيذ")


def stream(n=30):
    path = os.path.join(HERE, "alerts.log")
    if not os.path.exists(path):
        return []
    lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()[-3000:]
    out = []
    for ln in lines:
        if any(k in ln for k in STREAM_KEYS):
            t, _, msg = ln[11:16], None, ln[17:]
            if "sent" in msg or "posted" in msg:
                kind = "post"
            elif "SL" in msg or "Hard luck" in msg or ("⏳" in msg and ("-" in msg.split("⏳")[1])):
                kind = "loss"
            elif "🔥" in msg or "TP" in msg or "Congrats" in msg or "⏳" in msg:
                kind = "win"
            else:
                kind = "info"
            out.append({"t": t, "msg": msg.replace(" | ", " · ")[:140], "kind": kind})
    return out[-n:][::-1]


def execution():
    """The trading tool: kill switch, modes, which keys exist, and the orders it placed (from its state files)."""
    import alpaca_exec as ax
    lim = ax.limits()
    env = __import__("gold_alerts").load_env(__import__("gold_alerts").ENV_PATH)
    orders = []
    for name, f in (("Alpaca paper", "alpaca_exec_paper"), ("Alpaca LIVE", "alpaca_exec_live"),
                    ("Bybit demo", "bybit_exec_demo"), ("Bybit LIVE", "bybit_exec_live")):
        for k, v in recom_track.load(os.path.join(HERE, "cache", f + ".json"), {}).items():
            if not k.startswith("_") and isinstance(v, dict):
                orders.append({"acct": name, "call": k.split("|")[0], "symbol": v.get("symbol"),
                               "status": v.get("status"), "why": v.get("why") or v.get("error") or ""})
    return {"kill": os.path.exists(os.path.join(ax.SAFE, "KILL_SWITCH")),
            "alpaca": lim.get("mode", "paper"), "bybit": lim.get("bybit_mode", "demo"),
            "approval": lim.get("require_human_approval_per_order", True),
            "keys": {"Alpaca paper": bool(env.get("ALPACA_KEY")), "Bybit demo": bool(env.get("BYBIT_DEMO_KEY"))},
            "orders": orders[-12:][::-1]}


def replay(calls, hist, desk):
    """The trades for the workflow page (workflow.html), newest last: each one walks scan -> hunter -> desk ->
    risk -> post -> Bybit demo -> track -> result. Older history rows have no levels: the key holds name + entry."""
    prefix = {"GOLD": "XAUUSD", "OIL": "USOIL", "NVDA": "NVDA"}
    demo = recom_track.load(os.path.join(HERE, "cache", "bybit_exec_demo.json"), {})
    out = []
    for h in hist[-12:]:
        name, _, rest = h["key"].partition("|")
        sym = YSYM.get(h.get("sym"), None) or next((v for k, v in prefix.items() if name.startswith(k)), name)
        try:
            entry = h.get("entry") or float(rest.split("|")[0])
        except ValueError:
            entry = None
        out.append({"key": h["key"], "sym": sym, "side": h.get("side"), "entry": entry, "stop": h.get("stop"),
                    "t1": h.get("t1"), "t3": h.get("t3"), "exit": h.get("exit"), "r": h["r"], "status": h["status"],
                    "closed": h.get("closed"), "plan": name.endswith("PLAN"), "open": False,
                    "bybit": (demo.get(h["key"]) or {}).get("status") or "", "bybit_why": (demo.get(h["key"]) or {}).get("why", "")})
    for c in calls:
        out.append(dict(c, open=True, status="open", bybit=(demo.get(c["key"]) or {}).get("status") or "",
                        bybit_why=(demo.get(c["key"]) or {}).get("why", "")))
    ysym_back = {v: k for k, v in YSYM.items()}
    for t in out:
        d = desk.get(ysym_back.get(t["sym"], ""), {})
        t["votes"] = d.get("votes", {})
        t["reasons"] = d.get("reasons", {})
    return out


def write():
    q = {k: live.quote(v) for k, v in QUOTES.items()}
    prices = [{"name": k, "px": (v or {}).get("close"), "ch": (v or {}).get("change")} for k, v in q.items()]
    spot = {k: (v or {}).get("close") for k, v in q.items()}
    calls = []
    for key, t in recom_track.load(recom_track.OPEN, {}).items():
        px = spot.get(YSYM.get(t["sym"], t["sym"]))
        r = recom_track.r_of(t, px) if px else 0
        calls.append({"key": key, "sym": YSYM.get(t["sym"], t["sym"]), "side": t["side"], "entry": t["entry"],
                      "stop": t["stop"], "t1": t["t1"], "t2": t["t2"], "t3": t["t3"], "px": px, "r": round(r, 2),
                      "move": recom_track.move(t, "en", px).split(" (")[0] if px else "", "passed": t["passed"],
                      "since": t.get("filled") or t["posted"], "kind": t.get("kind", "")})
    hist = recom_track.load(recom_track.HIST, [])
    eq, curve = START, [START]
    for h in hist:
        eq += eq * RISK * h["r"]
        curve.append(round(eq, 2))
    open_r = sum(c["r"] for c in calls)
    wins = sum(h["r"] > 0 for h in hist)
    desk = recom_track.load(os.path.join(HERE, "cache", "desk_last.json"), {})
    breed = recom_track.load(os.path.join(HERE, "cache", "breed_results.json"), {})
    try:
        import live_recom  # noqa: F401  (import order: live_recom first, then breed)
        import breed as br
        live_bots = {s: [list(x) for x in g] for s, g in br.LIVE.items()}
    except Exception:
        live_bots = {}
    hunters = []
    for s, genes_ in live_bots.items():  # one tested bot per session (asia / london / new york)
        for g in genes_:
            gl = [list(x) if isinstance(x, (tuple, list)) else x for x in g]
            match = None
            for k, v in breed.items():
                if k.split("|")[0] != s:
                    continue
                for sv in v.get("survivors", []):
                    if [list(x) if isinstance(x, (tuple, list)) else x for x in sv["bot"]] == gl:
                        match = sv
                        break
                if match:
                    break
            hunters.append({"sym": f"{YSYM.get(s, s)} · {g[2]}", "bot": g, "in": match and match["in"],
                            "out": match and match["out"], "mc": match and match["mc"]})
    state = {
        "t": datetime.now(timezone.utc).isoformat(), "updated": time.time(),
        "account": {"start": START, "equity": round(eq, 2), "open_r": round(open_r, 2),
                    "live_equity": round(eq * (1 + RISK * open_r), 2), "trades": len(hist), "wins": wins,
                    "win_rate": round(100 * wins / len(hist)) if hist else None, "total_r": round(sum(h["r"] for h in hist), 2),
                    "curve": curve},
        "prices": prices, "calls": calls, "desk": desk, "stream": stream(), "hunters": hunters,
        "bred": {s: {"bred": v.get("bred"), "survived": len(v.get("survivors", []))} for s, v in breed.items()},
        "history": hist[-20:][::-1],
        "forward": __import__("forward").summary(),
        "execution": execution(),
        "replay": replay(calls, hist, desk),
    }
    os.makedirs(DIR, exist_ok=True)
    tmp = os.path.join(DIR, "state.tmp")
    json.dump(state, open(tmp, "w"), default=list)
    os.replace(tmp, os.path.join(DIR, "state.json"))
    return state


def serve(port=8777):
    import http.server
    import shutil
    import socketserver
    os.makedirs(DIR, exist_ok=True)
    shutil.copy(os.path.join(HERE, "terminal.html"), os.path.join(DIR, "index.html"))
    write()
    os.chdir(DIR)

    class H(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):  # always the current terminal.html
                shutil.copy(os.path.join(HERE, "terminal.html"), os.path.join(DIR, "index.html"))
            if self.path.startswith("/workflow"):  # the cursor walk-through of the trading tool
                shutil.copy(os.path.join(HERE, "workflow.html"), os.path.join(DIR, "workflow.html"))
                self.path = "/workflow.html"
            return super().do_GET()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), H) as srv:
        print(f"terminal on http://localhost:{port}")
        srv.serve_forever()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "write"
    if mode == "serve":
        serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8777)
    else:
        s = write()
        print(f"state written: {len(s['calls'])} open calls, equity ${s['account']['equity']:,.2f}")
