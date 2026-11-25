"""The trading DESK: a team of small agents that read the market together before any call is posted to java_recomm.

Built from what the AI-trading videos describe (a swarm of single-job bots under one lead that only speaks when
something needs a decision): scanner, setup hunter, newsroom, flows, risk skeptic ("what could go wrong?"),
a lead who decides (only when the backtested Hunter fires), and a reviewer who grades the agents after the trades close and re-weights them.

  python3 desk.py test [GC=F|CL=F]   # every agent's vote for the symbol now, nothing posted
  python3 desk.py review             # grade the agents on closed calls and update their weights

Every agent returns a vote in [-1, +1] (+ = buy, - = sell, 0 = no opinion) and a short reason. The lead adds the
weighted votes; a call needs |score| >= THRESHOLD and no veto from Risk. LIVE data only: the price must match the
TradingView spot within 0.4%, or the Risk agent vetoes (this is what "out of date" looked like before).
The LLM agent (Newsroom) cannot be backtested; the Scout and Hunter can (live_recom.py backtest). Info only.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import gold_alerts as ga
import live
import live_recom as lr
import recom
import recom_track
import zone_plan as zp

HERE = os.path.dirname(os.path.abspath(__file__))
WEIGHTS = os.path.join(HERE, "cache", "desk_weights.json")
LOG = os.path.join(HERE, "cache", "desk_log.jsonl")
NEWS = os.path.join(HERE, "cache", "desk_news.json")
LAST = os.path.join(HERE, "cache", "desk_last.json")
THRESHOLD = 2.0
# Confidence sizing (2026-11-24, from the "confidence score sets the size" video): over 446 backtested hunter trades
# a flat Scout (no trend, no momentum) did worst (gold -0.31R avg) while Scout WITH or AGAINST the hunter both paid.
# Full size when the market is moving, 0.4x when flat beat flat sizing in all 4 half-samples. Never above 1.0x:
# the executors' max loss per trade stays the ceiling.
SIZE_MOVING, SIZE_FLAT = 1.0, 0.4
BASE_W = {"hunter": 2.0}  # 2-agent desk (2026-11-25): Hunter votes, Risk vetoes
SPOT = {"GC=F": "OANDA:XAUUSD", "CL=F": "FX:USOIL", "NVDA": "NASDAQ:NVDA"}
NAME = {"GC=F": "GOLD", "CL=F": "OIL", "NVDA": "NVDA"}


def weights():
    w = dict(BASE_W)
    w.update({k: v for k, v in recom_track.load(WEIGHTS, {}).items() if k in BASE_W})
    return w


# Real-time 5-minute bars (tvbars.py). Yahoo's GC=F runs ~10 min late: the hunter only saw half-formed setup bars and
# missed all 6 gold setups on 2026-11-25; entering 10 min late also erased the gold edge. Tested on OANDA:XAUUSD bars
# (30 Oct - 25 Nov): 95 trades +0.19R, both halves positive. Oil stays on Yahoo: on TV spot its edge was ~0R.
TV_BARS = {"GC=F": "OANDA:XAUUSD", "NVDA": "NASDAQ:NVDA"}  # NVDA: Yahoo gave yesterday's close at the open


def bars(sym):
    if sym in TV_BARS:
        try:
            import tvbars
            b = tvbars.bars(TV_BARS[sym], "5", 1500)
            if b and time.time() - b[-1]["ts"] < 15 * 60:  # the last one is the forming candle
                return b
        except Exception as e:
            ga.log(f"desk tvbars {sym} failed, using Yahoo: {e}")
    return [x for x in zp.yahoo_bars(sym, "5d", "5m") if x["v"] is not None]


def scout(sym, b):
    """Trend + momentum + volatility from the 5-minute candles."""
    E = lr.emas(b)
    i = len(b) - 2
    c = b[i]["c"]
    trend = 1 if E[1][i] > E[2][i] and c > E[2][i] else -1 if E[1][i] < E[2][i] and c < E[2][i] else 0
    mom = (c - b[i - 12]["c"]) / b[i - 12]["c"]
    m = 1 if mom > 0.0008 else -1 if mom < -0.0008 else 0
    return (trend + m) / 2, f"trend {trend:+d}, 1h momentum {100 * mom:+.2f}%"


SEEN = os.path.join(HERE, "cache", "hunter_seen.json")  # last setup bar posted per symbol: never post one twice
_fired = {}


def mark_seen(sym, ts):
    seen = recom_track.load(SEEN, {})
    seen[sym] = max(seen.get(sym, 0), ts or 0)
    json.dump(seen, open(SEEN, "w"))


def hunter(sym, b):
    """The backtested setup rule on the newest finished bars.
    Real-time bars (TV_BARS: gold, NVDA): the last 2 closed bars, setup under 12 minutes old.
    Yahoo bars (oil) run ~10 min late: only grid-aligned bars Yahoo has finished (its last bar is still filling),
    setup under 30 minutes old. On 2026-11-25 the old check missed 5 of 7 oil setups. Entering 10 min late kept the
    oil edge in the backtest (+0.14R over 60 days), unlike gold. A bar already posted is never used again."""
    seen = recom_track.load(SEEN, {}).get(sym, 0)
    if sym in TV_BARS:
        rows, idx, max_age = b, (len(b) - 2, len(b) - 3), 12 * 60 + 300
    else:
        rows = [x for x in b if x["ts"] % 300 == 0 and x.get("v")][:-1]
        idx, max_age = (len(rows) - 1, len(rows) - 2), 30 * 60
    E = lr.emas(rows)
    for i in idx:
        if i < 0 or time.time() - rows[i]["ts"] > max_age or rows[i]["ts"] <= seen:
            continue
        s = lr.RULE[sym](rows, i, E)
        if s:
            _fired[sym] = rows[i]["ts"]
            return (1 if s["side"] == "buy" else -1), f"{lr.RULE[sym].__name__} setup {s['side']}"
    _fired.pop(sym, None)
    return 0, "no setup on the last closed bars"


def flows(sym):
    """Where the big money moves: dollar, yields, stocks, fear gauge (TradingView, live)."""
    q = {k: live.quote(v) for k, v in {"dxy": "TVC:DXY", "y10": "TVC:US10Y", "spx": "SP:SPX", "vix": "TVC:VIX"}.items()}
    ch = lambda k: (q[k] or {}).get("change") or 0
    if sym == "GC=F":  # gold likes a weak dollar and falling yields
        v = (-1 if ch("dxy") > 0.3 else 1 if ch("dxy") < -0.3 else 0) + (-1 if ch("y10") > 1.0 else 1 if ch("y10") < -1.0 else 0)
        return v / 2, f"dollar {ch('dxy'):+.2f}%, 10y {ch('y10'):+.2f}%"
    if sym == "NVDA":  # a stock follows the market and the fear gauge
        v = (1 if ch("spx") > 0.5 else -1 if ch("spx") < -0.5 else 0) + (1 if ch("vix") < -3 else -1 if ch("vix") > 3 else 0)
        return v / 2, f"S&P {ch('spx'):+.2f}%, VIX {ch('vix'):+.1f}%"
    v = (1 if ch("spx") > 0.5 else -1 if ch("spx") < -0.5 else 0) + (-1 if ch("dxy") > 0.5 else 1 if ch("dxy") < -0.5 else 0)
    return v / 2, f"stocks {ch('spx'):+.2f}%, dollar {ch('dxy'):+.2f}%"


def newsroom(sym):
    """Realtime first (news_rt: last-3h headlines, age-weighted net sentiment, refreshed every 2 min); when no
    recent headline is about the asset, an LLM reads the last 2 days of headlines (cached 30 min).
    + supports a buy, - against it."""
    if sym in ("GC=F", "CL=F", "NVDA"):
        try:
            import news_agent  # newsroom v2: top sources, data surprises, learned weights (2026-11-24)
            v, why, n = news_agent.vote(sym)
            if n:
                return v, why
        except Exception as e:
            ga.log(f"desk news_rt {sym} failed: {e}")
    cache = recom_track.load(NEWS, {})
    hit = cache.get(sym)
    if hit and time.time() - hit["t"] < 1800:
        return hit["v"], hit["why"]
    try:
        r = recom.research(NAME[sym], "buy")
    except Exception:
        r = None
    v = {"support": 1, "against": -1}.get((r or {}).get("verdict"), 0)
    why = (r or {}).get("en") or "no model answer"
    cache[sym] = {"t": time.time(), "v": v, "why": why}
    json.dump(cache, open(NEWS, "w"))
    return v, why


CAL = os.path.join(HERE, "cache", "ff_calendar.json")


def release_near(ts, before=30 * 60, after=15 * 60):
    """A medium/high-impact US release from 30 min before to 15 min after now (live ForexFactory week calendar,
    cached 6 h). The hardcoded regime.EVENTS list only holds the big ones; on 2026-11-24 a gold buy was posted
    13 min before CB Consumer Confidence (10:00 ET) and stopped out."""
    try:  # live TradingView calendar first; the ForexFactory week below is the fallback
        import news_agent
        hit = news_agent.release_near(ts, before, after)
        if hit or news_agent.calendar():
            return hit
    except Exception as e:
        ga.log(f"desk news_agent calendar failed: {e}")
    cal = recom_track.load(CAL, {})
    if time.time() - cal.get("t", 0) > 6 * 3600:
        try:
            cal = {"t": time.time(), "events": json.loads(ga.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", tries=2))}
            json.dump(cal, open(CAL, "w"))
        except Exception as e:  # rate-limited (429) easily: keep the old week, retry in 20 min
            ga.log(f"desk calendar failed: {e}")
            cal["t"] = time.time() - 6 * 3600 + 20 * 60
            json.dump(cal, open(CAL, "w"))
    for e in cal.get("events", []):
        if e.get("country") != "USD" or e.get("impact") not in ("High", "Medium"):
            continue
        try:
            et = datetime.fromisoformat(e["date"]).timestamp()
        except Exception:
            continue
        if et - before <= ts <= et + after:
            return f"{e['title']} at {datetime.fromtimestamp(et).strftime('%H:%M')}"
    return None


def headline_against(sym, side, window=30 * 60):
    """A strong headline (score 2) against the side in the last 30 min, e.g. 'Fed won't rule out back-to-back
    hikes' against a gold buy. Returns its title or None."""
    try:
        import news_rt
        items = news_rt.refresh()["items"].values()
    except Exception:
        return None
    sign = -1 if side == "buy" else 1
    for h in sorted(items, key=lambda h: -h["ts"]):
        if time.time() - h["ts"] > window:
            break
        if (h.get("score") or {}).get(sym, 0) * sign >= 2:
            return h["title"][:90]
    return None


def risk(sym, b):
    """The skeptic: reasons NOT to trade. Any returned reason is a veto."""
    out = []
    now = datetime.now(timezone.utc)
    spot = live.quote(SPOT[sym])
    if not spot or abs(b[-1]["c"] - spot["close"]) / spot["close"] > 0.004:
        out.append("price data out of date vs the live spot")
    if now.timestamp() - b[-1]["ts"] > 10 * 60:
        out.append("market closed or no fresh 5-min bar")
    tr = [max(x["h"], p["c"]) - min(x["l"], p["c"]) for p, x in zip(b[-15:-1], b[-14:])]
    long_tr = [max(x["h"], p["c"]) - min(x["l"], p["c"]) for p, x in zip(b[-289:-1], b[-288:])]
    if tr and long_tr and sum(tr) / len(tr) > 3 * sum(long_tr) / len(long_tr):
        out.append("volatility spike (3x normal)")
    today = now.strftime("%Y-%m-%d")
    hhmm = now.hour * 60 + now.minute
    for d, _ in __import__("regime").EVENTS:
        if d == today:
            # 30 min before to 15 min after the release (8:30 NY = 13:30 UTC; Fed on 12-09 at 19:00 UTC). It used to
            # block 2.5 h (12:30-15:00 UTC), freezing @@ all afternoon on 11-25 ("stopping all trades like an idiot").
            lo, hi = (18 * 60 + 30, 19 * 60 + 45) if now.month == 12 and now.day == 9 else (13 * 60, 13 * 60 + 45)
            if lo <= hhmm <= hi:
                out.append("major news release window")
    ev = release_near(now.timestamp())
    if ev:
        out.append(f"US release window: {ev}")
    hist = recom_track.load(recom_track.HIST, [])[-3:]
    if len(hist) == 3 and all(h["r"] < 0 for h in hist) and now.timestamp() - hist[-1]["closed"] < 3600:
        out.append("3 losses in a row: paused for an hour")
    return out


def decide(sym):
    """The lead: {"side", "score", "votes", "reasons", "veto", "px"}; side None = no call."""
    b = bars(sym)
    w = weights()
    votes, reasons = {}, {}
    # 2 agents only (user, 2026-11-25): the HUNTER (the backtested setup) votes, the RISK skeptic can veto.
    # Scout, Flows and Newsroom no longer vote; the scout reading is kept only for the tested trade size below.
    try:
        votes["hunter"], reasons["hunter"] = hunter(sym, b)
    except Exception as e:
        votes["hunter"], reasons["hunter"] = 0, f"agent failed: {e}"
    veto = risk(sym, b)
    score = votes["hunter"] * w["hunter"]
    h = votes["hunter"]
    side = "buy" if h > 0 else "sell" if h < 0 else None
    if side and sym in ("GC=F", "CL=F"):
        hl = headline_against(sym, side)
        if hl:
            veto.append(f"fresh headline against a {side}: {hl}")
    if veto:
        side = None
    try:
        moving = scout(sym, b)[0]
    except Exception:
        moving = 1
    size = SIZE_MOVING if moving else SIZE_FLAT
    out = {"sym": sym, "side": side, "score": round(score, 2), "votes": votes, "reasons": reasons, "veto": veto,
           "bar_ts": _fired.get(sym),
           "px": b[-1]["c"], "size": size, "t": time.time()}
    try:  # the latest reading per symbol, for the terminal (terminal.py)
        last = recom_track.load(LAST, {})
        last[sym] = out
        json.dump(last, open(LAST, "w"))
    except Exception:
        pass
    return out


def log_call(key, dk):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps({"key": key, "side": dk["side"], "votes": dk["votes"], "t": time.time()}) + "\n")


def review():
    """The reviewer: grade each agent on closed calls (right = its vote matched the winning side), then nudge its
    weight within 0.5-2x of the base once it has 20+ graded calls. Small steps, so it cannot over-fit quickly."""
    hist = {h["key"]: h for h in recom_track.load(recom_track.HIST, [])}
    rows = [json.loads(x) for x in open(LOG)] if os.path.exists(LOG) else []
    score = {k: [0, 0] for k in BASE_W}
    for r in rows:
        h = hist.get(r["key"])
        if not h or h["status"] == "shifted":
            continue
        win_side = r["side"] if h["r"] > 0 else ("sell" if r["side"] == "buy" else "buy")
        for k, v in r["votes"].items():
            if v and k in score:
                score[k][1] += 1
                score[k][0] += (1 if (v > 0) == (win_side == "buy") else 0)
    w = recom_track.load(WEIGHTS, {})
    for k, (ok, n) in score.items():
        if n >= 20:
            rate = ok / n
            w[k] = round(min(2.0, max(0.5, BASE_W[k] * (0.5 + rate))), 2)
    json.dump(w, open(WEIGHTS, "w"))
    return score, w


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    if mode == "review":
        print(review())
    else:
        for sym in ([sys.argv[2]] if len(sys.argv) > 2 else ["GC=F", "CL=F"]):
            d = decide(sym)
            print(f"\n=== {NAME[sym]} @ {d['px']:.2f}  → {d['side'] or 'NO CALL'}  (score {d['score']}, need ±{THRESHOLD})")
            for k in d["votes"]:
                print(f"  {k:7s} {d['votes'][k]:+.1f} × {weights()[k]}  {d['reasons'][k]}")
            print("  risk   ", d["veto"] or "no veto")
